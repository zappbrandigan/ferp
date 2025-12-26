from __future__ import annotations

from typing import Callable

from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Static
from textual.timer import Timer


class CaptureInput(Input):
    """Input widget that triggers a callback on submission."""

    def __init__(self, submit_callback: Callable[[], None]) -> None:
        super().__init__(id="task_capture_input", placeholder="New task…")
        self._submit_callback = submit_callback

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit_callback()


class TaskCaptureModal(ModalScreen[None]):
    """Popup used for rapid task entry."""

    BINDINGS = [
        Binding("escape", "close", "Close modal", show=True),
        Binding("enter", "submit", "Submit new task", show=True),
    ]

    def __init__(self, on_submit: Callable[[str], None]) -> None:
        super().__init__()
        self._on_submit = on_submit
        self._area: CaptureInput | None = None
        self._status: Static | None = None
        self._clear_timer: Timer | None = None

    def compose(self):
        self._area = CaptureInput(self.action_submit)
        self._status = Static("", classes="task_capture_status")
        yield Container(
            Vertical(
                self._area,
                self._status,
                Footer()
            ),
            id="task_capture_modal",
        )

    def on_mount(self) -> None:
        container = self.query_one("#task_capture_modal", Container)
        container.border_title = "Add a New Task"
        if self._area:
            self._area.focus()

    def action_submit(self) -> None:
        area = self._area or self.query_one(Input)
        text = area.value.strip()
        if not text:
            return
        self._on_submit(text)
        area.value = ""
        if self._status:
            self._status.update("[green]Task saved[/]")
        if self._clear_timer:
            self._clear_timer.stop()
        self._clear_timer = self.set_timer(1.5, self._clear_status)

    def _clear_status(self) -> None:
        if self._status:
            self._status.update("")
        if self._clear_timer:
            self._clear_timer.stop()
            self._clear_timer = None

    def action_close(self) -> None:
        self.dismiss(None)
