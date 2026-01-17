from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.markup import escape

from ferp.core.script_runner import ScriptResult
from ferp.widgets.panels import ContentPanel


class ScriptOutputPanel(ContentPanel):
    """Specialized panel responsible for rendering script status and errors."""

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
            f"[bold $primary]Target:[/bold $primary] {escape(str(target))}",
            f"[bold $primary]Status:[/bold $primary] {status}",
        ]

        if result.exit_code is not None:
            lines.append(
                f"[bold $primary]Exit Code:[/bold $primary] {result.exit_code}"
            )

        if result.results:
            total = len(result.results)
            for index, payload in enumerate(result.results, start=1):
                lines.append(
                    f"\n[bold $success]Result {index} of {total}[/bold $success]\n"
                )
                for key, value in payload.items():
                    lines.append(self._format_pair(key, value))

        if result.error:
            lines.append("\n[bold $error]Error:[/bold $error]\n" + escape(result.error))

        if transcript_path:
            lines.append(
                f"\n[bold $secondary]Transcript:[/bold $secondary] [$text-secondary]{escape(str(transcript_path))}[/$text-secondary]"
            )

        self.remove_children()
        self.update_content("\n".join(lines))

    def _format_pair(self, key: Any, value: Any) -> str:
        return (
            f"[bold $text-primary]{escape(str(key))}:[/bold $text-primary] "
            f"{escape(self._stringify_value(value))}"
        )

    def _stringify_value(self, value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        return str(value)
