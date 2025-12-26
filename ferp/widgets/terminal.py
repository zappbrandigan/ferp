from __future__ import annotations

from pathlib import Path

from textual import on
from textual.binding import Binding
from textual.widget import Widget
from textual.app import ComposeResult
from textual.widgets import Input

from ferp.core.messages import TerminalCommandRequest


class TerminalWidget(Widget):
    """Hidden input bar for running shell commands."""

    BINDINGS = [
        Binding("escape", "hide", "Hide terminal", show=True),
    ]

    def __init__(self, id: str | None = None) -> None:
        super().__init__(id=id)
        self._cwd = Path.home()
        self._input: Input | None = None

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Quick command (no interactive apps)…", id="terminal_input")

    def on_mount(self) -> None:
        self.display = "none"
        self._input = self.query_one(Input)

    def show(self, cwd: Path) -> None:
        self._cwd = cwd
        self.display = "block"
        if self._input:
            self._input.value = ""
            self._input.focus()

    def hide(self) -> None:
        self.display = "none"
        if self._input:
            self._input.value = ""
        file_tree = self.app.query_one("#file_list")
        file_tree.focus()


    def action_hide(self) -> None:
        self.hide()

    @on(Input.Submitted)
    def handle_submit(self, event: Input.Submitted) -> None:
        if self._input is None or event.input is not self._input:
            return
        command = event.value.strip()
        if not command:
            self.hide()
            return
        self.post_message(TerminalCommandRequest(command, self._cwd))
        self.hide()
