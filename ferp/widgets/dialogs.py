from rich.style import Style
from rich.text import Text
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label


class ConfirmDialog(ModalScreen[bool | None]):
    def __init__(self, message: str, id="confirm_dialog"):
        super().__init__(id=id)
        self.message = message

    def compose(self):
        yield Container(
            Label(self.message, id="dialog_message"),
            Horizontal(
                Button("Yes", id="yes", variant="primary", flat=True),
                Button("No", id="cancel", flat=True),
                classes="dialog_buttons",
            ),
            id="dialog_container",
        )

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(False)
            return
        self.dismiss(event.button.id == "yes")

    def on_screen_resume(self) -> None:
        if getattr(self, "_dismiss_on_resume", False):
            self.dismiss(None)


class BulkRenameConfirmDialog(ModalScreen[bool | None]):
    def __init__(
        self,
        title: str,
        rows: list[tuple[str, str]],
        more_count: int = 0,
    ) -> None:
        super().__init__(id="bulk_rename_confirm_dialog")
        self.dialog_title: str = title or ""
        self.rows: list[tuple[str, str]] = rows
        self.more_count = more_count

    def compose(self):
        table = DataTable(
            id="bulk_rename_preview_table", show_cursor=False, disabled=True
        )
        table.add_column("From", width=75)
        table.add_column("To", width=75)
        if self.rows:
            success_color = self.app.theme_variables["success"]
            error_color = self.app.theme_variables["error"]
            styled_rows = [
                (
                    Text(src, style=Style(color=error_color)),
                    Text(dest, style=Style(color=success_color)),
                )
                for src, dest in self.rows
            ]
            table.add_rows(styled_rows)
        yield Container(
            Label(self.dialog_title, id="bulk_rename_dialog_title"),
            table,
            Label(
                f"... and {self.more_count} more.",
                id="bulk_rename_dialog_message",
                classes="" if self.more_count else "hidden",
            ),
            Horizontal(
                Button("Yes", id="bulk_rename_yes", variant="primary", flat=True),
                Button("No", id="bulk_rename_cancel", flat=True),
                classes="dialog_buttons",
            ),
            id="bulk_rename_dialog_container",
        )

    def on_button_pressed(self, event):
        if event.button.id == "bulk_rename_cancel":
            self.dismiss(False)
            return
        self.dismiss(event.button.id == "bulk_rename_yes")

    def on_screen_resume(self) -> None:
        if getattr(self, "_dismiss_on_resume", False):
            self.dismiss(None)


class InputDialog(ModalScreen[str | None]):
    def __init__(
        self, message: str, id: str = "input_dialog", default: str | None = None
    ) -> None:
        super().__init__(id=id)
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
                Button("OK", id="ok", variant="primary", flat=True),
                Button("Cancel", id="cancel", flat=True),
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
