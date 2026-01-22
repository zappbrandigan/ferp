from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.markup import escape

from ferp.core.script_runner import ScriptResult
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
    ) -> None:
        super().__init__(initial_message, id=panel_id, title=title)

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
