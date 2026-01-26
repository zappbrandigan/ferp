from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.markup import escape
from textual.containers import Vertical
from textual.widgets import ProgressBar, Static

from ferp.core.script_runner import ScriptResult
from ferp.core.state import AppState, AppStateStore, ScriptRunState
from ferp.widgets.panels import ContentPanel


class ScriptOutputPanel(ContentPanel):
    """Specialized panel responsible for rendering script status and errors."""

    _MAX_VALUE_CHARS = 2500
    _TRUNCATION_SUFFIX = "\n... (truncated)"

    def __init__(
        self,
        *,
        title: str = "Script Output",
        panel_id: str = "output_panel",
        initial_message: str = "No script output.",
        state_store: AppStateStore,
    ) -> None:
        super().__init__(initial_message, id=panel_id, title=title)
        self._state_store = state_store
        self._state_subscription = self._handle_state_update
        self._last_script_run: ScriptRunState | None = None
        self._progress_header: Static | None = None
        self._progress_message: Static | None = None
        self._progress_bar: ProgressBar | None = None
        self._progress_status: Static | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self._state_store.subscribe(self._state_subscription)

    def on_unmount(self) -> None:
        self._state_store.unsubscribe(self._state_subscription)

    def show_error(self, error: BaseException) -> None:
        self.remove_children()
        self.update_content("[bold $error]Error:[/bold $error]\n" + escape(str(error)))

    def show_result(
        self,
        script_name: str,
        target: Path,
        result: ScriptResult,
        transcript_path: Path | None = None,
    ) -> None:
        status = result.status.value.replace("_", " ").title()
        lines: list[str] = [
            f"[bold $primary]Script:[/bold $primary] {escape(script_name)}",
            f"[bold $primary]Target:[/bold $primary] {escape(str(target.name))}",
            f"[bold $primary]Status:[/bold $primary] {status}",
        ]

        if result.exit_code is not None:
            lines.append(
                f"[bold $primary]Exit Code:[/bold $primary] {result.exit_code}"
            )

        if result.results:
            total = len(result.results)
            for index, payload in enumerate(result.results, start=1):
                header_text, header_style = self._result_header(payload, index, total)
                lines.append(
                    f"\n[bold {header_style}]{escape(header_text)}[/bold {header_style}]\n"
                )
                format_hint = payload.get("_format")
                if (
                    isinstance(format_hint, str)
                    and format_hint.strip().lower() == "json"
                ):
                    cleaned = {
                        key: value
                        for key, value in payload.items()
                        if not (isinstance(key, str) and key.startswith("_"))
                    }
                    lines.append(self._format_pair("json", cleaned))
                    continue
                for key, value in payload.items():
                    if isinstance(key, str) and key.startswith("_"):
                        continue
                    lines.append(self._format_pair(key, value))

        if result.error:
            lines.append("\n[bold $error]Error:[/bold $error]\n" + escape(result.error))

        if transcript_path:
            lines.append(
                f"\n[bold $secondary]Transcript:[/bold $secondary] [$text-secondary]{escape(str(transcript_path.name))}[/$text-secondary]"
            )

        self.remove_children()
        self.update_content("\n".join(lines))

    def _handle_state_update(self, state: AppState) -> None:
        script_run = state.script_run
        if self._last_script_run == script_run:
            return
        self._last_script_run = script_run
        self._render_script_state(script_run)

    def _render_script_state(self, script_run: ScriptRunState) -> None:
        phase = script_run.phase
        if phase == "running":
            self._render_progress(script_run)
            return
        if phase == "awaiting_input":
            self._clear_progress()
            self.remove_children()
            prompt = script_run.input_prompt or "Input required"
            self.update_content(
                "[bold $primary]Input requested:[/bold $primary] " + escape(prompt)
            )
            return
        if phase == "result" and script_run.result is not None:
            self._clear_progress()
            script_name = script_run.script_name or "Script"
            target = script_run.target_path or Path(".")
            self.show_result(
                script_name,
                target,
                script_run.result,
                script_run.transcript_path,
            )
            return
        if phase == "error" and script_run.error:
            self._clear_progress()
            self.remove_children()
            self.update_content(
                "[bold $error]Error:[/bold $error]\n" + escape(script_run.error)
            )

    def _render_progress(self, script_run: ScriptRunState) -> None:
        script_name = script_run.script_name or "Script"
        target = script_run.target_path
        target_label = escape(str(target)) if target else "Unknown"
        header_text = (
            f"[bold $primary]Script:[/bold $primary] {escape(script_name)}\n"
            f"[bold $primary]Target:[/bold $primary] {target_label}"
        )

        if self._progress_bar is None or self._progress_header is None:
            self.remove_children()
            self._progress_header = Static(header_text, id="progress_header")
            self._progress_message = Static("", id="progress_message")
            self._progress_bar = ProgressBar(
                total=None,
                show_eta=False,
                id="script_progress_bar",
                show_percentage=False,
            )
            self._progress_status = Static(
                "[dim]Working, please wait...[/dim]",
                id="progress_status",
            )
            self.mount(
                self._progress_header,
                Vertical(
                    self._progress_message,
                    self._progress_bar,
                    self._progress_status,
                    id="progress-container",
                ),
            )
        else:
            self._progress_header.update(header_text)

        if self._progress_message is not None:
            self._progress_message.update(escape(script_run.progress_message or ""))
        if self._progress_bar is not None:
            total = script_run.progress_total
            current = script_run.progress_current
            if total is not None and total >= 0 and current is not None:
                self._progress_bar.update(
                    total=total, progress=max(0.0, min(current, total))
                )
            else:
                self._progress_bar.update(total=None)
        if self._progress_status is not None and script_run.progress_line:
            self._progress_status.update(script_run.progress_line)

    def _clear_progress(self) -> None:
        self._progress_header = None
        self._progress_message = None
        self._progress_bar = None
        self._progress_status = None

    def _format_pair(self, key: Any, value: Any) -> str:
        label = f"[bold $text-primary]{escape(str(key))}:[/bold $text-primary]"
        body = escape(self._stringify_value(value))
        return f"{label} {body}"

    def _result_header(
        self,
        payload: dict[str, Any],
        index: int,
        total: int,
    ) -> tuple[str, str]:
        header_text = f"Result {index} of {total}"
        status = "success"
        custom_title = payload.get("_title")
        if isinstance(custom_title, str) and custom_title.strip():
            header_text = custom_title.strip()
        custom_status = payload.get("_status")
        if isinstance(custom_status, str):
            status = custom_status.strip().lower()
        status_to_style = {
            "success": "$success",
            "ok": "$success",
            "warn": "$warning",
            "warning": "$warning",
            "error": "$error",
            "fail": "$error",
            "failed": "$error",
        }
        return header_text, status_to_style.get(status, "$success")

    def _stringify_value(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, (str, int, float, bool)):
            return self._truncate_value(str(value))
        if isinstance(value, (dict, list)):
            try:
                return self._truncate_value(
                    json.dumps(value, indent=2, ensure_ascii=True)
                )
            except (TypeError, ValueError):
                return self._truncate_value(str(value))
        return self._truncate_value(str(value))

    def _truncate_value(self, value: str) -> str:
        if len(value) <= self._MAX_VALUE_CHARS:
            return value
        return value[: self._MAX_VALUE_CHARS] + self._TRUNCATION_SUFFIX
