from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SettingsStore:
    """Load and persist FERP user settings."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        """Read settings from disk, injecting expected sections."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
            except (OSError, json.JSONDecodeError):
                data = {}
        else:
            data = {}
        return self._with_defaults(data)

    def save(self, settings: dict[str, Any]) -> None:
        """Persist settings to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(settings, indent=4))

    def update_theme(self, settings: dict[str, Any], theme_name: str) -> None:
        """Store the active theme."""
        settings.setdefault("userPreferences", {})["theme"] = theme_name
        self.save(settings)

    def update_startup_path(self, settings: dict[str, Any], path: Path | str) -> None:
        """Store the startup directory."""
        settings.setdefault("userPreferences", {})["startupPath"] = str(path)
        self.save(settings)

    def log_preferences(self, settings: dict[str, Any]) -> tuple[int, int]:
        """Return (max_files, max_age_days) for transcript pruning."""
        logs = settings.setdefault("logs", {})
        max_files = self._coerce_positive_int(logs.get("maxFiles"), default=50, min_value=1)
        max_age_days = self._coerce_positive_int(logs.get("maxAgeDays"), default=14, min_value=0)
        return max_files, max_age_days

    def _with_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("userPreferences", {})
        data.setdefault("logs", {})
        return data

    def _coerce_positive_int(
        self,
        value: Any,
        *,
        default: int,
        min_value: int,
    ) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(min_value, number)
