from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, cast
import sys
import subprocess

from textual.containers import Horizontal
from textual.widgets import ListView, Label, ListItem, LoadingIndicator
from textual.binding import Binding
from textual import on

from ferp.core.messages import (
    CreatePathRequest,
    DeletePathRequest,
    DirectorySelectRequest,
    HighlightRequest,
    NavigateRequest,
    RenamePathRequest,
    ShowTerminalRequest,
)
from ferp.core.protocols import AppWithPath


@dataclass(frozen=True)
class FileListingEntry:
    path: Path
    display_name: str
    char_count: int
    type_label: str
    modified_label: str
    created_label: str
    is_dir: bool

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
                Label("Chars", classes="file_tree_cell file_tree_chars file_tree_header"),
                Label("Type", classes="file_tree_cell file_tree_type file_tree_header"),
                Label("Modified", classes="file_tree_cell file_tree_modified file_tree_header"),
                Label("Created", classes="file_tree_cell file_tree_created file_tree_header"),
                classes="file_tree_row",
            )
        else:
            if metadata is None:
                raise ValueError("metadata required for non-header FileItems")
            row = Horizontal(
                Label(metadata.display_name, classes="file_tree_cell file_tree_name"),
                Label(str(metadata.char_count), classes="file_tree_cell file_tree_chars"),
                Label(metadata.type_label, classes="file_tree_cell file_tree_type"),
                Label(metadata.modified_label, classes="file_tree_cell file_tree_modified"),
                Label(metadata.created_label, classes="file_tree_cell file_tree_created"),
                classes=f"file_tree_row {'file_tree_type_dir' if metadata.is_dir else 'file_tree_type_file'}",
            )

        super().__init__(row, classes=classes, **kwargs)
        self.disabled = is_header


class ChunkNavigatorItem(ListItem):
    """Interactive row to navigate between file list chunks."""

    def __init__(self, label: str, *, direction: str) -> None:
        super().__init__(Label(label, classes="file_tree_notice"), classes="item_notice")
        self.direction = direction


class FileTree(ListView):
    CHUNK_SIZE = 250
    BINDINGS = [
        Binding("enter", "select_cursor", "Select directory", show=False),
        Binding("g", "cursor_top", "To top", show=False),
        Binding("G", "cursor_bottom", "To bottom", key_display="G", show=False),
        Binding("k", "cursor_up", "Cursor up", show=False),
        Binding("K", "cursor_up_fast", "Cursor up (fast)", key_display="K", show=False),
        Binding("j", "cursor_down", "Cursor down", show=False),
        Binding("J", "cursor_down_fast", "Cursor down (fast)", key_display="J", show=False),
        Binding("ctrl+t", "open_terminal", "Terminal", show=False),
        Binding("u", "go_parent", "Go to parent", show=True, tooltip="Go to parent directory"),
        Binding("h", "go_home", "Go to start", show=True, tooltip="Go to default startup path"),
        Binding("r", "rename_entry", "Rename", show=True, tooltip="Rename selected file or directory"),
        Binding("n", "new_file", "New File", show=True, tooltip="Create new file in current directory"),
        Binding("N", "new_directory", "New Directory", key_display="N", show=True, tooltip="Create new directory in current directory"),
        Binding("d,delete,backspace", "delete_entry", "Delete", show=True, tooltip="Delete selected file or directory"),
        Binding("ctrl+f", "open_finder", "Open in FS", show=True, tooltip="Open current directory in system file explorer"),
        Binding("ctrl+o", "open_selected_file", "Open file", show=True, tooltip="Open selected file with default application"),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._all_entries: list[FileListingEntry] = []
        self._chunk_start = 0
        self._current_listing_path: Path | None = None
        self._last_selected_path: Path | None = None
        self._selection_history: dict[Path, Path] = {}
        self._last_chunk_direction: str | None = None

    def on_mount(self) -> None:
        self.border_title = "File Navigator"

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

    def _restore_selection(self) -> None:
        target = self._last_selected_path
        if target:
            for idx, child in enumerate(self.children):
                if isinstance(child, FileItem) and not child.is_header and child.path == target:
                    self.index = idx
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
                    self.focus()
                    return

        if target:
            # fall back to target again if it was removed from history, but still present
            for idx, child in enumerate(self.children):
                if isinstance(child, FileItem) and not child.is_header and child.path == target:
                    self.index = idx
                    self.focus()
                    return

        direction = self._last_chunk_direction
        if direction == "prev":
            self.index=1
            self.focus()
            return
        elif direction == "next":
            self.index = len(self.children) - 1
            self.focus()
            return
        else:
            for idx, child in enumerate(self.children):
                if isinstance(child, FileItem) and not child.is_header:
                    self.index = idx
                    self.focus()
                    return

        self.index = None

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
        notice = ListItem(Label(message, classes="file_tree_error"), classes="item_error")
        notice.can_focus = False
        self.append(notice)

    def show_listing(self, path: Path, entries: Sequence[FileListingEntry]) -> None:
        self._current_listing_path = path
        self._all_entries = sorted(
            entries,
            key=lambda entry: (
                not entry.is_dir,
                entry.type_label.casefold(),
                entry.display_name.casefold(),
            ),
        )
        self._chunk_start = 0
        self._render_current_chunk()

    def _append_header(self, path: Path) -> None:
        parent = path.parent
        header_target = parent if parent != path else path
        self.append(FileItem(header_target, is_header=True))

    def _render_current_chunk(self) -> None:
        path = self._current_listing_path
        if path is None:
            return

        self.clear()
        self._append_header(path)

        total = len(self._all_entries)
        if total == 0:
            self.call_after_refresh(self._restore_selection)
            return

        max_start = max(0, total - self.CHUNK_SIZE)
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

        for entry in self._all_entries[start:end]:
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
            total = len(self._all_entries)
            if total == 0:
                return
            if item.direction == "prev":
                self._chunk_start = max(0, self._chunk_start - self.CHUNK_SIZE)
                self._last_chunk_direction = "prev"
            else:
                self._chunk_start = min(self._chunk_start + self.CHUNK_SIZE, max(0, total - self.CHUNK_SIZE))
                self._last_chunk_direction = "next"
            self._render_current_chunk()
            self._last_selected_path = None

    def action_cursor_down(self) -> None:
        super().action_cursor_down()
        if self.index == 0 and len(self.children) > 1:
            self.index = 1

    def action_cursor_up(self) -> None:
        super().action_cursor_up()
        if self.index == 0 and len(self.children) > 1:
            self.index = 1

    def action_cursor_down_fast(self) -> None:
        for _ in range(self._visible_item_count()):  
            super().action_cursor_down()
        if self.index == 0 and len(self.children) > 1:
            self.index = 1

    def action_cursor_up_fast(self) -> None:
        for _ in range(self._visible_item_count()):  
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
        app = cast(AppWithPath, self.app)
        return app.current_path

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
        self.post_message(ShowTerminalRequest())
