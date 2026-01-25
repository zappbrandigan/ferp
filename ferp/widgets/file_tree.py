import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Pattern, Sequence, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView, LoadingIndicator

from ferp.core.messages import (
    CreatePathRequest,
    DeletePathRequest,
    DirectorySelectRequest,
    HighlightRequest,
    NavigateRequest,
    RenamePathRequest,
)
from ferp.core.protocols import AppWithPath
from ferp.widgets.dialogs import BulkRenameConfirmDialog

if TYPE_CHECKING:
    from ferp.core.app import Ferp


@dataclass(frozen=True)
class FileListingEntry:
    path: Path
    display_name: str
    char_count: int
    type_label: str
    modified_ts: float
    created_ts: float
    is_dir: bool
    search_blob: str


@lru_cache(maxsize=2048)
def _format_timestamp(timestamp: float) -> str:
    return datetime.strftime(datetime.fromtimestamp(timestamp), "%x %I:%S %p")


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


class FileItem(ListItem):
    def __init__(
        self,
        path: Path,
        *,
        metadata: FileListingEntry | None = None,
        is_header: bool = False,
        classes: str | None = None,
        **kwargs,
    ) -> None:
        self.path = path
        self.is_header = is_header
        self.metadata = metadata

        if is_header:
            row = Horizontal(
                Label("Name", classes="file_tree_cell file_tree_name file_tree_header"),
                Label(
                    "Chars", classes="file_tree_cell file_tree_chars file_tree_header"
                ),
                Label("Type", classes="file_tree_cell file_tree_type file_tree_header"),
                Label(
                    "Modified",
                    classes="file_tree_cell file_tree_modified file_tree_header",
                ),
                Label(
                    "Created",
                    classes="file_tree_cell file_tree_created file_tree_header",
                ),
                classes="file_tree_row",
            )
        else:
            if metadata is None:
                raise ValueError("metadata required for non-header FileItems")
            row = Horizontal(
                Label(metadata.display_name, classes="file_tree_cell file_tree_name"),
                Label(
                    str(metadata.char_count), classes="file_tree_cell file_tree_chars"
                ),
                Label(metadata.type_label, classes="file_tree_cell file_tree_type"),
                Label(
                    _format_timestamp(metadata.modified_ts),
                    classes="file_tree_cell file_tree_modified",
                ),
                Label(
                    _format_timestamp(metadata.created_ts),
                    classes="file_tree_cell file_tree_created",
                ),
                classes=f"file_tree_row {'file_tree_type_dir' if metadata.is_dir else 'file_tree_type_file'}",
            )

        super().__init__(row, classes=classes, **kwargs)
        self.disabled = is_header


class ChunkNavigatorItem(ListItem):
    """Interactive row to navigate between file list chunks."""

    def __init__(self, label: str, *, direction: str) -> None:
        super().__init__(
            Label(label, classes="file_tree_notice"), classes="item_notice"
        )
        self.direction = direction


class FileTreeFilterWidget(Widget):
    """Hidden input bar for filtering file tree entries."""

    DEBOUNCE_DELAY = 0.4
    BINDINGS = [
        Binding("escape", "hide", "Hide filter", show=True),
    ]

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
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
        file_tree = self.app.query_one("#file_list", FileTree)
        file_tree.handle_filter_preview(self._pending_value)


class FileTree(ListView):
    CHUNK_SIZE = 100
    FILTER_TITLE_MAX = 24
    BINDINGS = [
        Binding("enter", "select_cursor", "Select directory", show=False),
        Binding("g", "cursor_top", "To top", show=False),
        Binding("G", "cursor_bottom", "To bottom", key_display="G", show=False),
        Binding("k", "cursor_up", "Cursor up", show=False),
        Binding(
            "K", "cursor_up_fast", "Cursor up (half-page)", key_display="K", show=False
        ),
        Binding("j", "cursor_down", "Cursor down", show=False),
        Binding(
            "J",
            "cursor_down_fast",
            "Cursor down (half-page)",
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
            "r",
            "rename_entry",
            "Rename",
            show=False,
            tooltip="Rename selected file or directory",
        ),
        Binding(
            "n",
            "new_file",
            "New File",
            show=False,
            tooltip="Create new file in current directory",
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
        Binding("/", "filter_entries", "Filter", show=True, tooltip="Filter entries"),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._all_entries: list[FileListingEntry] = []
        self._filtered_entries: list[FileListingEntry] = []
        self._filter_query = ""
        self._filter_error = False
        self._chunk_start = 0
        self._current_listing_path: Path | None = None
        self._last_selected_path: Path | None = None
        self._selection_history: dict[Path, Path] = {}
        self._last_chunk_direction: str | None = None
        self._pending_delete_index: int | None = None

    def set_pending_delete_index(self, index: int | None) -> None:
        self._pending_delete_index = index

    def on_mount(self) -> None:
        self._update_border_title()

    def action_go_parent(self) -> None:
        app = cast(AppWithPath, self.app)
        self.post_message(NavigateRequest(app.current_path.parent))

    def action_go_home(self) -> None:
        self._selection_history.clear()
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
        target = self._last_selected_path
        if target:
            for idx, child in enumerate(self.children):
                if (
                    isinstance(child, FileItem)
                    and not child.is_header
                    and child.path == target
                ):
                    self.index = idx
                    if should_focus:
                        self.focus()
                    return

        current_dir = self._current_listing_path
        history_target: Path | None = None
        if current_dir is not None:
            history_target = self._selection_history.get(current_dir)

        if history_target is not None:
            for idx, child in enumerate(self.children):
                if isinstance(child, FileItem) and child.path == history_target:
                    self.index = idx
                    if should_focus:
                        self.focus()
                    return

        if target:
            # fall back to target again if it was removed from history, but still present
            for idx, child in enumerate(self.children):
                if (
                    isinstance(child, FileItem)
                    and not child.is_header
                    and child.path == target
                ):
                    self.index = idx
                    if should_focus:
                        self.focus()
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

    def show_loading(self, path: Path) -> None:
        self.clear()
        self._append_header(path)
        indicator = LoadingIndicator()
        indicator.loading = True
        placeholder = ListItem(indicator, classes="item_loading")
        placeholder.can_focus = False
        self.append(placeholder)

    def show_error(self, path: Path, message: str) -> None:
        self.clear()
        self._append_header(path)
        notice = ListItem(
            Label(message, classes="file_tree_error"), classes="item_error"
        )
        notice.can_focus = False
        self.append(notice)
        self.post_message(HighlightRequest(None))

    def show_listing(self, path: Path, entries: Sequence[FileListingEntry]) -> None:
        previous_path = self._current_listing_path
        self._current_listing_path = path
        self._all_entries = list(entries)
        if previous_path != path:
            self._filter_query = ""
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
        replacement = replacement.strip()

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

        # Regex replacements must use Python's \g<name> or \g<number> syntax.

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

        preview = [f"{src.name} -> {dest.name}" for src, dest in plan[:5]]
        if len(plan) > 5:
            preview.append(f"... and {len(plan) - 5} more.")
        mode = "regex" if is_regex else "text"
        title = f"Rename {len(plan)} file(s) using {mode} replace?"
        body = "\n".join(preview)

        def after(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._set_filter("")
            app._stop_file_tree_watch()
            self.show_loading(app.current_path)
            app.notify(f"Renaming {len(plan)} file(s)...", timeout=2)
            app.run_worker(
                lambda rename_plan=plan: self._bulk_rename_worker(rename_plan),
                group="bulk_rename",
                thread=True,
            )

        app.push_screen(BulkRenameConfirmDialog(title, body), after)

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

    def _set_filter(self, value: str) -> None:
        query = value.strip()
        if query == self._filter_query:
            return
        self._filter_query = query
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
        self.border_title = title

    def action_filter_entries(self) -> None:
        try:
            filter_widget = self.app.query_one(
                "#file_tree_filter", FileTreeFilterWidget
            )
        except Exception:
            return
        filter_widget.show(self._filter_query)

    def _append_header(self, path: Path) -> None:
        parent = path.parent
        header_target = parent if parent != path else path
        self.append(FileItem(header_target, is_header=True))

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

        self.clear()
        self._append_header(path)

        total = len(self._filtered_entries)
        if total == 0:
            if self._all_entries:
                self._append_notice("No items match the current filter.")
            else:
                self._append_notice("No files in this directory.")
            self.post_message(HighlightRequest(None))
            self.call_after_refresh(self._restore_selection)
            return

        max_start = max(0, total - 1)
        start = max(0, min(self._chunk_start, max_start))
        self._chunk_start = start
        end = min(start + self.CHUNK_SIZE, total)
        if start > 0:
            prev_start = max(0, start - self.CHUNK_SIZE)
            prev_end = start
            prev_label = (
                f"Show previous {self.CHUNK_SIZE} (items {prev_start + 1}-{prev_end})"
            )
            self.append(ChunkNavigatorItem(prev_label, direction="prev"))

        for entry in self._filtered_entries[start:end]:
            classes = "item_dir" if entry.is_dir else "item_file"
            self.append(FileItem(entry.path, metadata=entry, classes=classes))

        if end < total:
            next_end = min(total, end + self.CHUNK_SIZE)
            next_label = (
                f"Showing items {start + 1}-{end} of {total}. "
                f"Press Enter to load {end + 1}-{next_end}"
            )
            self.append(ChunkNavigatorItem(next_label, direction="next"))

        self.call_after_refresh(self._restore_selection)

    @on(ListView.Highlighted)
    def emit_highlight(self, event: ListView.Highlighted) -> None:
        item = event.item

        if isinstance(item, FileItem) and not item.is_header:
            self._last_selected_path = item.path
            self.post_message(HighlightRequest(item.path))
        else:
            self.post_message(HighlightRequest(None))

    @on(ListView.Selected)
    def emit_selection(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, FileItem) and not item.is_header and item.path.is_dir():
            if self._current_listing_path is not None:
                self._selection_history[self._current_listing_path] = item.path
            self.post_message(DirectorySelectRequest(item.path))
        elif isinstance(item, ChunkNavigatorItem):
            total = len(self._filtered_entries)
            if total == 0:
                return
            if item.direction == "prev":
                self._chunk_start = max(0, self._chunk_start - self.CHUNK_SIZE)
                self._last_chunk_direction = "prev"
            else:
                self._chunk_start = min(
                    self._chunk_start + self.CHUNK_SIZE,
                    max(0, total - 1),
                )
                self._last_chunk_direction = "next"
            self._render_current_chunk()
            self._last_selected_path = None

    def _move_chunk(self, direction: str) -> None:
        total = len(self._filtered_entries)
        if total == 0:
            return

        if direction == "prev":
            next_start = max(0, self._chunk_start - self.CHUNK_SIZE)
        else:
            next_start = min(self._chunk_start + self.CHUNK_SIZE, max(0, total - 1))

        if next_start == self._chunk_start:
            return

        self._chunk_start = next_start
        self._last_chunk_direction = direction
        self._last_selected_path = None
        self._render_current_chunk()

    def action_prev_chunk(self) -> None:
        self._move_chunk("prev")

    def action_next_chunk(self) -> None:
        self._move_chunk("next")

    def action_cursor_down(self) -> None:
        super().action_cursor_down()
        if self.index == 0 and len(self.children) > 1:
            self.index = 1

    def action_cursor_up(self) -> None:
        super().action_cursor_up()
        if self.index == 0 and len(self.children) > 1:
            self.index = 1

    def action_cursor_down_fast(self) -> None:
        step = max(1, self._visible_item_count() // 2)
        for _ in range(step):
            super().action_cursor_down()
        if self.index == 0 and len(self.children) > 1:
            self.index = 1

    def action_cursor_up_fast(self) -> None:
        step = max(1, self._visible_item_count() // 2)
        for _ in range(step):
            super().action_cursor_up()
        if self.index == 0 and len(self.children) > 1:
            self.index = 1

    def action_cursor_top(self) -> None:
        if len(self.children) > 1:
            self.index = 1
            self.scroll_to(y=0)

    def action_cursor_bottom(self) -> None:
        if len(self.children) > 1:
            self.index = len(self.children) - 1

    def _visible_item_count(self) -> int:
        if not self.children:
            return 0

        first = self.children[0]
        row_height = first.size.height

        if row_height <= 0:
            return 0

        return (self.size.height // row_height) - 1

    def _selected_path(self) -> Path | None:
        item = self.highlighted_child
        if isinstance(item, FileItem) and not item.is_header:
            return item.path
        return None

    def action_new_file(self) -> None:
        app = cast(AppWithPath, self.app)
        base = app.current_path
        self.post_message(CreatePathRequest(base, is_directory=False))

    def action_new_directory(self) -> None:
        app = cast(AppWithPath, self.app)
        base = app.current_path
        self.post_message(CreatePathRequest(base, is_directory=True))

    def action_delete_entry(self) -> None:
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
