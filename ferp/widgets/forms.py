from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    Select,
    SelectionList,
    TextArea,
)


@dataclass(frozen=True)
class BooleanField:
    id: str
    label: str
    value: bool = False


@dataclass(frozen=True)
class SelectionField:
    id: str
    label: str
    options: list[str]
    values: list[str] | None = None


@dataclass(frozen=True)
class SelectField:
    id: str
    label: str
    options: list[str]
    value: str | None = None


def _selection_list_values(selection_list: SelectionList) -> list[str]:
    selected = selection_list.selected
    if isinstance(selected, list):
        return [str(item) for item in selected]
    return []


class PromptSelectionList(SelectionList):
    FAST_CURSOR_STEP = 5
    BINDINGS = [
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
    ]

    def _option_count(self) -> int:
        count = getattr(self, "option_count", None)
        if isinstance(count, int):
            return count
        options = getattr(self, "options", None)
        if options is not None:
            try:
                return len(options)
            except TypeError:
                pass
        options = getattr(self, "_options", None)
        if options is not None:
            try:
                return len(options)
            except TypeError:
                pass
        return len(self.children)

    def _set_index(self, index: int) -> None:
        if hasattr(self, "index"):
            try:
                self.index = index
                return
            except Exception:
                pass
        if hasattr(self, "highlighted"):
            try:
                self.highlighted = index
                return
            except Exception:
                pass

    def action_cursor_down_fast(self) -> None:
        for _ in range(self.FAST_CURSOR_STEP):
            super().action_cursor_down()

    def action_cursor_up_fast(self) -> None:
        for _ in range(self.FAST_CURSOR_STEP):
            super().action_cursor_up()

    def action_cursor_top(self) -> None:
        if self._option_count() > 0:
            self._set_index(0)
            if hasattr(self, "scroll_to"):
                self.scroll_to(y=0)

    def action_cursor_bottom(self) -> None:
        count = self._option_count()
        if count > 0:
            self._set_index(count - 1)


class PromptDialog(ModalScreen[dict[str, str | bool | list[str]] | None]):
    def __init__(
        self,
        message: str,
        id: str,
        *,
        default: str | None = None,
        suggestions: Iterable[str] | None = None,
        boolean_fields: Iterable[BooleanField] | None = None,
        selection_fields: Iterable[SelectionField] | None = None,
        select_fields: Iterable[SelectField] | None = None,
        show_text_input: bool = True,
        text_input_style: str = "single_line",
    ) -> None:
        super().__init__(id=id)
        self._message = message
        self._default = default or ""
        self._suggestions = list(suggestions or [])
        self._bool_fields = list(boolean_fields or [])
        self._selection_fields = list(selection_fields or [])
        self._select_fields = list(select_fields or [])
        self._show_text_input = show_text_input
        self._text_input_style = text_input_style

    def compose(self) -> ComposeResult:
        contents: list[Widget] = [Label(self._message, id="dialog_message")]
        if self._show_text_input:
            if self._text_input_style == "multiline":
                text_area = TextArea(
                    self._default,
                    id="prompt_textarea",
                )
                if hasattr(text_area, "placeholder"):
                    text_area.placeholder = (
                        "Enter one query per line. Use /regex/ for regex."
                    )
                contents.append(text_area)
            else:
                suggester = None
                if self._suggestions:
                    suggester = SuggestFromList(
                        self._suggestions,
                        case_sensitive=False,
                    )
                contents.append(
                    Input(value=self._default, id="prompt_input", suggester=suggester)
                )
        for field in self._selection_fields:
            contents.append(
                Label(
                    field.label,
                    id=f"{field.id}_label",
                    classes="selection_list_subtitle",
                )
            )
            contents.append(
                PromptSelectionList(
                    *[(option, option) for option in field.options],
                    id=field.id,
                    classes="prompt_selection_list",
                )
            )
        for field in self._select_fields:
            contents.append(
                Label(
                    field.label,
                    id=f"{field.id}_label",
                    classes="selection_list_subtitle",
                )
            )
            default = field.value or (field.options[0] if field.options else "")
            contents.append(
                Select(
                    [(option, option) for option in field.options],
                    value=default,
                    allow_blank=False,
                    id=field.id,
                    classes="prompt_select",
                )
            )
        contents.append(
            Horizontal(
                *(
                    Checkbox(label=field.label, value=field.value, id=field.id)
                    for field in self._bool_fields
                ),
                id="prompt_flags",
                classes="hidden" if not self._bool_fields else "",
            )
        )
        contents.append(
            Horizontal(
                Button("OK", id="ok", variant="primary", flat=True),
                Button("Cancel", id="cancel", flat=True),
                classes="dialog_buttons",
            )
        )
        yield Vertical(*contents, id="dialog_container")

    def on_mount(self) -> None:
        if self._show_text_input:
            if self._text_input_style == "multiline":
                self.query_one(TextArea).focus()
            else:
                self.query_one(Input).focus()
        for field in self._selection_fields:
            selection_list = self.query_one(f"#{field.id}", SelectionList)
            if field.values:
                for value in field.values:
                    selector = getattr(selection_list, "select", None)
                    if callable(selector):
                        try:
                            selector(value)
                        except Exception:
                            pass
        if not self._show_text_input:
            if self._selection_fields:
                self.query_one(SelectionList).focus()
                return
            if self._select_fields:
                self.query_one(Select).focus()
                return
            if self._bool_fields:
                self.query_one(Checkbox).focus()
                return
            self.query_one("#ok", Button).focus()

    def on_screen_resume(self) -> None:
        if getattr(self, "_dismiss_on_resume", False):
            self.dismiss(None)

    def _collect_state(self) -> dict[str, str | bool | list[str]]:
        state: dict[str, str | bool | list[str]] = {}
        if self._show_text_input:
            if self._text_input_style == "multiline":
                widget = self.query_one(TextArea)
                state["value"] = str(
                    getattr(widget, "text", getattr(widget, "value", ""))
                ).strip()
            else:
                state["value"] = self.query_one(Input).value.strip()
        else:
            state["value"] = ""
        for field in self._bool_fields:
            checkbox = self.query_one(f"#{field.id}", Checkbox)
            state[field.id] = bool(checkbox.value)
        for field in self._selection_fields:
            selection_list = self.query_one(f"#{field.id}", SelectionList)
            state[field.id] = _selection_list_values(selection_list)
        for field in self._select_fields:
            select = self.query_one(f"#{field.id}", Select)
            value = select.value
            state[field.id] = str(value) if value is not None else ""
        return state

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self._collect_state())
        else:
            self.dismiss(None)
