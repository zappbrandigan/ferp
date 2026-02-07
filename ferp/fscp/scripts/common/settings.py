from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ferp.fscp.scripts import sdk


def get_settings_path(ctx: sdk.ScriptContext) -> Path | None:
    """Return the host-provided settings file path, if available."""
    env_paths = ctx.environment.get("paths", {})
    settings_path_value = env_paths.get("settings_file")
    if not settings_path_value:
        return None
    return Path(settings_path_value)


def load_settings(ctx: sdk.ScriptContext) -> dict[str, Any]:
    """Load settings from the host-provided settings file path."""
    settings_path = get_settings_path(ctx)
    if settings_path is None or not settings_path.exists():
        return {}
    try:
        return json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(ctx: sdk.ScriptContext, payload: dict[str, Any]) -> str | None:
    """Persist settings to the host-provided settings file path."""
    settings_path = get_settings_path(ctx)
    if settings_path is None:
        return "Settings file path is not available."
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(payload, indent=4))
    except Exception as exc:
        return f"Unable to save settings: {exc}"
    return None
