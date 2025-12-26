from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
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
        *,
        default: str | None = None,
        boolean_fields: Iterable[BooleanField] | None = None,
    ) -> None:
        super().__init__()
        self._message = message
        self._default = default or ""
        self._bool_fields = list(boolean_fields or [])

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._message, id="dialog_message"),
            Input(value=self._default, id="prompt_input"),
            Horizontal(
                *(
                    Checkbox(label=field.label, value=field.value, id=field.id)
                    for field in self._bool_fields
                ),
                id="prompt_flags",
                classes="hidden" if not self._bool_fields else "",
            ),
            Horizontal(
                Button("OK", id="ok", variant="primary"),
                Button("Cancel", id="cancel"),
                classes="dialog_buttons",
            ),
            id="dialog_container",
        )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def _collect_state(self) -> dict[str, str | bool]:
        state: dict[str, str | bool] = {}
        state["value"] = self.query_one(Input).value
        for field in self._bool_fields:
            checkbox = self.query_one(f"#{field.id}", Checkbox)
            state[field.id] = bool(checkbox.value)
        return state

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self._collect_state())
        else:
            self.dismiss(None)
