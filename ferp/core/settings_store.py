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

    def update_script_namespace(self, settings: dict[str, Any], namespace: str) -> None:
        """Store the installed default scripts namespace."""
        settings.setdefault("userPreferences", {})["scriptNamespace"] = namespace
        self.save(settings)

    def update_script_versions(
        self,
        settings: dict[str, Any],
        *,
        core_version: str | None = None,
        namespace: str | None = None,
        namespace_version: str | None = None,
    ) -> None:
        """Store the installed default scripts versions."""
        preferences = settings.setdefault("userPreferences", {})
        versions = preferences.setdefault("scriptVersions", {})
        if not isinstance(versions, dict):
            versions = {}
            preferences["scriptVersions"] = versions
        if core_version:
            versions["core"] = core_version
        if namespace and namespace_version:
            namespaces = versions.setdefault("namespaces", {})
            if not isinstance(namespaces, dict):
                namespaces = {}
                versions["namespaces"] = namespaces
            namespaces[namespace] = namespace_version
        self.save(settings)

    def log_preferences(self, settings: dict[str, Any]) -> tuple[int, int]:
        """Return (max_files, max_age_days) for transcript pruning."""
        logs = settings.setdefault("logs", {})
        max_files = self._coerce_positive_int(
            logs.get("maxFiles"), default=50, min_value=1
        )
        max_age_days = self._coerce_positive_int(
            logs.get("maxAgeDays"), default=14, min_value=0
        )
        return max_files, max_age_days

    def _with_defaults(self, data: dict[str, Any]) -> dict[str, Any]:
        preferences = data.setdefault("userPreferences", {})
        preferences.setdefault("scriptNamespace", "")
        preferences.setdefault("scriptVersions", {"core": "", "namespaces": {}})
        data.setdefault("logs", {})
        integrations = data.setdefault("integrations", {})
        integrations.setdefault("monday", {})
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
