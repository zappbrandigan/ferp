from rich.style import Style
from rich.text import Text
from textual import on
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, OptionList, Select
from textual.widgets.option_list import Option


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
        self,
        message: str,
        id: str = "input_dialog",
        default: str | None = None,
        subtitle: str | None = "Enter confirm | Esc cancel",
    ) -> None:
        super().__init__(id=id)
        self._message = message
        self._default = default
        self._subtitle = subtitle

    def compose(self):
        yield Input(
            value=self._default or "",
            id="input_dialog_input",
        )

    def on_mount(self) -> None:
        input_widget = self.query_one("#input_dialog_input", Input)
        input_widget.border_title = self._message
        input_widget.border_subtitle = self._subtitle or ""
        input_widget.focus()

    @on(Input.Submitted, "#input_dialog_input")
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class SelectDialog(ModalScreen[str | None]):
    def __init__(
        self,
        message: str,
        options: list[str],
        *,
        default: str | None = None,
        id: str = "select_dialog",
    ) -> None:
        super().__init__(id=id)
        self._message = message
        self._options = options
        self._default = default

    def compose(self):
        select_options = [(option, option) for option in self._options]
        default = (
            self._default
            if self._default in self._options
            else (self._options[0] if self._options else "")
        )
        yield Vertical(
            Label(self._message, id="dialog_message"),
            Container(
                Select(
                    select_options,
                    value=default,
                    allow_blank=False,
                    id="select",
                ),
                id="select_container",
            ),
            Horizontal(
                Button("OK", id="ok", variant="primary", flat=True),
                Button("Cancel", id="cancel", flat=True),
                classes="dialog_buttons",
            ),
            id="dialog_container",
        )

    def on_mount(self) -> None:
        self.query_one(Select).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            value = self.query_one(Select).value
            self.dismiss(str(value) if value is not None else None)
        else:
            self.dismiss(None)


class SortOrderDialog(ModalScreen[str | None]):
    _MODE_ROWS: tuple[tuple[str, str, str], ...] = (
        ("name", "a", "Name"),
        ("extension", "e", "Extension"),
        ("natural", "n", "Natural"),
        ("size", "s", "Size"),
        ("created", "c", "Created"),
        ("modified", "m", "Modified"),
    )

    def __init__(
        self,
        *,
        current_mode: str,
        sort_descending: bool,
        id: str = "sort_dialog",
    ) -> None:
        super().__init__(id=id)
        self._current_mode = current_mode
        self._sort_descending = sort_descending
        self._option_ids: list[str] = []

    def compose(self):
        yield Container(
            OptionList(*self._build_options(), id="sort_order_list"),
            id="sort_dialog_container",
        )

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.focus()
        if self._current_mode in self._option_ids:
            option_list.highlighted = self._option_ids.index(self._current_mode)

    def _build_options(self) -> list[Option]:
        self._option_ids = []
        options: list[Option] = []
        for mode_id, key_hint, label in self._MODE_ROWS:
            marker = "☑" if mode_id == self._current_mode else "☐"
            options.append(
                Option(f"{marker} [dim]{key_hint}[/dim] {label}", id=mode_id)
            )
            self._option_ids.append(mode_id)
        options.append(Option("[dim]----------------[/dim]", disabled=True))
        direction_prefix = "☑" if self._sort_descending else "☐"
        options.append(
            Option(f"{direction_prefix} [dim]d[/dim] Descending", id="descending")
        )
        self._option_ids.append("descending")
        return options

    @on(OptionList.OptionSelected)
    def _handle_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        self.dismiss(option_id if option_id else None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
            return
        key_map = {
            "a": "name",
            "e": "extension",
            "n": "natural",
            "s": "size",
            "c": "created",
            "m": "modified",
            "d": "descending",
        }
        option_id = key_map.get((event.character or "").lower())
        if option_id is not None:
            self.dismiss(option_id)
