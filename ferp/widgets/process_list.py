from __future__ import annotations

from datetime import datetime
from typing import Callable

from textual import on
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, ListItem, ListView, Static

from ferp.fscp.host.process_registry import ProcessRecord, ProcessRegistry


class ProcessListItem(ListItem):
    """Row showing a single tracked process."""

    def __init__(self, record: ProcessRecord) -> None:
        self.record = record
        body = Vertical(
            Static(self._render_title(record), classes="process_row_title"),
            Static(self._render_meta(record), classes="process_row_meta"),
        )
        super().__init__(body, classes="process_row")

    @staticmethod
    def _render_title(record: ProcessRecord) -> str:
        pid = record.pid if record.pid is not None else "?"
        state = record.state.name.replace("_", " ").title()
        return f"{record.metadata.script_name} · pid {pid} · {state}"

    @staticmethod
    def _render_meta(record: ProcessRecord) -> str:
        started = datetime.fromtimestamp(record.start_time).strftime("%Y-%m-%d %H:%M:%S")
        target = record.metadata.target_path
        exit_code = f" · exit {record.exit_code}" if record.exit_code is not None else ""
        mode = f" · {record.termination_mode}" if record.termination_mode else ""
        return f"{target} · started {started}{exit_code}{mode}"


class ProcessListScreen(ModalScreen[None]):
    """Modal view over currently tracked processes."""

    BINDINGS = [
        Binding("escape", "close", "Close", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("p", "prune_finished", "Prune finished", show=True),
        Binding("k", "kill_selected", "Kill selected", show=True),
    ]

    def __init__(
        self,
        registry: ProcessRegistry,
        request_abort: Callable[[ProcessRecord], bool],
    ) -> None:
        super().__init__()
        self._registry = registry
        self._request_abort = request_abort
        self._status: Static | None = None

    def compose(self):
        list_view = ListView(id="process_list_view")
        list_view.border_title = "Processes"
        status = Static("", id="process_list_status")
        self._status = status
        yield Container(
            Vertical(
                list_view,
                status,
                Footer(),
            ),
            id="process_list_modal",
        )

    def on_mount(self) -> None:
        self._refresh()
        list_view = self.query_one(ListView)
        list_view.focus()

    @on(ListView.Highlighted, "#process_list_view")
    def _clear_status_on_move(self, _: ListView.Highlighted) -> None:
        self._set_status("")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_refresh(self) -> None:
        self._refresh()

    def action_prune_finished(self) -> None:
        removed = self._registry.prune_finished()
        self._set_status(f"Pruned {len(removed)} finished process(es).")
        self._refresh()

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
        if not isinstance(item, ProcessListItem):
            self._set_status("Invalid selection.")
            return
        record = item.record
        if record.is_terminal:
            self._set_status("Process already finished.")
            return
        killed = self._request_abort(record)
        if killed:
            self._set_status("Termination requested.")
            self._refresh()
        else:
            self._set_status("Unable to terminate this process.")

    def _refresh(self) -> None:
        list_view = self.query_one(ListView)
        list_view.clear()
        records = sorted(self._registry.list_all(), key=lambda rec: rec.start_time, reverse=True)
        if not records:
            placeholder = ListItem(Static("No tracked processes."), classes="process_row process_row--empty")
            placeholder.disabled = True
            list_view.append(placeholder)
            return
        for record in records:
            list_view.append(ProcessListItem(record))

    def _set_status(self, message: str) -> None:
        status = self._status
        if status is None:
            return
        status.update(message)
