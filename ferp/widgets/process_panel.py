from __future__ import annotations

from typing import Callable

from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import ListItem, ListView, Static

from ferp.fscp.host.process_registry import ProcessRecord, ProcessRegistry
from ferp.fscp.protocol.state import HostState


class ProcessPanelListView(ListView):
    def on_focus(self) -> None:
        if self.index is not None:
            return
        for idx, child in enumerate(self.children):
            if isinstance(child, ListItem) and not child.disabled:
                self.index = idx
                break


class ProcessListPanel(Vertical):
    BINDINGS = [
        Binding("r", "refresh", "Refresh", show=True),
        Binding("p", "prune_finished", "Prune finished", show=True),
        Binding("k", "kill_selected", "Kill selected", show=True),
    ]

    def __init__(
        self,
        registry: ProcessRegistry,
        request_abort: Callable[[ProcessRecord], bool],
    ) -> None:
        super().__init__(id="process_panel")
        self._registry = registry
        self._request_abort = request_abort
        self._status: Static | None = None

    def compose(self):
        yield ProcessPanelListView(id="process_panel_list")
        status = Static("", id="process_panel_status")
        self._status = status
        yield status

    def on_mount(self) -> None:
        self.border_title = "Processes"
        self._refresh()
        self._registry.add_listener(self._on_registry_update)

    def on_unmount(self) -> None:
        self._registry.remove_listener(self._on_registry_update)

    def _on_registry_update(self) -> None:
        try:
            app = self.app
        except Exception:
            return
        try:
            app.call_from_thread(self._refresh)
        except RuntimeError:
            self._refresh()

    def action_refresh(self) -> None:
        self._refresh()

    def action_prune_finished(self) -> None:
        removed = self._registry.prune_finished()
        self._set_status(f"Pruned {len(removed)} finished process(es).")
        self._refresh()
        self._clear_status_after_delay()

    def action_kill_selected(self) -> None:
        list_view = self.query_one(ListView)
        if list_view.index is None:
            self._set_status("Select a process first.")
            return
        try:
            item = list_view.children[list_view.index]
        except IndexError:
            self._set_status("No process selected.")
            return
        if not isinstance(item, ProcessPanelItem):
            self._set_status("Invalid selection.")
            return
        record = item.record
        if record.is_terminal:
            self._set_status("Process already finished.")
            return
        killed = self._request_abort(record)
        if killed:
            self._set_status("Termination requested.")
            self.set_timer(0.2, self._refresh)
            self.set_timer(0.8, self._refresh)
            self._clear_status_after_delay()
        else:
            self._set_status("Unable to terminate this process.")

    def _refresh(self) -> None:
        list_view = self.query_one(ListView)
        list_view.clear()
        records = sorted(
            self._registry.list_all(), key=lambda rec: rec.start_time, reverse=True
        )
        if not records:
            placeholder = ListItem(
                Static("No tracked processes."),
                classes="process_row process_row--empty",
            )
            placeholder.disabled = True
            list_view.append(placeholder)
            return
        for record in records:
            list_view.append(ProcessPanelItem(record))

    def _set_status(self, message: str) -> None:
        status = self._status
        if status is None:
            return
        status.update(message)

    def _clear_status_after_delay(self) -> None:
        self.set_timer(1.2, self._clear_status)

    def _clear_status(self) -> None:
        self._set_status("")


class ProcessPanelItem(ListItem):
    """Compact row for the embedded process panel."""

    def __init__(self, record: ProcessRecord) -> None:
        self.record = record
        body = Vertical(
            Static(self._render_title(record), classes="process_row_title"),
            Static(self._render_meta(record), classes="process_row_meta"),
        )
        super().__init__(body, classes="process_row")

    @staticmethod
    def _render_title(record: ProcessRecord) -> str:
        pid = record.pid
        pid_label = f" · pid {pid}" if pid is not None else ""
        status = ProcessPanelItem._friendly_status(record)
        return f"{record.metadata.script_name} · {status}{pid_label}"

    @classmethod
    def _render_meta(cls, record: ProcessRecord) -> str:
        target = record.metadata.target_path
        target_label = target.name or str(target)
        return cls._abbreviate_label(target_label)

    @staticmethod
    def _abbreviate_label(label: str, max_len: int = 32) -> str:
        if len(label) <= max_len:
            return f"target: {label}"
        if max_len < 7:
            return f"target: {label[:max_len]}"
        head = (max_len - 3) // 2
        tail = max_len - 3 - head
        return f"target: {label[:head]}...{label[-tail:]}"

    @staticmethod
    def _friendly_status(record: ProcessRecord) -> str:
        if record.state in {HostState.ERR_PROTOCOL, HostState.ERR_TRANSPORT}:
            return "[$error]Error[/]"
        if record.state is HostState.CANCELLING:
            return "[$warning]Canceling[/]"
        if record.termination_mode in {"cancel", "kill", "terminate"}:
            return "[$warning]Canceled[/]"
        if record.termination_mode in {
            "protocol-error",
            "transport-error",
            "abnormal-exit",
        }:
            return "[$error]Error[/]"
        if record.exit_code not in (None, 0):
            return "[$error]Error[/]"
        if record.state is HostState.TERMINATED:
            return "[$success]Finished[/]"
        if record.state is HostState.AWAITING_INPUT:
            return "[$warning]Waiting for input[/]"
        if record.state is HostState.RUNNING:
            return "[$warning]Running[/]"
        return record.state.name.replace("_", " ").title()
