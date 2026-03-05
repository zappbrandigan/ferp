from __future__ import annotations

from pathlib import Path
from typing import Callable

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class CaptureInput(Input):
    """Input widget that triggers a callback on submission."""

    def __init__(
        self,
        submit_callback: Callable[[], None],
        *,
        input_id: str = "task_capture_input",
        placeholder: str = "New task...",
    ) -> None:
        super().__init__(id=input_id, placeholder=placeholder)
        self._submit_callback = submit_callback

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit_callback()


class TaskCaptureModal(ModalScreen[None]):
    """Popup used for rapid task entry."""

    _LINK_LABEL_MAX = 28

    BINDINGS = [
        Binding("escape", "close", "Close modal", show=True),
        Binding("enter", "submit", "Submit new task", show=True),
        Binding("ctrl+l", "toggle_link", "Toggle path link", show=True),
    ]

    def __init__(
        self,
        on_submit: Callable[[str, Path | None], None],
        *,
        linked_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._on_submit = on_submit
        self._linked_path = linked_path
        self._link_enabled = linked_path is not None
        self._area: CaptureInput | None = None
        self._link_state: Static | None = None

    def compose(self):
        self._area = CaptureInput(self.action_submit)
        self._link_state = Static("", id="task_capture_link_state")
        yield Vertical(self._area, self._link_state, id="task_capture_modal")

    def on_mount(self) -> None:
        area = self._area or self.query_one("#task_capture_input", CaptureInput)
        area.border_title = "Add Task"
        area.border_subtitle = "Enter save | Esc close"
        area.focus()
        self._area = area
        if self._link_state is None:
            self._link_state = self.query_one("#task_capture_link_state", Static)
        self._refresh_link_state()

    def action_submit(self) -> None:
        area = self._area or self.query_one(Input)
        text = area.value.strip()
        if not text:
            return
        linked_path = self._linked_path if self._link_enabled else None
        self._on_submit(text, linked_path)
        area.value = ""
        self.app.notify("Task saved.", timeout=1.0)
        self._refresh_link_state()

    def action_toggle_link(self) -> None:
        if self._linked_path is None:
            self.app.bell()
            return
        self._link_enabled = not self._link_enabled
        state = "Path link on." if self._link_enabled else "Path link off."
        self.app.notify(state, timeout=1.0)
        self._refresh_link_state()

    def _refresh_link_state(self) -> None:
        if self._link_state is None:
            return
        if self._linked_path is None:
            self._link_state.update("[dim]Link: unavailable[/dim]")
            return
        label = self._linked_path_label()
        if self._link_enabled:
            self._link_state.update(
                f"[dim]Link:[/] {label}  [dim](Ctrl+L to unlink)[/dim]"
            )
            return
        self._link_state.update(
            f"[dim]Link:[/] off  [dim](Ctrl+L to relink {label})[/dim]"
        )

    def _linked_path_label(self) -> str:
        label = self._linked_path.name if self._linked_path is not None else ""
        label = label or (str(self._linked_path) if self._linked_path else "")
        if len(label) <= self._LINK_LABEL_MAX:
            return label
        if self._LINK_LABEL_MAX <= 3:
            return label[: self._LINK_LABEL_MAX]
        return f"{label[: self._LINK_LABEL_MAX - 3]}..."

    def action_close(self) -> None:
        self.dismiss(None)
