from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from rich.markup import escape
from textual.containers import Vertical
from textual.widgets import ProgressBar, Static
from textual.worker import Worker, WorkerState

from ferp.core.script_runner import (
    ScriptInputRequest,
    ScriptResult,
    ScriptRunner,
    ScriptStatus,
)
from ferp.domain.scripts import Script
from ferp.services.scripts import ScriptExecutionContext
from ferp.widgets.dialogs import ConfirmDialog
from ferp.widgets.file_tree import FileTree
from ferp.widgets.forms import BooleanField, PromptDialog
from ferp.widgets.output_panel import ScriptOutputPanel
from ferp.widgets.scripts import ScriptManager
from ferp.widgets.top_bar import TopBar

if TYPE_CHECKING:
    from ferp.core.app import Ferp


class ScriptLifecycleController:
    """Coordinates script execution, prompts, and progress UI."""

    def __init__(self, app: "Ferp") -> None:
        self._app = app
        self._runner = ScriptRunner(app.app_root, self._handle_script_progress)
        self._progress_lines: list[str] = []
        self._progress_bar_widget: ProgressBar | None = None
        self._progress_status_widget: Static | None = None
        self._script_running = False
        self._active_script_name: str | None = None
        self._active_target: Path | None = None

    @property
    def is_running(self) -> bool:
        return self._script_running

    @property
    def active_target(self) -> Path | None:
        return self._active_target

    @property
    def active_script_name(self) -> str | None:
        return self._active_script_name

    @property
    def process_registry(self):
        return self._runner.process_registry

    @property
    def active_process_handle(self) -> str | None:
        return self._runner.active_process_handle

    def run_script(self, script: Script, context: ScriptExecutionContext) -> None:
        if self._script_running:
            return
        self._active_script_name = script.name
        self._active_target = context.target_path
        self._start_worker(lambda: self._runner.start(context))

    def abort_active(self, reason: str = "Operation cancelled by user.") -> bool:
        if not self._script_running:
            return False
        cancelled = self._runner.abort(reason)
        if cancelled:
            script_name = self._active_script_name or "Script"
            self._app.render_script_output(script_name, cancelled)
        self._app.refresh_listing()
        self._reset_after_script()
        return cancelled is not None

    def handle_worker_state(self, event: Worker.StateChanged) -> bool:
        worker = event.worker
        if worker.group != "scripts":
            return False

        state = event.state
        if state is WorkerState.RUNNING:
            return True

        if state is WorkerState.SUCCESS:
            result = worker.result
            if not isinstance(result, ScriptResult):
                return True

            if result.status is ScriptStatus.WAITING_INPUT:
                if result.input_request:
                    self._handle_input_request(result.input_request)
                else:
                    self._app.show_error(RuntimeError("Missing FSCP input details."))
                    self._runner.abort("Protocol error.")
                    self._reset_after_script()
                return True

            self._app.render_script_output(
                self._active_script_name or "Script",
                result,
            )
            self._app.refresh_listing()
            self._reset_after_script()
            return True

        if state is WorkerState.ERROR:
            error = worker.error
            if error is not None:
                self._app.show_error(error)
            else:
                self._app.show_error(RuntimeError("Script worker failed."))
            self._runner.abort("Worker failed.")
            self._app.refresh_listing()
            self._reset_after_script()
            return True

        if state is WorkerState.CANCELLED:
            self._reset_after_script()
            return True

        return True

    def handle_launch_failure(self) -> None:
        """Reset state if launching the worker raises."""
        self._script_running = False
        self._active_script_name = None
        self._active_target = None
        self._progress_bar_widget = None
        self._progress_status_widget = None
        self._progress_lines = []
        self._set_controls_disabled(False)
        self._app.query_one(TopBar).status = "Idle"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _start_worker(self, runner_fn: Callable[[], ScriptResult]) -> None:
        self._script_running = True
        app = self._app
        app.query_one(TopBar).status = "Running script"
        output_panel = app.query_one(ScriptOutputPanel)
        self._progress_lines = []
        output_panel.remove_children()

        script_name = self._active_script_name or "Script"
        target = self._active_target or app.current_path
        header = Static(
            (
                f"[bold $primary]Script:[/bold $primary] {escape(script_name)}\n"
                f"[bold $primary]Target:[/bold $primary] {escape(str(target))}"
            ),
            id="progress_header",
        )
        self._progress_bar_widget = ProgressBar(total=None, show_eta=False, id="script_progress_bar")
        self._progress_status_widget = Static(
            "[dim]Waiting for progress…[/dim]", id="progress_status"
        )

        output_panel.mount(
            header,
            Vertical(
                self._progress_bar_widget,
                self._progress_status_widget,
                id="progress-container",
            ),
        )

        self._set_controls_disabled(True)

        try:
            app.run_worker(
                runner_fn,
                group="scripts",
                exclusive=True,
                thread=True,
            )
        except Exception:
            self.handle_launch_failure()
            raise

    def _handle_input_request(self, request: ScriptInputRequest) -> None:
        self._progress_bar_widget = None
        self._progress_status_widget = None
        panel = self._app.query_one(ScriptOutputPanel)
        panel.remove_children()
        prompt = request.prompt or "Input required"
        panel.update_content(
            "[bold $primary]Input requested:[/bold $primary] " + escape(prompt)
        )

        normalized_default = (request.default or "").strip().lower()
        is_confirm = request.mode == "confirm"
        if not is_confirm and normalized_default in {"true", "1", "yes", "y", "false", "0", "no", "n"}:
            is_confirm = True

        if is_confirm:
            self._app.query_one(TopBar).status = "Awaiting confirmation"

            def handle_confirm(value: bool | None) -> None:
                if value is None:
                    self._handle_user_cancelled()
                    return
                payload = "true" if value else "false"
                self._start_worker(lambda: self._runner.provide_input(payload))

            self._app.push_screen(
                ConfirmDialog(prompt, id="confirm_dialog"),
                handle_confirm,
            )
            return

        self._app.query_one(TopBar).status = "Awaiting input"
        bool_fields = self._boolean_fields_for_request(request)
        dialog = PromptDialog(
            prompt,
            default=request.default,
            boolean_fields=bool_fields,
            show_text_input=request.show_text_input,
            id="prompt_dialog",
        )

        def on_close(data: dict[str, str | bool] | None) -> None:
            if data is None:
                self._handle_user_cancelled()
                return
            value = data.get("value", "")
            payload_value = str(value)
            payload = json.dumps(data) if bool_fields else payload_value
            self._start_worker(lambda: self._runner.provide_input(payload))

        self._app.push_screen(dialog, on_close)

    def _handle_user_cancelled(self) -> None:
        self.abort_active("Operation cancelled by user.")

    def _boolean_fields_for_request(self, request: ScriptInputRequest) -> list[BooleanField]:
        fields: list[BooleanField] = []
        for field in request.fields:
            if field.get("type") != "bool":
                continue
            field_id = field.get("id")
            label = field.get("label")
            if not field_id or not label:
                continue
            fields.append(
                BooleanField(
                    str(field_id),
                    str(label),
                    bool(field.get("default", False)),
                )
            )
        return fields

    def _handle_script_progress(self, payload: dict[str, Any]) -> None:
        def update() -> None:
            bar = self._progress_bar_widget
            status_widget = self._progress_status_widget
            if bar is None or status_widget is None:
                return

            current = self._coerce_float(payload.get("current"))
            if current is None:
                return

            total = self._coerce_float(payload.get("total"))
            unit = str(payload.get("unit")).strip() if payload.get("unit") else ""

            if total is not None and total >= 0:
                bar.update(total=total, progress=max(0.0, min(current, total)))
            else:
                bar.update(total=None)

            line = self._format_progress_line(current, total, unit)
            if not line:
                return

            self._progress_lines.append(line)
            self._progress_lines = self._progress_lines[-1:]
            status_widget.update("\n".join(self._progress_lines))

        self._app.call_from_thread(update)

    def _coerce_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _format_progress_line(
        self,
        current: float,
        total: float | None,
        unit: str,
    ) -> str | None:
        def fmt(value: float) -> str:
            if abs(value - int(value)) < 1e-6:
                return str(int(value))
            return f"{value:.2f}".rstrip("0").rstrip(".")

        if total is not None and total > 0:
            percent = (current / total) * 100
            progress = (
                f"{fmt(current)}/{fmt(total)}"
                + (f" {unit}" if unit else "")
                + f" ({percent:.0f}%)"
            )
        else:
            progress = f"{fmt(current)}" + (f" {unit}" if unit else "")

        timestamp = datetime.now().strftime("%H:%M:%S")
        return f"[dim]{timestamp}[/dim] {progress}"

    def _reset_after_script(self) -> None:
        self._script_running = False
        self._active_script_name = None
        self._active_target = None
        self._progress_bar_widget = None
        self._progress_status_widget = None
        self._progress_lines = []
        self._set_controls_disabled(False)
        self._app.query_one(TopBar).status = "Idle"

    def _set_controls_disabled(self, disabled: bool) -> None:
        script_manager = self._app.query_one(ScriptManager)
        script_manager.disabled = disabled
        if disabled:
            script_manager.add_class("dimmed")
        else:
            script_manager.remove_class("dimmed")

        file_tree = self._app.query_one(FileTree)
        file_tree.disabled = disabled
        if disabled:
            file_tree.add_class("dimmed")
        else:
            file_tree.remove_class("dimmed")
