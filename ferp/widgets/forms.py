from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label


@dataclass(frozen=True)
class BooleanField:
    id: str
    label: str
    value: bool = False


class PromptDialog(ModalScreen[dict[str, str | bool] | None]):
    def __init__(
        self,
        message: str,
        id: str,
        *,
        default: str | None = None,
        boolean_fields: Iterable[BooleanField] | None = None,
        show_text_input: bool = True,
    ) -> None:
        super().__init__(id=id)
        self._message = message
        self._default = default or ""
        self._bool_fields = list(boolean_fields or [])
        self._show_text_input = show_text_input

    def compose(self) -> ComposeResult:
        contents: list[Label | Input | Horizontal] = [
            Label(self._message, id="dialog_message")
        ]
        if self._show_text_input:
            contents.append(Input(value=self._default, id="prompt_input"))
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
                Button("OK", id="ok", variant="primary"),
                Button("Cancel", id="cancel"),
                classes="dialog_buttons",
            )
        )
        yield Vertical(*contents, id="dialog_container")

    def on_mount(self) -> None:
        if self._show_text_input:
            self.query_one(Input).focus()
            return
        if self._bool_fields:
            self.query_one(Checkbox).focus()
            return
        self.query_one("#ok", Button).focus()

    def on_screen_resume(self) -> None:
        if getattr(self, "_dismiss_on_resume", False):
            self.dismiss(None)

    def _collect_state(self) -> dict[str, str | bool]:
        state: dict[str, str | bool] = {}
        if self._show_text_input:
            state["value"] = self.query_one(Input).value.strip()
        else:
            state["value"] = ""
        for field in self._bool_fields:
            checkbox = self.query_one(f"#{field.id}", Checkbox)
            state[field.id] = bool(checkbox.value)
        return state

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self._collect_state())
        else:
            self.dismiss(None)
