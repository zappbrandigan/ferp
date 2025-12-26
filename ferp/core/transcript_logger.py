from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from ferp.core.script_runner import ScriptResult


class TranscriptLogger:
    """Writes script transcripts and prunes historical logs."""

    def __init__(
        self,
        base_dir: Path,
        log_preferences: Callable[[], tuple[int, int]],
    ) -> None:
        self._logs_dir = base_dir / "data" / "logs"
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        self._log_preferences = log_preferences

    def write(
        self,
        script_name: str,
        target_path: Path,
        result: ScriptResult,
    ) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = "".join(
            ch.lower() if ch.isalnum() else "_"
            for ch in script_name.strip()
        ).strip("_") or "script"
        filename = f"{timestamp}_{slug}.log"
        path = self._logs_dir / filename

        lines = [
            f"Script: {script_name}",
            f"Target: {target_path}",
            f"Status: {result.status.value}",
            f"Exit Code: {result.exit_code}",
            "",
            "Transcript:",
        ]

        for event in result.transcript:
            if event.message:
                payload = json.dumps(
                    event.message.payload,
                    ensure_ascii=False,
                    indent=2,
                )
                lines.append(
                    f"{event.direction.value.upper()} "
                    f"{event.message.type.value}: {payload}"
                )
            elif event.raw:
                lines.append(f"{event.direction.value.upper()}: {event.raw}")

        path.write_text("\n".join(lines), encoding="utf-8")
        self._prune()
        return path

    def _prune(self) -> None:
        max_files, max_age_days = self._log_preferences()
        entries = sorted(
            self._logs_dir.glob("*.log"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

        cutoff = None
        if max_age_days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        for index, entry in enumerate(entries):
            remove = index >= max_files
            if not remove and cutoff is not None:
                try:
                    mtime = datetime.fromtimestamp(
                        entry.stat().st_mtime,
                        tz=timezone.utc,
                    )
                except (OSError, ValueError):
                    mtime = None
                if mtime is not None and mtime < cutoff:
                    remove = True

            if remove:
                try:
                    entry.unlink()
                except OSError:
                    pass
