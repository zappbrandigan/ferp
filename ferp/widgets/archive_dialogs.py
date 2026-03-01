from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from ferp.services.archive_ops import ArchiveFormat


@dataclass(frozen=True)
class ArchiveCreateDialogResult:
    output_path: str
    format: ArchiveFormat
    compression_level: int


class ArchiveSingleSelectList(OptionList):
    FAST_CURSOR_STEP = 5
    BINDINGS = [
        Binding("g", "first_option", "Top", show=False),
        Binding("G", "last_option", "Bottom", key_display="G", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("K", "cursor_up_fast", "Up (fast)", key_display="K", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("J", "cursor_down_fast", "Down (fast)", key_display="J", show=False),
    ]

    def __init__(
        self,
        rows: Sequence[tuple[str, str]],
        *,
        selected_id: str,
        id: str,
    ) -> None:
        self._rows = list(rows)
        self._selected_id = selected_id
        super().__init__(id=id)
        self._render_rows()

    @property
    def selected_id(self) -> str:
        return self._selected_id

    def select_value(self, option_id: str) -> None:
        if option_id == self._selected_id:
            return
        self._selected_id = option_id
        highlighted = self.highlighted
        self._render_rows()
        if highlighted is not None and highlighted < self.option_count:
            self.highlighted = highlighted

    def action_cursor_up_fast(self) -> None:
        for _ in range(self.FAST_CURSOR_STEP):
            super().action_cursor_up()

    def action_cursor_down_fast(self) -> None:
        for _ in range(self.FAST_CURSOR_STEP):
            super().action_cursor_down()

    def action_first_option(self) -> None:
        if self.option_count:
            self.highlighted = 0
            self.scroll_to(y=0)

    def action_last_option(self) -> None:
        if self.option_count:
            self.highlighted = self.option_count - 1

    @on(OptionList.OptionSelected)
    def _on_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self.select_value(event.option_id)

    def _render_rows(self) -> None:
        options: list[Option] = []
        for option_id, label in self._rows:
            marker = "☑" if option_id == self._selected_id else "☐"
            options.append(Option(f"{marker} {label}", id=option_id))
        self.set_options(options)


class ArchiveFormatList(ArchiveSingleSelectList):
    def __init__(self, *, selected_id: ArchiveFormat = "zip") -> None:
        super().__init__(
            (
                ("zip", "Zip (.zip)"),
                ("7z", "7z (.7z)"),
            ),
            selected_id=selected_id,
            id="archive_format_list",
        )

    @property
    def selected_id(self) -> ArchiveFormat:
        return cast(ArchiveFormat, super().selected_id)


class ArchiveCompressionList(ArchiveSingleSelectList):
    def __init__(self, *, selected_id: str = "0") -> None:
        super().__init__(
            tuple((str(level), str(level)) for level in range(0, 10)),
            selected_id=selected_id,
            id="archive_compression_list",
        )


class ArchiveCreateDialog(ModalScreen[ArchiveCreateDialogResult | None]):
    BINDINGS = [
        Binding("tab", "app.focus_next", "Next", show=False),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        *,
        default_output: str,
        default_format: ArchiveFormat = "zip",
        default_level: int = 6,
    ) -> None:
        super().__init__()
        self._default_output = default_output
        self._default_format: ArchiveFormat = default_format
        self._default_level = max(0, min(default_level, 9))
        self._input: Input | None = None
        self._format_list: ArchiveFormatList | None = None
        self._compression_list: ArchiveCompressionList | None = None

    def compose(self) -> ComposeResult:
        self._input = Input(value=self._default_output, id="archive_output_input")
        self._format_list = ArchiveFormatList(selected_id=self._default_format)
        self._compression_list = ArchiveCompressionList(
            selected_id=str(self._default_level)
        )
        yield Vertical(
            self._input,
            Horizontal(
                self._format_list,
                self._compression_list,
                id="archive_options_row",
            ),
            id="archive_create_dialog",
        )

    def on_mount(self) -> None:
        input_widget = self._input or self.query_one("#archive_output_input", Input)
        input_widget.border_title = "Create Archive"
        input_widget.border_subtitle = "Enter confirm | Esc cancel"
        self._input = input_widget

        format_list = self._format_list or self.query_one(
            "#archive_format_list", ArchiveFormatList
        )
        compression_list = self._compression_list or self.query_one(
            "#archive_compression_list", ArchiveCompressionList
        )
        format_list.border_title = "Archive Formats"
        compression_list.border_title = "Compression Levels"
        self._format_list = format_list
        self._compression_list = compression_list
        input_widget.focus()

    @on(Input.Submitted, "#archive_output_input")
    def _on_input_submitted(self, event: Input.Submitted) -> None:
        output = event.value.strip()
        if not output:
            return
        format_list = self._format_list
        compression_list = self._compression_list
        if format_list is None or compression_list is None:
            return
        self.dismiss(
            ArchiveCreateDialogResult(
                output_path=output,
                format=format_list.selected_id,
                compression_level=int(compression_list.selected_id),
            )
        )

    @on(OptionList.OptionSelected, "#archive_format_list")
    def _on_format_changed(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self._update_output_suffix(event.option_id)

    def _update_output_suffix(self, option_id: str) -> None:
        if self._input is None:
            return
        value = self._input.value
        if value.endswith(".zip"):
            base = value[:-4]
        elif value.endswith(".7z"):
            base = value[:-3]
        else:
            base = value
        suffix = ".zip" if option_id == "zip" else ".7z"
        self._input.value = f"{base}{suffix}"

    def action_cancel(self) -> None:
        self.dismiss(None)
