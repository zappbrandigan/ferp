from textual.screen import ModalScreen
from textual.widgets import Button, Label, Input
from textual.containers import Horizontal, Vertical, Container


class ConfirmDialog(ModalScreen[bool | None]):
    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self):
        yield Container(
            Label(self.message, id="dialog_message"),
            Horizontal(
                Button("Yes", id="yes", variant="primary"),
                Button("No", id="no"),
                Button("Cancel", id="cancel"),
                classes="dialog_buttons",
            ),
            id="dialog_container",
        )

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.dismiss(event.button.id == "yes")


class InputDialog(ModalScreen[str | None]):
    def __init__(self, message: str, default: str | None = None) -> None:
        super().__init__()
        self._message = message
        self._default = default

    def compose(self):
        yield Vertical(
            Label(self._message, id="dialog_message"),
            Container(
                Input(value=self._default or "", id="input"),
                id="input_container",
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            value = self.query_one(Input).value
            self.dismiss(value)
        else:
            self.dismiss(None)
