from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from textual.worker import Worker, WorkerState

from ferp.core.script_runner import (
    ScriptInputRequest,
    ScriptResult,
    ScriptRunner,
    ScriptStatus,
)
from ferp.core.worker_groups import WorkerGroup
from ferp.core.worker_registry import worker_handler
from ferp.domain.scripts import Script
from ferp.services.scripts import ScriptExecutionContext
from ferp.services.file_listing import snapshot_directory
from ferp.widgets.dialogs import ConfirmDialog
from ferp.widgets.file_tree import FileTree
from ferp.widgets.forms import (
    BooleanField,
    PromptDialog,
    SelectField,
    SelectionField,
)
from ferp.widgets.scripts import ScriptManager

if TYPE_CHECKING:
    from ferp.core.app import Ferp


class ScriptLifecycleController:
    """Coordinates script execution, prompts, and progress UI."""

    _POST_SCRIPT_REFRESH_DELAY_S = 0.25

    def __init__(self, app: "Ferp") -> None:
        self._app = app
        self._runner = ScriptRunner(
            app.app_root,
            app._paths.cache_dir,
            self._handle_script_progress,
            namespace_resolver=app._active_namespace,
            settings_file=app._paths.settings_file,
        )
        self._progress_lines: list[str] = []
        self._progress_started_at: datetime | None = None
        self._script_running = False
        self._active_script_name: str | None = None
        self._active_target: Path | None = None
        self._active_worker: Worker | None = None
        self._abort_worker: Worker | None = None
        self._input_screen: PromptDialog | ConfirmDialog | None = None
        self._pre_script_path: Path | None = None
        self._pre_script_snapshot: tuple[str, ...] | None = None

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

    def abort_active(self, reason: str = "Operation canceled by user.") -> bool:
        if not self._script_running:
            return False
        self._dismiss_input_screen()
        cancelled = self._runner.abort(reason)
        if cancelled:
            script_name = self._active_script_name or "Script"
            self._app.render_script_output(script_name, cancelled)
        self._schedule_post_script_refresh()
        self._reset_after_script()
        return cancelled is not None

    def request_abort(self, reason: str = "Operation canceled by user.") -> bool:
        if not self._script_running:
            return False
        if self._abort_worker is not None:
            return True
        self._dismiss_input_screen()

        def abort() -> ScriptResult | None:
            return self._runner.abort(reason)

        try:
            self._abort_worker = self._app.run_worker(
                abort,
                group=WorkerGroup.SCRIPT_ABORT,
                exclusive=True,
                thread=True,
            )
        except Exception:
            self._abort_worker = None
            raise
        return True

    @worker_handler((WorkerGroup.SCRIPTS, WorkerGroup.SCRIPT_ABORT))
    def handle_worker_state(self, event: Worker.StateChanged) -> bool:
        worker = event.worker
        if worker.group not in {WorkerGroup.SCRIPTS, WorkerGroup.SCRIPT_ABORT}:
            return False
        if worker.group == WorkerGroup.SCRIPTS:
            if self._active_worker is None:
                if not self._script_running:
                    return True
            elif worker is not self._active_worker:
                return True

        state = event.state
        if state is WorkerState.RUNNING:
            return True

        if worker.group == WorkerGroup.SCRIPT_ABORT:
            if state is WorkerState.SUCCESS:
                result = worker.result
                if isinstance(result, ScriptResult):
                    self._app.render_script_output(
                        self._active_script_name or "Script",
                        result,
                    )
                    self._schedule_post_script_refresh()
                self._reset_after_script()
            elif state is WorkerState.ERROR:
                error = worker.error or RuntimeError("Script cancellation failed.")
                self._set_script_error(error)
                self._schedule_post_script_refresh()
                self._reset_after_script()
            if state in {WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED}:
                self._abort_worker = None
            return True

        if state is WorkerState.SUCCESS:
            result = worker.result
            if not isinstance(result, ScriptResult):
                return True

            if result.status is ScriptStatus.WAITING_INPUT:
                if result.input_request:
                    self._handle_input_request(result.input_request)
                else:
                    self._set_script_error(RuntimeError("Missing FSCP input details."))
                    self._runner.abort("Protocol error.")
                    self._reset_after_script()
                return True

            self._app.render_script_output(
                self._active_script_name or "Script",
                result,
            )
            self._schedule_post_script_refresh()
            self._reset_after_script()
            return True

        if state is WorkerState.ERROR:
            error = worker.error
            if error is not None:
                self._set_script_error(error)
            else:
                self._set_script_error(RuntimeError("Script worker failed."))
            self._runner.abort("Worker failed.")
            self._schedule_post_script_refresh()
            self._reset_after_script()
            return True

        if state is WorkerState.CANCELLED:
            self._reset_after_script()
            return True

        return True

    @worker_handler(WorkerGroup.SCRIPT_SNAPSHOT)
    def handle_snapshot_state(self, event: Worker.StateChanged) -> bool:
        if event.state is WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, tuple) and len(result) == 2:
                path, snapshot = result
                if isinstance(path, Path) and path == self._pre_script_path:
                    if isinstance(snapshot, tuple):
                        self._pre_script_snapshot = snapshot
        elif event.state is WorkerState.ERROR:
            self._pre_script_snapshot = None
        return True

    def handle_launch_failure(self) -> None:
        """Reset state if launching the worker raises."""
        self._script_running = False
        self._active_script_name = None
        self._active_target = None
        self._active_worker = None
        self._abort_worker = None
        self._progress_lines = []
        self._progress_started_at = None
        self._set_controls_disabled(False)
        self._app.state_store.set_status("Ready")
        self._set_script_error(RuntimeError("Script launch failed."))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _start_worker(self, runner_fn: Callable[[], ScriptResult]) -> None:
        self._script_running = True
        app = self._app
        app.state_store.set_status("Running")
        self._progress_lines = []
        self._progress_started_at = datetime.now()
        current_path = app.current_path
        self._pre_script_path = current_path
        self._pre_script_snapshot = None
        if current_path is not None:
            app.run_worker(
                lambda target=current_path: (
                    target,
                    snapshot_directory(
                        target,
                        hide_filtered_entries=app.hide_filtered_entries,
                    ),
                ),
                group=WorkerGroup.SCRIPT_SNAPSHOT,
                exclusive=True,
                thread=True,
            )
        app._stop_file_tree_watch()

        script_name = self._active_script_name or "Script"
        target = self._active_target or app.current_path
        app.state_store.update_script_run(
            phase="running",
            script_name=script_name,
            target_path=target,
            input_prompt=None,
            progress_message="",
            progress_line="",
            progress_current=None,
            progress_total=None,
            progress_unit="",
            result=None,
            transcript_path=None,
            error=None,
        )

        self._set_controls_disabled(True)
        self._focus_output_panel()

        try:
            worker = app.run_worker(
                runner_fn,
                group=WorkerGroup.SCRIPTS,
                exclusive=True,
                thread=True,
            )
            self._active_worker = worker
        except Exception:
            self.handle_launch_failure()
            raise

    def _handle_input_request(self, request: ScriptInputRequest) -> None:
        prompt = request.prompt or "Input required"
        self._app.state_store.update_script_run(
            phase="awaiting_input",
            input_prompt=prompt,
        )

        normalized_default = (request.default or "").strip().lower()
        is_confirm = request.mode == "confirm"
        if not is_confirm and normalized_default in {
            "true",
            "1",
            "yes",
            "y",
            "false",
            "0",
            "no",
            "n",
        }:
            is_confirm = True

        if is_confirm:

            def handle_confirm(value: bool | None) -> None:
                if value is None:
                    self._handle_user_cancelled()
                    return
                if not self._accept_input():
                    return
                self._input_screen = None
                payload = "true" if value else "false"
                self._start_worker(lambda: self._runner.provide_input(payload))

            dialog = ConfirmDialog(prompt, id="confirm_dialog")
            self._input_screen = dialog
            self._app.push_screen(dialog, handle_confirm)
            return

        bool_fields = self._boolean_fields_for_request(request)
        selection_fields = self._selection_fields_for_request(request)
        select_fields = self._select_fields_for_request(request)
        dialog = PromptDialog(
            prompt,
            default=request.default,
            suggestions=request.suggestions,
            boolean_fields=bool_fields,
            selection_fields=selection_fields,
            select_fields=select_fields,
            show_text_input=request.show_text_input,
            text_input_style=request.text_input_style,
            id="prompt_dialog",
        )

        def on_close(data: dict[str, str | bool | list[str]] | None) -> None:
            if data is None:
                self._handle_user_cancelled()
                return
            if not self._accept_input():
                return
            self._input_screen = None
            value = data.get("value", "")
            payload_value = str(value)
            payload = (
                json.dumps(data)
                if (bool_fields or selection_fields or select_fields)
                else payload_value
            )
            self._start_worker(lambda: self._runner.provide_input(payload))

        self._input_screen = dialog
        self._app.push_screen(dialog, on_close)

    def _handle_user_cancelled(self) -> None:
        self.abort_active("Operation canceled by user.")

    def _accept_input(self) -> bool:
        if not self._script_running:
            return False
        return self._runner.active_process_handle is not None

    def _dismiss_input_screen(self) -> None:
        screen = self._input_screen
        if screen is None:
            return
        if screen.is_active:
            try:
                screen.dismiss(None)
            except Exception:
                pass
        else:
            setattr(screen, "_dismiss_on_resume", True)
        self._input_screen = None

    def _set_script_error(self, error: BaseException) -> None:
        script_name = self._active_script_name or "Script"
        target = self._active_target or self._app.current_path
        self._app.state_store.update_script_run(
            phase="error",
            script_name=script_name,
            target_path=target,
            input_prompt=None,
            progress_message="",
            progress_line="",
            progress_current=None,
            progress_total=None,
            progress_unit="",
            result=None,
            transcript_path=None,
            error=str(error),
        )

    def _boolean_fields_for_request(
        self, request: ScriptInputRequest
    ) -> list[BooleanField]:
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

    def _selection_fields_for_request(
        self, request: ScriptInputRequest
    ) -> list[SelectionField]:
        fields: list[SelectionField] = []
        for field in request.fields:
            if field.get("type") != "multi_select":
                continue
            field_id = field.get("id")
            label = field.get("label")
            options = field.get("options")
            default = field.get("default", [])
            if not field_id or not label:
                continue
            if not isinstance(options, list) or not options:
                continue
            options_clean = [str(item) for item in options if item]
            if not options_clean:
                continue
            values = []
            if isinstance(default, list):
                values = [str(item) for item in default if item]
            fields.append(
                SelectionField(
                    str(field_id),
                    str(label),
                    options_clean,
                    values or None,
                )
            )
        return fields

    def _select_fields_for_request(
        self, request: ScriptInputRequest
    ) -> list[SelectField]:
        fields: list[SelectField] = []
        for field in request.fields:
            if field.get("type") != "select":
                continue
            field_id = field.get("id")
            label = field.get("label")
            options = field.get("options")
            default = field.get("default")
            if not field_id or not label:
                continue
            if not isinstance(options, list) or not options:
                continue
            options_clean = [str(item) for item in options if item]
            if not options_clean:
                continue
            default_value = None
            if isinstance(default, str) and default:
                default_value = default
            fields.append(
                SelectField(
                    str(field_id),
                    str(label),
                    options_clean,
                    default_value,
                )
            )
        return fields

    def _handle_script_progress(self, payload: dict[str, Any]) -> None:
        def update() -> None:
            current = self._coerce_float(payload.get("current"))
            if current is None:
                return

            total = self._coerce_float(payload.get("total"))
            unit = str(payload.get("unit")).strip() if payload.get("unit") else ""
            message = payload.get("message")
            message_text = str(message) if message is not None else ""

            line = self._format_progress_line(current, total, unit)
            if not line:
                return

            self._progress_lines.append(line)
            self._progress_lines = self._progress_lines[-1:]
            self._app.state_store.update_script_run(
                phase="running",
                progress_message=message_text,
                progress_line="\n".join(self._progress_lines),
                progress_current=current,
                progress_total=total,
                progress_unit=unit,
            )

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

        elapsed = self._format_elapsed()
        return f"[dim]{elapsed}[/dim] {progress}"

    def _format_elapsed(self) -> str:
        started_at = self._progress_started_at
        if started_at is None:
            total_seconds = 0
        else:
            total_seconds = int((datetime.now() - started_at).total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _reset_after_script(self) -> None:
        self._script_running = False
        self._active_script_name = None
        self._active_target = None
        self._progress_lines = []
        self._progress_started_at = None
        self._active_worker = None
        self._abort_worker = None
        self._input_screen = None
        self._pre_script_path = None
        self._pre_script_snapshot = None
        if self._app.is_shutting_down:
            self._app._maybe_exit_after_script()
            return
        self._set_controls_disabled(False)
        self._app.state_store.set_status("Ready")
        self._app.state_store.update_script_run(
            phase="idle",
            script_name=None,
            target_path=None,
            input_prompt=None,
            progress_message="",
            progress_line="",
            progress_current=None,
            progress_total=None,
            progress_unit="",
            result=None,
            transcript_path=None,
            error=None,
        )
        self._app._start_file_tree_watch()
        self._app._maybe_exit_after_script()

    def _focus_output_panel(self) -> None:
        try:
            container = self._app.query_one("#output_panel_container")
        except Exception:
            return
        if getattr(container, "disabled", False):
            return
        try:
            container.focus()
        except Exception:
            return

    def _set_controls_disabled(self, disabled: bool) -> None:
        visual_mode = self._app.visual_mode
        script_manager = self._app.query_one(ScriptManager)
        script_manager.disabled = disabled or visual_mode
        if disabled or visual_mode:
            script_manager.add_class("dimmed")
        else:
            script_manager.remove_class("dimmed")

        file_tree = self._app.query_one(FileTree)
        file_tree_container = self._app.query_one("#file_list_container")
        file_tree.disabled = disabled
        if disabled:
            file_tree_container.add_class("dimmed")
        else:
            file_tree_container.remove_class("dimmed")

    def _schedule_post_script_refresh(self) -> None:
        app = self._app
        should_refresh = True
        pre_path = self._pre_script_path
        if pre_path is not None and pre_path == app.current_path:
            try:
                post_snapshot = snapshot_directory(
                    pre_path,
                    hide_filtered_entries=app.hide_filtered_entries,
                )
            except Exception:
                post_snapshot = None
            if post_snapshot is not None and post_snapshot == self._pre_script_snapshot:
                should_refresh = False
        if should_refresh:
            app.suppress_watcher_refreshes(1.0)
            app.schedule_refresh_listing(
                delay=self._POST_SCRIPT_REFRESH_DELAY_S,
                suppress_focus=True,
            )
