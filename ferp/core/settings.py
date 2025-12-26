import json
from pathlib import Path

def load_settings(app_root: Path) -> dict:
    path = app_root / "config" / "settings.json"
    return json.loads(path.read_text()) if path.exists() else {}

def save_settings(app_root: Path, settings: dict) -> None:
    path = app_root / "config" / "settings.json"
    path.write_text(json.dumps(settings, indent=4))
