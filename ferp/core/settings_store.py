from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ferp.core.settings_model import SettingsModel


class SettingsStore:
    """Load and persist FERP user settings."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> dict[str, Any]:
        """Read settings from disk, injecting expected sections."""
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text())
            except (OSError, json.JSONDecodeError):
                raw = {}
        else:
            raw = {}
        migrated = self._migrate(raw)
        normalized = self._normalize(migrated)
        if self._should_persist_upgrade(raw, normalized):
            self._backup_raw_settings()
            self.save(normalized)
        return normalized

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

    def update_hide_filtered_entries(
        self,
        settings: dict[str, Any],
        value: bool,
    ) -> None:
        """Store whether hidden / filtered entries should be excluded."""
        settings.setdefault("userPreferences", {})["hideFilteredEntries"] = bool(value)
        self.save(settings)

    def update_sort_preferences(
        self,
        settings: dict[str, Any],
        *,
        sort_by: str | None = None,
        sort_descending: bool | None = None,
    ) -> None:
        """Store file listing sort preferences."""
        preferences = settings.setdefault("userPreferences", {})
        if sort_by is not None:
            preferences["sortBy"] = str(sort_by)
        if sort_descending is not None:
            preferences["sortDescending"] = bool(sort_descending)
        self.save(settings)

    def update_script_namespace(self, settings: dict[str, Any], namespace: str) -> None:
        """Store the installed default scripts namespace."""
        settings.setdefault("userPreferences", {})["scriptNamespace"] = namespace
        self.save(settings)

    def update_drive_inventory(
        self,
        settings: dict[str, Any],
        *,
        entries: list[dict[str, Any]],
        last_checked_at: float,
    ) -> None:
        """Persist cached drive inventory metadata."""
        settings["driveInventory"] = {
            "entries": list(entries),
            "lastCheckedAt": float(last_checked_at),
        }
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

    def _normalize(self, data: dict[str, Any]) -> dict[str, Any]:
        try:
            model = SettingsModel.model_validate(data or {})
        except ValidationError:
            model = SettingsModel()
        return model.model_dump()

    def _migrate(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        version = data.get("schemaVersion")
        if not isinstance(version, int):
            version = 0
        if version < 1:
            data = dict(data)
            data["schemaVersion"] = 1
        return data

    def _should_persist_upgrade(
        self, raw: dict[str, Any], normalized: dict[str, Any]
    ) -> bool:
        if not isinstance(raw, dict):
            return True
        if raw.get("schemaVersion") != normalized.get("schemaVersion"):
            return True
        return raw != normalized

    def _backup_raw_settings(self) -> None:
        if not self._path.exists():
            return
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        backup_path = self._path.with_name(f"{self._path.stem}.bak-{timestamp}.json")
        try:
            backup_path.write_text(self._path.read_text())
        except OSError:
            pass

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
