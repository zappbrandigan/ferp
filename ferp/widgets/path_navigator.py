from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click, DescendantBlur, DescendantFocus, Key, Resize
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static

from ferp.core.messages import NavigateRequest
from ferp.core.path_navigation import (
    can_navigate_up,
    is_navigable_directory,
    parent_directory,
)
from ferp.core.state import AppState, AppStateStore
from ferp.services.file_listing import is_entry_visible


class PathNavigator(Vertical):
    """Navigation bar with history controls and editable path input."""

    HISTORY_LIMIT = 200
    SUGGESTION_LIMIT = 20
    SUGGESTION_VERTICAL_OVERLAP = 2

    def __init__(self, *, state_store: AppStateStore, id: str | None = None) -> None:
        super().__init__(id=id)
        self._state_store = state_store
        self._state_subscription = self._handle_state_update
        self._current_path = Path.home()
        self._history: list[Path] = []
        self._history_index = -1
        self._syncing_input = False
        self._user_editing = False
        self._input: Input | None = None
        self._suggestions: OptionList | None = None
        self._suggested_paths: list[Path] = []
        self._typing_session_active = False
        self._edit_start_value = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="path_nav_row"):
            yield Static("←", id="path_nav_back", classes="path_nav_control")
            yield Static("→", id="path_nav_forward", classes="path_nav_control")
            yield Static("↑", id="path_nav_up", classes="path_nav_control")
            with Vertical(id="path_nav_input_wrap"):
                yield Input(
                    placeholder="Enter a directory path",
                    id="path_nav_input",
                )
                suggestions = OptionList(id="path_nav_suggestions")
                suggestions.display = False
                yield suggestions

    def on_mount(self) -> None:
        self._input = self.query_one("#path_nav_input", Input)
        self._suggestions = self.query_one("#path_nav_suggestions", OptionList)
        self._state_store.subscribe(self._state_subscription)

    def on_unmount(self) -> None:
        self._state_store.unsubscribe(self._state_subscription)

    @on(DescendantFocus, "#path_nav_input")
    def _on_input_focused(self) -> None:
        self._user_editing = True
        self._typing_session_active = False
        self._edit_start_value = self._input.value if self._input else ""

    @on(DescendantBlur, "#path_nav_input")
    def _on_input_blurred(self) -> None:
        self.call_after_refresh(self._sync_after_input_blur)

    @on(DescendantBlur, "#path_nav_suggestions")
    def _on_suggestions_blurred(self) -> None:
        self.call_after_refresh(self._sync_after_suggestions_blur)

    @on(Input.Changed, "#path_nav_input")
    def _on_input_changed(self, event: Input.Changed) -> None:
        if self._syncing_input:
            return
        if not self._user_editing or self.app.focused is not self._input:
            return
        if not self._typing_session_active:
            if event.value == self._edit_start_value:
                return
            self._typing_session_active = True
        self._refresh_suggestions(event.value)

    @on(Input.Submitted, "#path_nav_input")
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        if self._suggestions is not None and self.has_class("show_suggestions"):
            highlighted = self._suggestions.highlighted
            if highlighted is not None:
                self._select_suggestion(highlighted)
                return
        target = self._resolve_candidate_path(event.value)
        if target is None:
            self.app.notify("Invalid path.", severity="error")
            return
        if not is_navigable_directory(target):
            self.app.notify(f"Not a directory: {target}", severity="error")
            return
        self.post_message(NavigateRequest(target))

    @on(OptionList.OptionSelected, "#path_nav_suggestions")
    def _on_suggestion_selected(self, event: OptionList.OptionSelected) -> None:
        self._select_suggestion(event.option_index)

    @on(Click, ".path_nav_control")
    def _on_control_click(self, event: Click) -> None:
        if event.control is not None and event.control.has_class("disabled"):
            return
        control_id = event.control.id if event.control else None
        if control_id == "path_nav_back":
            self._navigate_history(-1)
        elif control_id == "path_nav_forward":
            self._navigate_history(1)
        elif control_id == "path_nav_up":
            self._navigate_up()

    def _navigate_up(self) -> None:
        parent = parent_directory(self._current_path)
        if parent is None:
            return
        self.post_message(NavigateRequest(parent))

    def _navigate_history(self, delta: int) -> None:
        if not self._history:
            return
        next_index = self._history_index + delta
        while 0 <= next_index < len(self._history):
            candidate = self._history[next_index]
            if is_navigable_directory(candidate):
                self._history_index = next_index
                self.post_message(NavigateRequest(candidate))
                self._update_controls()
                return
            del self._history[next_index]
            if delta < 0:
                next_index -= 1
        self._history_index = max(0, min(self._history_index, len(self._history) - 1))
        self._update_controls()

    def _handle_state_update(self, state: AppState) -> None:
        if not state.current_path:
            return
        path = Path(state.current_path)
        self._current_path = path
        self._record_history(path)
        if not self._user_editing:
            self._set_input_value(str(path))
            self._clear_suggestions()
        self._update_controls()

    def _record_history(self, path: Path) -> None:
        if self._history and self._history_index >= 0:
            current = self._history[self._history_index]
            if current == path:
                return
        if self._history_index < len(self._history) - 1:
            self._history = self._history[: self._history_index + 1]
        self._history.append(path)
        if len(self._history) > self.HISTORY_LIMIT:
            overflow = len(self._history) - self.HISTORY_LIMIT
            self._history = self._history[overflow:]
        self._history_index = len(self._history) - 1

    def _set_input_value(self, value: str) -> None:
        if not self._input:
            return
        self._syncing_input = True
        self._input.value = value
        self._syncing_input = False

    def _resolve_candidate_path(self, value: str) -> Path | None:
        raw = value.strip()
        if not raw:
            return self._current_path
        try:
            candidate = Path(raw).expanduser()
        except Exception:
            return None
        if not candidate.is_absolute():
            candidate = (self._current_path / candidate).expanduser()
        return candidate.resolve()

    def _refresh_suggestions(self, value: str) -> None:
        if not self._input:
            return
        candidates = self._directory_suggestions(value)
        self._input.suggester = (
            SuggestFromList(
                [str(path) for path in candidates],
                case_sensitive=False,
            )
            if candidates
            else None
        )
        if not self._suggestions:
            return
        if not candidates:
            self.remove_class("show_suggestions")
            self._suggestions.display = False
            self._suggestions.clear_options()
            self._suggested_paths = []
            return
        self._suggested_paths = candidates
        self._suggestions.display = True
        self._suggestions.set_options(str(path) for path in candidates)
        self._suggestions.highlighted = 0 if self._suggestions.option_count else None
        self.add_class("show_suggestions")
        self.call_after_refresh(self._position_suggestions)

    def _clear_suggestions(self) -> None:
        if self._suggestions:
            self._suggestions.display = False
            self._suggestions.clear_options()
        self._suggested_paths = []
        self.remove_class("show_suggestions")

    def _directory_suggestions(self, value: str) -> list[Path]:
        raw = value.strip()
        try:
            typed = Path(raw).expanduser() if raw else self._current_path
        except Exception:
            return []

        if not typed.is_absolute():
            typed = (self._current_path / typed).expanduser()

        has_trailing_sep = raw.endswith(("/", "\\"))
        base_dir = typed if has_trailing_sep else typed.parent
        prefix = "" if has_trailing_sep else typed.name

        if not is_navigable_directory(base_dir):
            return []

        hide_filtered_entries = bool(getattr(self.app, "hide_filtered_entries", True))

        try:
            entries = [
                entry
                for entry in base_dir.iterdir()
                if entry.is_dir()
                and is_entry_visible(
                    entry,
                    base_dir,
                    hide_filtered_entries=hide_filtered_entries,
                )
            ]
        except OSError:
            return []

        if prefix:
            lowered = prefix.lower()
            entries = [
                entry for entry in entries if entry.name.lower().startswith(lowered)
            ]

        entries.sort(key=lambda path: path.name.lower())
        return entries[: self.SUGGESTION_LIMIT]

    def on_resize(self, _event: Resize) -> None:
        if self.has_class("show_suggestions"):
            self._position_suggestions()

    def _position_suggestions(self) -> None:
        if not self._input or not self._suggestions:
            return
        input_region = self._input.region
        parent = self._suggestions.parent
        if not isinstance(parent, Widget):
            x = input_region.x
            y = input_region.y + input_region.height
        else:
            parent_region = parent.region
            x = input_region.x - parent_region.x
            y = (
                input_region.y
                - parent_region.y
                + input_region.height
                - self.SUGGESTION_VERTICAL_OVERLAP
            )

        self._suggestions.styles.offset = (max(0, x), max(0, y))
        self._suggestions.styles.width = max(20, self._input.size.width)
        self._suggestions.styles.height = min(
            self.SUGGESTION_LIMIT + 2, max(3, self._suggestions.option_count + 2)
        )
        self._suggestions.refresh(layout=True)

    def refresh_visible_suggestions(self) -> None:
        if not self._input:
            return
        if not self.has_class("show_suggestions"):
            return
        self._refresh_suggestions(self._input.value)

    def on_key(self, event: Key) -> None:
        focused = self.app.focused
        if focused is self._input:
            if event.is_printable or event.key in {
                "backspace",
                "delete",
                "ctrl+h",
                "ctrl+w",
                "ctrl+u",
                "ctrl+k",
            }:
                self._typing_session_active = True

        if (
            focused is self._input
            and event.key == "down"
            and self.has_class("show_suggestions")
            and self._suggestions is not None
        ):
            event.stop()
            event.prevent_default()
            if (
                self._suggestions.highlighted is None
                and self._suggestions.option_count > 0
            ):
                self._suggestions.highlighted = 0
            self._suggestions.focus()
            return

        if focused is self._suggestions and event.key == "escape" and self._input:
            event.stop()
            event.prevent_default()
            self._input.focus()
            self._clear_suggestions()

    def _sync_after_input_blur(self) -> None:
        focused = self.app.focused
        if self._suggestions is not None and focused is self._suggestions:
            self._user_editing = True
            return
        self._user_editing = False
        self._typing_session_active = False
        self._edit_start_value = ""
        self._set_input_value(str(self._current_path))
        self._clear_suggestions()

    def _sync_after_suggestions_blur(self) -> None:
        focused = self.app.focused
        if focused is self._input:
            return
        if self._suggestions is not None and focused is self._suggestions:
            return
        self._user_editing = False
        self._typing_session_active = False
        self._edit_start_value = ""
        self._clear_suggestions()

    def _select_suggestion(self, index: int) -> None:
        if index < 0 or index >= len(self._suggested_paths):
            return
        selected = self._suggested_paths[index]
        self._set_input_value(str(selected))
        self._clear_suggestions()
        if self._input is not None:
            self._input.focus()
        self.post_message(NavigateRequest(selected))

    def _update_controls(self) -> None:
        back = self.query_one("#path_nav_back", Static)
        forward = self.query_one("#path_nav_forward", Static)
        up = self.query_one("#path_nav_up", Static)

        if self._history_index > 0:
            back.remove_class("disabled")
        else:
            back.add_class("disabled")

        if 0 <= self._history_index < len(self._history) - 1:
            forward.remove_class("disabled")
        else:
            forward.add_class("disabled")

        if can_navigate_up(self._current_path):
            up.remove_class("disabled")
        else:
            up.add_class("disabled")
