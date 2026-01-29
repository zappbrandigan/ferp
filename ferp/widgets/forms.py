from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Checkbox, Input, Label, SelectionList


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


def _selection_list_values(selection_list: SelectionList) -> list[str]:
    selected = selection_list.selected
    if isinstance(selected, list):
        return [str(item) for item in selected]
    return []


class PromptDialog(ModalScreen[dict[str, str | bool | list[str]] | None]):
    def __init__(
        self,
        message: str,
        id: str,
        *,
        default: str | None = None,
        boolean_fields: Iterable[BooleanField] | None = None,
        selection_fields: Iterable[SelectionField] | None = None,
        show_text_input: bool = True,
    ) -> None:
        super().__init__(id=id)
        self._message = message
        self._default = default or ""
        self._bool_fields = list(boolean_fields or [])
        self._selection_fields = list(selection_fields or [])
        self._show_text_input = show_text_input

    def compose(self) -> ComposeResult:
        contents: list[Widget] = [Label(self._message, id="dialog_message")]
        if self._show_text_input:
            contents.append(Input(value=self._default, id="prompt_input"))
        for field in self._selection_fields:
            contents.append(
                Label(
                    field.label,
                    id=f"{field.id}_label",
                    classes="selection_list_subtitle",
                )
            )
            contents.append(
                SelectionList(
                    *[(option, option) for option in field.options],
                    id=field.id,
                    classes="prompt_selection_list",
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
            state["value"] = self.query_one(Input).value.strip()
        else:
            state["value"] = ""
        for field in self._bool_fields:
            checkbox = self.query_one(f"#{field.id}", Checkbox)
            state[field.id] = bool(checkbox.value)
        for field in self._selection_fields:
            selection_list = self.query_one(f"#{field.id}", SelectionList)
            state[field.id] = _selection_list_values(selection_list)
        return state

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self._collect_state())
        else:
            self.dismiss(None)
