import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Pattern, Sequence, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, LoadingIndicator

from ferp.core.messages import (
    BulkDeleteRequest,
    BulkPasteRequest,
    CreatePathRequest,
    DeletePathRequest,
    DirectorySelectRequest,
    NavigateRequest,
    RenamePathRequest,
)
from ferp.core.protocols import AppWithPath
from ferp.core.state import FileTreeState, FileTreeStateStore
from ferp.core.worker_groups import WorkerGroup
from ferp.widgets.dialogs import BulkRenameConfirmDialog

if TYPE_CHECKING:
    from ferp.core.app import Ferp


@dataclass(frozen=True)
class FileListingEntry:
    path: Path
    display_name: str
    char_count: int
    type_label: str
    is_dir: bool
    search_blob: str


def _split_replace_input(value: str) -> tuple[str, str, str] | None:
    if value.startswith("/"):
        second = value.find("/", 1)
        if second == -1:
            return None
        pattern = value[1:second]
        replacement = value[second + 1 :]
        return "regex", pattern, replacement

    if "/" not in value:
        return None
    pattern, replacement = value.split("/", 1)
    return "literal", pattern, replacement


def _filter_query_for_input(value: str) -> str:
    parsed = _split_replace_input(value)
    if parsed is None:
        return value

    mode, pattern, _replacement = parsed
    if mode == "regex":
        return f"/{pattern}"
    return pattern


def _escape_regex_replacement(replacement: str) -> str:
    return replacement.replace("\\", r"\\").replace("$", r"\$")


def _split_stem_suffix(name: str) -> tuple[str, str]:
    suffix = Path(name).suffix
    if suffix in ("", "."):
        suffix = ""
    stem = name[: -len(suffix)] if suffix else name
    return stem, suffix


def _replace_in_stem(
    name: str, *, matcher: Pattern[str], replacement: str
) -> tuple[str, str, int]:
    stem, suffix = _split_stem_suffix(name)
    new_stem, count = matcher.subn(replacement, stem)
    new_name = f"{new_stem}{suffix}"
    return new_name, new_stem, count


class FileRow(Widget):
    CHARS_WIDTH = 8
    TYPE_WIDTH = 8
    GAP = 1

    def __init__(
        self,
        *,
        name: str,
        chars: str,
        type_label: str,
        is_header: bool = False,
        classes: str | None = None,
    ) -> None:
        row_classes = "file_tree_row"
        if is_header:
            row_classes = f"{row_classes} file_tree_header"
        if classes:
            row_classes = f"{row_classes} {classes}"
        super().__init__(classes=row_classes)
        self._name = name
        self._chars = chars
        self._type_label = type_label

    @staticmethod
    def _truncate(value: str, width: int) -> str:
        if width <= 0:
            return ""
        if len(value) <= width:
            return value
        if width <= 3:
            return value[:width]
        return f"{value[: width - 3]}..."

    def render(self) -> Text:
        width = self.size.width
        name_width = max(
            1, width - (self.CHARS_WIDTH + self.TYPE_WIDTH + (self.GAP * 2))
        )
        name = self._truncate(self._name, name_width)
        chars = self._truncate(self._chars, self.CHARS_WIDTH)
        type_label = self._truncate(self._type_label, self.TYPE_WIDTH)

        name_seg = name.ljust(name_width)
        chars_seg = chars.ljust(self.CHARS_WIDTH)
        type_seg = type_label.ljust(self.TYPE_WIDTH)
        gap = " " * self.GAP

        text = Text()
        text.append(f"{name_seg}{gap}{chars_seg}{gap}{type_seg}")
        text.stylize(self.rich_style)
        return text


class FileItem(ListItem):
    def __init__(
        self,
        path: Path,
        *,
        metadata: FileListingEntry,
        classes: str | None = None,
        **kwargs,
    ) -> None:
        self.path = path
        self.is_header = False
        self.metadata = metadata

        row = FileRow(
            name=metadata.display_name,
            chars=str(metadata.char_count),
            type_label=metadata.type_label,
            classes="file_tree_type_dir" if metadata.is_dir else "file_tree_type_file",
        )

        super().__init__(row, classes=classes, **kwargs)

    def on_click(self, event: Click) -> None:
        if event.chain < 2:
            return
        parent = self.parent
        if isinstance(parent, FileTree):
            parent._activate_item(self)

    def render(self) -> Text:
        # Prevent fallback ListItem text (e.g., "FileItem.item_file") during refresh.
        return Text("")


class ChunkNavigatorItem(ListItem):
    """Interactive row to navigate between file list chunks."""

    def __init__(self, label: str, *, direction: str) -> None:
        super().__init__(
            Label(label, classes="file_tree_notice"), classes="item_notice"
        )
        self.direction = direction


class FileTreeHeader(Widget):
    """Static header row for the file tree list."""

    def compose(self) -> ComposeResult:
        yield FileRow(
            name="Name",
            chars="Chars",
            type_label="Type",
            is_header=True,
            classes="file_tree_header_row",
        )


class FileTreeFilterWidget(Widget):
    """Hidden input bar for filtering file tree entries."""

    DEBOUNCE_DELAY = 0.4
    BINDINGS = [
        Binding("escape", "hide", "Hide filter", show=True),
    ]

    def __init__(
        self, *, state_store: FileTreeStateStore, id: str | None = None
    ) -> None:
        super().__init__(id=id)
        self._state_store = state_store
        self.display = "none"
        self._input: Input | None = None
        self._debounce_timer: Timer | None = None
        self._pending_value = ""

    def compose(self) -> ComposeResult:
        yield Input(
            placeholder="Filter entries (type to refine) — use find/replace or /regex/replace",
            id="file_tree_filter_input",
        )

    def on_mount(self) -> None:
        self._input = self.query_one(Input)

    def show(self, value: str) -> None:
        # Don't show filter widget if file tree is maximized, since the input won't be visible.
        if focused := self.app.focused:
            try:
                if cast(Widget, focused.parent).is_maximized:
                    return
            except AttributeError:
                pass
        self.display = "block"
        if self._input:
            self._input.value = value
            self._input.focus()
        self._pending_value = value

    def hide(self) -> None:
        self.display = "none"
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
            self._debounce_timer = None
        file_tree = self.app.query_one("#file_list")
        file_tree.focus()

    def action_hide(self) -> None:
        self.hide()

    @on(Input.Changed)
    def handle_changed(self, event: Input.Changed) -> None:
        if self._input is None or event.input is not self._input:
            return
        self._pending_value = event.value
        self._schedule_filter_apply()

    @on(Input.Submitted)
    def handle_submit(self, event: Input.Submitted) -> None:
        if self._input is None or event.input is not self._input:
            return
        file_tree = self.app.query_one("#file_list", FileTree)
        file_tree.handle_filter_submit(event.value)
        self.hide()

    @on(Input.Blurred)
    def handle_blur(self, event: Input.Blurred) -> None:
        if self._input is None or event.input is not self._input:
            return
        self.hide()

    def _schedule_filter_apply(self) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
            self._debounce_timer = None
        self._debounce_timer = self.set_timer(
            self.DEBOUNCE_DELAY,
            self._apply_pending_filter,
            name="file-tree-filter-debounce",
        )

    def _apply_pending_filter(self) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.stop()
            self._debounce_timer = None
        self._state_store.set_filter_query(_filter_query_for_input(self._pending_value))


class FileTreeContainer(Vertical):
    ALLOW_MAXIMIZE = True


class FileTree(ListView):
    ALLOW_MAXIMIZE = False
    CHUNK_SIZE = 50
    FILTER_TITLE_MAX = 24
    CHUNK_DEBOUNCE_S = 0.25
    FAST_CURSOR_STEP = 5
    BINDINGS = [
        Binding("enter", "activate_item", "Select directory", show=False),
        Binding("g", "cursor_top", "To top", show=False),
        Binding("G", "cursor_bottom", "To bottom", key_display="G", show=False),
        Binding("k", "cursor_up", "Cursor up", show=False),
        Binding("K", "cursor_up_fast", "Cursor up (fast)", key_display="K", show=False),
        Binding("j", "cursor_down", "Cursor down", show=False),
        Binding(
            "J",
            "cursor_down_fast",
            "Cursor down (fast)",
            key_display="J",
            show=False,
        ),
        Binding("ctrl+t", "open_terminal", "Terminal", show=False),
        Binding(
            "u",
            "go_parent",
            "Go to parent",
            show=True,
            tooltip="Go to parent directory",
        ),
        Binding(
            "h",
            "go_home",
            "Go to start",
            show=True,
            tooltip="Go to default startup path",
        ),
        Binding(
            "e",
            "rename_entry",
            "Rename",
            show=False,
            tooltip="Edit name of selected file or directory",
        ),
        Binding(
            "n",
            "new_file",
            "New File",
            show=False,
            tooltip="Create new raw file",
        ),
        Binding(
            "N",
            "new_directory",
            "New Directory",
            key_display="N",
            show=False,
            tooltip="Create new directory in current directory",
        ),
        Binding(
            "delete",
            "delete_entry",
            "Delete",
            show=False,
            tooltip="Delete selected file or directory",
        ),
        Binding(
            "v",
            "toggle_visual_mode",
            "Visual mode",
            show=True,
            tooltip="Toggle visual selection mode",
        ),
        Binding(
            "s",
            "toggle_select",
            "Select",
            show=False,
            tooltip="Toggle selection (visual mode)",
        ),
        Binding(
            "S",
            "select_range",
            "Select range",
            key_display="Shift+S",
            show=False,
            tooltip="Select range (visual mode)",
        ),
        Binding(
            "c",
            "copy_selection",
            "Copy",
            show=False,
            tooltip="Copy selected items (visual mode)",
        ),
        Binding(
            "x",
            "move_selection",
            "Move",
            show=False,
            tooltip="Move selected items (visual mode)",
        ),
        Binding(
            "p",
            "paste_selection",
            "Paste",
            show=False,
            tooltip="Paste copied/moved items (visual mode)",
        ),
        Binding(
            "f",
            "toggle_favorite",
            "Favorite",
            show=False,
            tooltip="Toggle favorite for highlighted item",
        ),
        Binding(
            "F",
            "open_favorites",
            "Favorites",
            key_display="Shift+F",
            show=False,
            tooltip="Open favorites list",
        ),
        Binding(
            "i",
            "show_info",
            "Info",
            show=False,
            tooltip="Show file info",
        ),
        Binding(
            "a",
            "select_all",
            "Select all",
            show=False,
            tooltip="Select all visible items (visual mode)",
        ),
        Binding(
            "A",
            "deselect_all",
            "Deselect all",
            key_display="Shift+A",
            show=False,
            tooltip="Clear all selections (visual mode)",
        ),
        Binding(
            "escape",
            "clear_staging",
            "Clear staged",
            show=False,
            tooltip="Clear staged items (visual mode)",
        ),
        Binding(
            "ctrl+f",
            "open_finder",
            "Open in FS",
            show=True,
            tooltip="Open current directory in system file explorer",
        ),
        Binding(
            "ctrl+o",
            "open_selected_file",
            "Open file",
            show=True,
            tooltip="Open selected file with default application",
        ),
        Binding(
            "[", "prev_chunk", "Prev chunk", show=False, tooltip="Load previous chunk"
        ),
        Binding("]", "next_chunk", "Next chunk", show=False, tooltip="Load next chunk"),
        Binding(
            "{", "first_chunk", "First chunk", show=False, tooltip="Jump to first chunk"
        ),
        Binding(
            "}", "last_chunk", "Last chunk", show=False, tooltip="Jump to last chunk"
        ),
        Binding("/", "filter_entries", "Filter", show=True, tooltip="Filter entries"),
    ]

    def __init__(self, *args, state_store: FileTreeStateStore, **kwargs) -> None:
        super().__init__(*args, initial_index=None, **kwargs)
        self._state_store = state_store
        self._state_subscription = self._handle_state_update
        self._all_entries: list[FileListingEntry] = []
        self._filtered_entries: list[FileListingEntry] = []
        self._filter_query = state_store.state.filter_query
        self._filter_error = False
        self._chunk_start = 0
        self._current_listing_path = state_store.state.current_listing_path
        self._selection_history = dict(state_store.state.selection_history)
        self._last_chunk_direction: str | None = None
        self._pending_delete_index: int | None = None
        self._pending_chunk_delta = 0
        self._chunk_timer: Timer | None = None
        self._listing_changed = False
        self._suppress_focus_once = False
        self._current_chunk_items: dict[Path, FileItem] = {}
        self._selected_paths: set[Path] = set()
        self._selection_anchor: Path | None = None
        self._visual_clipboard_paths: list[Path] = []
        self._visual_clipboard_mode: str | None = None
        self._subtitle_base = ""

    def set_pending_delete_index(self, index: int | None) -> None:
        self._pending_delete_index = index

    def on_mount(self) -> None:
        self._state_store.subscribe(self._state_subscription)
        self._update_border_title()

    def on_unmount(self) -> None:
        self._state_store.unsubscribe(self._state_subscription)

    def action_go_parent(self) -> None:
        app = cast(AppWithPath, self.app)
        self.post_message(NavigateRequest(app.current_path.parent))

    def action_go_home(self) -> None:
        self._state_store.clear_selection_history()
        app = cast(AppWithPath, self.app)
        self.post_message(NavigateRequest(app.resolve_startup_path()))

    def action_open_finder(self) -> None:
        app = cast(AppWithPath, self.app)
        self._open_with_default_app(app.current_path)

    def action_open_selected_file(self) -> None:
        item = self.highlighted_child
        if not isinstance(item, FileItem) or item.is_header:
            return

        path = item.path
        if path.is_file():
            self._open_with_default_app(path)

    def _open_with_default_app(self, path: Path) -> None:
        target = str(path)

        if sys.platform == "darwin":
            if path.is_file() and path.suffix.lower() == ".zip":
                subprocess.run(["open", "-R", target])
                return
            subprocess.run(["open", target])
        elif sys.platform == "win32":
            subprocess.run(["explorer", target])
        else:
            subprocess.run(["xdg-open", target])

    def _open_terminal_window(self, path: Path) -> None:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Terminal", str(path)])
            return
        if sys.platform == "win32":
            for candidate in ("pwsh", "powershell"):
                if shutil.which(candidate):
                    subprocess.Popen(["cmd", "/c", "start", "", candidate], cwd=path)
                    return
            subprocess.Popen(["cmd", "/c", "start", "", "cmd"], cwd=path)
            return

        candidates = (
            "x-terminal-emulator",
            "gnome-terminal",
            "konsole",
            "xfce4-terminal",
            "xterm",
            "alacritty",
            "kitty",
        )
        for candidate in candidates:
            if shutil.which(candidate):
                subprocess.Popen([candidate], cwd=path)
                return

    def _restore_selection(self) -> None:
        should_focus = self._should_focus_after_render()
        pending_index = self._pending_delete_index
        if pending_index is not None:
            self._pending_delete_index = None
            if len(self.children) <= 1:
                self.index = None
                return
            if pending_index < len(self.children):
                self.index = pending_index
            else:
                self.index = len(self.children) - 1
            if should_focus:
                self.focus()
            return
        current_dir = self._current_listing_path
        history_target: Path | None = None
        if current_dir is not None:
            history_target = self._selection_history.get(current_dir)

        prefer_history = self._listing_changed
        target = self._state_store.state.last_selected_path
        self._listing_changed = False

        def _select_path(path: Path | None) -> bool:
            if path is None:
                return False
            item = self._current_chunk_items.get(path)
            if item is None:
                return False
            try:
                self.index = self.children.index(item)
            except ValueError:
                return False
            if should_focus:
                self.focus()
            return True

        if prefer_history and _select_path(history_target):
            return

        if _select_path(target):
            return

        if _select_path(history_target):
            return

        direction = self._last_chunk_direction
        if direction in {"prev", "next"}:
            for idx, child in enumerate(self.children):
                if isinstance(child, FileItem) and not child.is_header:
                    self.index = idx
                    if should_focus:
                        self.focus()
                    return
        else:
            for idx, child in enumerate(self.children):
                if isinstance(child, FileItem) and not child.is_header:
                    self.index = idx
                    if should_focus:
                        self.focus()
                    return

        self.index = None

    def _should_focus_after_render(self) -> bool:
        if self._suppress_focus_once:
            self._suppress_focus_once = False
            return False
        focused = getattr(self.app, "focused", None)
        if isinstance(focused, Input) and focused.id == "file_tree_filter_input":
            return False
        try:
            filter_widget = self.app.query_one(
                "#file_tree_filter", FileTreeFilterWidget
            )
        except Exception:
            return True
        return filter_widget.display != "block"

    def suppress_focus_once(self) -> None:
        self._suppress_focus_once = True

    def show_loading(self, path: Path) -> None:
        app = self.app
        with app.batch_update():
            self.clear()
            self._current_chunk_items = {}
            indicator = LoadingIndicator()
            indicator.loading = True
            placeholder = ListItem(indicator, classes="item_loading")
            placeholder.can_focus = False
            self.append(placeholder)

    def show_error(self, path: Path, message: str) -> None:
        app = self.app
        with app.batch_update():
            self.clear()
            self._current_chunk_items = {}
            notice = ListItem(
                Label(message, classes="file_tree_error"), classes="item_error"
            )
            notice.can_focus = False
            self.append(notice)

    def show_listing(self, path: Path, entries: Sequence[FileListingEntry]) -> None:
        app = self.app
        with app.batch_update():
            previous_path = self._current_listing_path
            self._state_store.set_current_listing_path(path)
            self._current_listing_path = path
            self._listing_changed = previous_path != path
            self._all_entries = list(entries)
            if previous_path != path:
                self._state_store.set_last_selected_path(None)
                self._clear_selection()
                self._set_filter("")
            else:
                self._prune_selection({entry.path for entry in self._all_entries})
            self._apply_filter()
            self._update_border_title()
            self._chunk_start = 0
            self._last_chunk_direction = None
            self._render_current_chunk()

    def _apply_filter(self) -> None:
        self._filter_error = False
        if not self._filter_query:
            self._filtered_entries = self._all_entries
            return

        if self._filter_query.startswith("/"):
            pattern = self._filter_query[1:]
            if not pattern:
                self._filtered_entries = self._all_entries
                return
            try:
                matcher = re.compile(pattern, re.IGNORECASE)
            except re.error:
                self._filter_error = True
                self._filtered_entries = []
                return
            self._filtered_entries = [
                entry for entry in self._all_entries if matcher.search(entry.path.name)
            ]
            return

        query = self._filter_query.casefold()
        negate = query.startswith("!")
        if negate:
            query = query[1:].strip()
            if not query:
                self._filtered_entries = self._all_entries
                return
            self._filtered_entries = [
                entry for entry in self._all_entries if query not in entry.search_blob
            ]
            return
        self._filtered_entries = [
            entry for entry in self._all_entries if query in entry.search_blob
        ]

    def handle_filter_submit(self, value: str) -> None:
        parsed = self._parse_replace_request(value)
        if parsed is None:
            self._set_filter(_filter_query_for_input(value))
            return

        filter_query, pattern, replacement, is_regex = parsed
        self._set_filter(filter_query)
        self._confirm_replace(pattern, replacement, is_regex)

    def _parse_replace_request(self, value: str) -> tuple[str, str, str, bool] | None:
        parsed = _split_replace_input(value)
        if parsed is None:
            return None

        mode, pattern, replacement = parsed
        pattern = pattern.strip()
        if not pattern:
            return None

        if mode == "regex":
            filter_query = f"/{pattern}"
            return filter_query, pattern, replacement, True

        return pattern, pattern, replacement, False

    def _confirm_replace(self, pattern: str, replacement: str, is_regex: bool) -> None:
        app = cast("Ferp", self.app)
        if is_regex:
            try:
                matcher = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                app.show_error(exc)
                return
        else:
            matcher = re.compile(re.escape(pattern), re.IGNORECASE)
            replacement = _escape_regex_replacement(replacement)

        sources = {entry.path for entry in self._filtered_entries if not entry.is_dir}
        if not sources:
            app.show_error(RuntimeError("No files match the current filter."))
            return

        plan: list[tuple[Path, Path]] = []
        invalid: list[str] = []
        conflicts: list[str] = []
        planned_targets: dict[str, str] = {}

        for entry in self._filtered_entries:
            if entry.is_dir:
                continue
            name = entry.path.name
            stem, _suffix = _split_stem_suffix(name)
            new_name, new_stem, count = _replace_in_stem(
                name, matcher=matcher, replacement=replacement
            )
            if count == 0 or new_stem == stem:
                continue
            if not new_stem:
                invalid.append(f"{name} -> (empty name)")
                continue
            if Path(new_name).name != new_name:
                invalid.append(f"{name} -> {new_name}")
                continue
            if new_name in planned_targets:
                conflicts.append(
                    f"{name} -> {new_name} (already used by {planned_targets[new_name]})"
                )
                continue
            destination = entry.path.with_name(new_name)
            if destination.exists() and destination != entry.path:
                conflicts.append(f"{name} -> {new_name} (already exists)")
                continue
            if destination in sources and destination != entry.path:
                conflicts.append(f"{name} -> {new_name} (conflicts with another file)")
                continue
            planned_targets[new_name] = name
            plan.append((entry.path, destination))

        if not plan:
            app.show_error(RuntimeError("No files would be renamed."))
            return

        if invalid or conflicts:
            details = []
            if invalid:
                details.append("Invalid names:\n" + "\n".join(invalid[:5]))
            if conflicts:
                details.append("Conflicts:\n" + "\n".join(conflicts[:5]))
            message = "Cannot complete replace.\n" + "\n".join(details)
            app.show_error(RuntimeError(message))
            return

        preview_rows = [(src.name, dest.name) for src, dest in plan[:5]]
        more_count = max(len(plan) - len(preview_rows), 0)
        mode = "regex" if is_regex else "text"
        title = f"Rename {len(plan)} file(s) using {mode} replace?"
        body = preview_rows

        def after(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._set_filter("")
            app._stop_file_tree_watch()
            self.show_loading(app.current_path)
            app.notify(
                f"Renaming {len(plan)} file(s)...",
                timeout=app.notify_timeouts.quick,
            )
            app.run_worker(
                lambda rename_plan=plan: self._bulk_rename_worker(rename_plan),
                group=WorkerGroup.BULK_RENAME,
                thread=True,
            )

        app.push_screen(BulkRenameConfirmDialog(title, body, more_count), after)

    def _bulk_rename_worker(self, plan: list[tuple[Path, Path]]) -> dict[str, object]:
        errors: list[str] = []
        app = cast("Ferp", self.app)
        for source, destination in plan:
            try:
                app.fs_controller.rename_path(
                    source,
                    destination,
                    overwrite=False,
                )
            except Exception as exc:  # pragma: no cover - UI path
                errors.append(f"{source.name}: {exc}")
        return {"count": len(plan), "errors": errors}

    def _set_filter(self, value: str, *, from_store: bool = False) -> None:
        query = value.strip()
        if query == self._filter_query:
            return
        self._filter_query = query
        if not from_store:
            self._state_store.set_filter_query(self._filter_query)
        self._apply_filter()
        self._update_border_title()
        self._chunk_start = 0
        self._last_chunk_direction = None
        self._render_current_chunk()

    def handle_filter_preview(self, value: str) -> None:
        self._set_filter(_filter_query_for_input(value))

    def _update_border_title(self) -> None:
        title = "File Navigator"
        if self._filter_query:
            truncated = self._filter_query
            if len(truncated) > self.FILTER_TITLE_MAX:
                truncated = f"{truncated[: self.FILTER_TITLE_MAX - 3]}..."
            if self._filter_error:
                title = f'{title} (filter: "{truncated}" - invalid regex)'
            else:
                title = f'{title} (filter: "{truncated}")'
        if self._is_visual_mode():
            title = f"{title} · [$text-accent]Visual[/]"
        try:
            container = self.app.query_one("#file_list_container")
        except Exception:
            self.border_title = title
        else:
            container.border_title = title

    def _set_border_subtitle(self, subtitle: str) -> None:
        try:
            container = self.app.query_one("#file_list_container")
        except Exception:
            return
        self._subtitle_base = subtitle
        selected_count = len(self._selected_paths)
        staged_count = len(self._visual_clipboard_paths)
        staged_label = ""
        if staged_count:
            staged_mode = self._visual_clipboard_mode or "copy"
            staged_label = f"[$text-accent]Staged: {staged_count} {staged_mode}[/]"
        if selected_count:
            if subtitle:
                subtitle = f"{subtitle} | [$text-accent]Selected: {selected_count}[/]"
            else:
                subtitle = f"[$text-accent]Selected: {selected_count}[/]"
        if staged_label:
            if subtitle:
                subtitle = f"{subtitle} | {staged_label}"
            else:
                subtitle = staged_label
        container.border_subtitle = subtitle

    def _refresh_border_subtitle(self) -> None:
        self._set_border_subtitle(self._subtitle_base)

    def action_filter_entries(self) -> None:
        try:
            filter_widget = self.app.query_one(
                "#file_tree_filter", FileTreeFilterWidget
            )
        except Exception:
            return
        filter_widget.show(self._filter_query)

    def _handle_state_update(self, state: FileTreeState) -> None:
        self._current_listing_path = state.current_listing_path
        self._selection_history = dict(state.selection_history)
        if state.filter_query != self._filter_query:
            self._set_filter(state.filter_query, from_store=True)
            return

    def _is_visual_mode(self) -> bool:
        return bool(getattr(self.app, "visual_mode", False))

    def clear_visual_state(self) -> None:
        self._clear_selection()
        self.clear_visual_clipboard()

    def clear_visual_clipboard(self) -> None:
        self._visual_clipboard_paths = []
        self._visual_clipboard_mode = None
        self._refresh_border_subtitle()

    def _clear_selection(self) -> None:
        if not self._selected_paths and self._selection_anchor is None:
            return
        self._selected_paths = set()
        self._selection_anchor = None
        self._apply_selection_to_items()
        self._refresh_border_subtitle()

    def _apply_selection_to_items(self) -> None:
        for path, item in self._current_chunk_items.items():
            if path in self._selected_paths:
                item.add_class("item_selected")
            else:
                item.remove_class("item_selected")

    def _set_selected_paths(self, paths: set[Path], *, anchor: Path | None) -> None:
        self._selected_paths = paths
        self._selection_anchor = anchor
        self._apply_selection_to_items()
        self._refresh_border_subtitle()

    def _prune_selection(self, valid_paths: set[Path]) -> None:
        if not self._selected_paths and self._selection_anchor is None:
            return
        self._selected_paths = {
            path for path in self._selected_paths if path in valid_paths
        }
        if self._selection_anchor not in valid_paths:
            self._selection_anchor = None
        self._apply_selection_to_items()
        self._refresh_border_subtitle()

    def _selected_or_highlighted(self) -> list[Path]:
        if self._selected_paths:
            return sorted(self._selected_paths, key=lambda path: str(path))
        path = self._selected_path()
        return [path] if path else []

    def _append_notice(self, message: str) -> None:
        notice = ListItem(
            Label(message, classes="file_tree_notice"), classes="item_notice"
        )
        notice.can_focus = False
        self.append(notice)

    def _render_current_chunk(self) -> None:
        path = self._current_listing_path
        if path is None:
            return

        app = self.app
        with app.batch_update():
            self.scroll_to(y=0, animate=False)
            self.clear()
            self._current_chunk_items = {}

            total = len(self._filtered_entries)
            if total == 0:
                self._set_border_subtitle("")
                if self._all_entries:
                    self._append_notice("No items match the current filter.")
                else:
                    self._append_notice("No files in this directory.")
                self.call_after_refresh(self._restore_selection)
                return

            max_start = (
                0 if total == 0 else (total - 1) // self.CHUNK_SIZE * self.CHUNK_SIZE
            )
            start = max(0, min(self._chunk_start, max_start))
            self._chunk_start = start
            end = min(start + self.CHUNK_SIZE, total)
            if total > self.CHUNK_SIZE:
                self._set_border_subtitle(
                    f"Showing {start + 1}-{end} of {total} | Press [ / ] to change chunks"
                )
            else:
                self._set_border_subtitle("")
            for entry in self._filtered_entries[start:end]:
                classes = "item_dir" if entry.is_dir else "item_file"
                if entry.path in self._selected_paths:
                    classes = f"{classes} item_selected"
                item = FileItem(
                    entry.path,
                    metadata=entry,
                    classes=classes,
                )
                self.append(item)
                self._current_chunk_items[entry.path] = item

            self.call_after_refresh(self._restore_selection)

    @on(ListView.Highlighted)
    def emit_highlight(self, event: ListView.Highlighted) -> None:
        item = event.item

        if isinstance(item, FileItem) and not item.is_header:
            self._state_store.set_last_selected_path(item.path)
        else:
            pass

    @on(ListView.Selected)
    def emit_selection(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, ChunkNavigatorItem):
            total = len(self._filtered_entries)
            if total == 0:
                return
            delta = -1 if item.direction == "prev" else 1
            self._schedule_chunk_move(delta)

    def action_activate_item(self) -> None:
        item = self.highlighted_child
        if isinstance(item, FileItem) and not item.is_header:
            self._activate_item(item)
            return
        if isinstance(item, ChunkNavigatorItem):
            self._activate_chunk_item(item)

    def _activate_item(self, item: FileItem) -> None:
        if not item.path.is_dir():
            return
        if self._current_listing_path is not None:
            self._state_store.update_selection_history(
                self._current_listing_path, item.path
            )
        self._state_store.set_last_selected_path(None)
        self.post_message(DirectorySelectRequest(item.path))

    def _activate_chunk_item(self, item: ChunkNavigatorItem) -> None:
        total = len(self._filtered_entries)
        if total == 0:
            return
        if item.direction == "prev":
            self._chunk_start = max(0, self._chunk_start - self.CHUNK_SIZE)
            self._last_chunk_direction = "prev"
        else:
            max_start = (total - 1) // self.CHUNK_SIZE * self.CHUNK_SIZE
            self._chunk_start = min(self._chunk_start + self.CHUNK_SIZE, max_start)
            self._last_chunk_direction = "next"
        self._render_current_chunk()
        self._state_store.set_last_selected_path(None)

    def action_prev_chunk(self) -> None:
        self._schedule_chunk_move(-1)

    def action_next_chunk(self) -> None:
        self._schedule_chunk_move(1)

    def action_first_chunk(self) -> None:
        total = len(self._filtered_entries)
        if total == 0:
            return
        if total <= self.CHUNK_SIZE:
            return
        if self._chunk_start == 0:
            return
        self._chunk_start = 0
        self._last_chunk_direction = "prev"
        self._render_current_chunk()

    def action_last_chunk(self) -> None:
        total = len(self._filtered_entries)
        if total == 0:
            return
        if total <= self.CHUNK_SIZE:
            return
        max_start = (total - 1) // self.CHUNK_SIZE * self.CHUNK_SIZE
        if self._chunk_start == max_start:
            return
        self._chunk_start = max_start
        self._last_chunk_direction = "next"
        self._render_current_chunk()

    def _schedule_chunk_move(self, delta: int) -> None:
        self._pending_chunk_delta += delta
        if self._chunk_timer is not None:
            self._chunk_timer.stop()
            self._chunk_timer = None
        self._chunk_timer = self.set_timer(
            self.CHUNK_DEBOUNCE_S,
            self._apply_pending_chunk_move,
            name="file-tree-chunk-debounce",
        )

    def _apply_pending_chunk_move(self) -> None:
        if self._chunk_timer is not None:
            self._chunk_timer.stop()
            self._chunk_timer = None
        delta = self._pending_chunk_delta
        self._pending_chunk_delta = 0
        if delta == 0:
            return
        total = len(self._filtered_entries)
        if total == 0:
            return
        if total <= self.CHUNK_SIZE:
            return
        max_start = (total - 1) // self.CHUNK_SIZE * self.CHUNK_SIZE
        next_start = self._chunk_start + (delta * self.CHUNK_SIZE)
        next_start = max(0, min(next_start, max_start))
        if next_start == self._chunk_start:
            return
        self._chunk_start = next_start
        self._last_chunk_direction = "next" if delta > 0 else "prev"
        self._render_current_chunk()

    def action_cursor_down(self) -> None:
        super().action_cursor_down()

    def action_cursor_up(self) -> None:
        super().action_cursor_up()

    def action_cursor_down_fast(self) -> None:
        for _ in range(self.FAST_CURSOR_STEP):
            super().action_cursor_down()

    def action_cursor_up_fast(self) -> None:
        for _ in range(self.FAST_CURSOR_STEP):
            super().action_cursor_up()

    def action_cursor_top(self) -> None:
        if self.children:
            self.index = 0
            self.scroll_to(y=0)

    def action_cursor_bottom(self) -> None:
        if self.children:
            self.index = len(self.children) - 1

    def action_toggle_visual_mode(self) -> None:
        app = cast("Ferp", self.app)
        app.action_toggle_visual_mode()

    def _selected_path(self) -> Path | None:
        item = self.highlighted_child
        if isinstance(item, FileItem) and not item.is_header:
            return item.path
        return None

    def _range_paths(self, anchor: Path, target: Path) -> list[Path] | None:
        entries = [entry.path for entry in self._filtered_entries]
        index_map = {path: idx for idx, path in enumerate(entries)}
        if anchor not in index_map or target not in index_map:
            return None
        start = min(index_map[anchor], index_map[target])
        end = max(index_map[anchor], index_map[target])
        return entries[start : end + 1]

    def action_toggle_select(self) -> None:
        if not self._is_visual_mode():
            return
        path = self._selected_path()
        if path is None:
            return
        selected = set(self._selected_paths)
        anchor = self._selection_anchor
        if path in selected:
            selected.remove(path)
            if anchor == path:
                anchor = None
        else:
            selected.add(path)
            anchor = path
        self._set_selected_paths(selected, anchor=anchor)

    def action_select_range(self) -> None:
        if not self._is_visual_mode():
            return
        path = self._selected_path()
        if path is None:
            return
        anchor = self._selection_anchor or path
        range_paths = self._range_paths(anchor, path)
        if range_paths is None:
            self._set_selected_paths({path}, anchor=path)
            return
        selected = set(self._selected_paths)
        selected.update(range_paths)
        self._set_selected_paths(selected, anchor=anchor)

    def action_copy_selection(self) -> None:
        if not self._is_visual_mode():
            return
        paths = self._selected_or_highlighted()
        if not paths:
            return
        self._visual_clipboard_paths = paths
        self._visual_clipboard_mode = "copy"
        self._refresh_border_subtitle()
        # self.app.notify(f"Copied {len(paths)} item(s).", timeout=app.notify_timeouts.quick)

    def action_move_selection(self) -> None:
        if not self._is_visual_mode():
            return
        paths = self._selected_or_highlighted()
        if not paths:
            return
        self._visual_clipboard_paths = paths
        self._visual_clipboard_mode = "move"
        self._refresh_border_subtitle()
        # self.app.notify(f"Move staged for {len(paths)} item(s).", timeout=app.notify_timeouts.quick)

    def action_paste_selection(self) -> None:
        if not self._is_visual_mode():
            return
        if not self._visual_clipboard_paths or not self._visual_clipboard_mode:
            app = cast("Ferp", self.app)
            app.notify(
                "Nothing to paste.",
                timeout=app.notify_timeouts.quick,
            )
            return
        staged_paths = list(self._visual_clipboard_paths)
        staged_mode = self._visual_clipboard_mode
        self.clear_visual_clipboard()
        app = cast(AppWithPath, self.app)
        self.post_message(
            BulkPasteRequest(
                staged_paths,
                app.current_path,
                move=staged_mode == "move",
            )
        )

    def action_toggle_favorite(self) -> None:
        app = cast("Ferp", self.app)
        path = self._selected_path() or app.current_path
        app.toggle_favorite(path)

    def action_open_favorites(self) -> None:
        app = cast("Ferp", self.app)
        app.open_favorites_dialog()

    def action_show_info(self) -> None:
        app = cast("Ferp", self.app)
        path = self._selected_path()
        if path is None:
            return
        app.request_file_info(path)

    def action_select_all(self) -> None:
        if not self._is_visual_mode():
            return
        if not self._filtered_entries:
            return
        paths = {entry.path for entry in self._filtered_entries}
        anchor = self._selected_path()
        if anchor is None and self._filtered_entries:
            anchor = self._filtered_entries[0].path
        self._set_selected_paths(paths, anchor=anchor)

    def action_deselect_all(self) -> None:
        if not self._is_visual_mode():
            return
        self._clear_selection()

    def action_clear_staging(self) -> None:
        if not self._is_visual_mode():
            return
        if not self._visual_clipboard_paths:
            return
        self.clear_visual_clipboard()
        # self.app.notify("Cleared staged items.", timeout=app.notify_timeouts.quick)

    def action_new_file(self) -> None:
        app = cast(AppWithPath, self.app)
        base = app.current_path
        self.post_message(CreatePathRequest(base, is_directory=False))

    def action_new_directory(self) -> None:
        app = cast(AppWithPath, self.app)
        base = app.current_path
        self.post_message(CreatePathRequest(base, is_directory=True))

    def action_delete_entry(self) -> None:
        if self._is_visual_mode() and self._selected_paths:
            targets = sorted(self._selected_paths)
            self._clear_selection()
            self.post_message(BulkDeleteRequest(targets))
            return
        path = self._selected_path()
        if path is None:
            return
        self.post_message(DeletePathRequest(path))

    def action_rename_entry(self) -> None:
        path = self._selected_path()
        if path is None:
            return
        self.post_message(RenamePathRequest(path))

    def action_open_terminal(self) -> None:
        app = cast(AppWithPath, self.app)
        self._open_terminal_window(app.current_path)
