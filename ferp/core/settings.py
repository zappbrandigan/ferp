import json
from pathlib import Path

from platformdirs import user_config_path

from ferp.core.paths import APP_AUTHOR, APP_NAME

def load_settings(app_root: Path) -> dict:
    path = Path(user_config_path(APP_NAME, APP_AUTHOR)) / "settings.json"
    return json.loads(path.read_text()) if path.exists() else {}

def save_settings(app_root: Path, settings: dict) -> None:
    path = Path(user_config_path(APP_NAME, APP_AUTHOR)) / "settings.json"
    path.write_text(json.dumps(settings, indent=4))
