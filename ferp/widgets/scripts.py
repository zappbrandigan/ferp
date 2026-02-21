import json
from pathlib import Path
from typing import Sequence

from rich.text import Text
from textual.binding import Binding
from textual.widgets import ListItem, ListView

from ferp.core.messages import RunScriptRequest, ShowReadmeRequest
from ferp.core.paths import SCRIPTS_CONFIG_FILENAME
from ferp.domain.scripts import Script, ScriptConfig, normalize_targets


def script_from_config(cfg: ScriptConfig) -> Script:
    return Script(
        id=cfg["id"],
        name=cfg["name"],
        version=cfg["version"],
        script=cfg["script"],
        target=normalize_targets(cfg["target"]),
        file_extensions=cfg.get("file_extensions"),
    )


def load_scripts_config(path: Path) -> list[Script]:
    data = json.loads(path.read_text())

    if "scripts" not in data or not isinstance(data["scripts"], list):
        raise ValueError("Invalid config: missing 'scripts' list")

    scripts: list[Script] = []

    for raw in data["scripts"]:
        scripts.append(script_from_config(raw))  # type: ignore[arg-type]

    return sorted(scripts, key=lambda script: script.name.lower())


def load_scripts_configs(paths: Sequence[Path]) -> list[Script]:
    scripts_by_id: dict[str, Script] = {}
    errors: list[str] = []

    for path in paths:
        try:
            loaded = load_scripts_config(path)
        except ValueError as exc:
            errors.append(f"{path}: {exc}")
            continue
        for script in loaded:
            scripts_by_id.setdefault(script.id, script)

    if not scripts_by_id and errors:
        raise ValueError("; ".join(errors))

    return sorted(scripts_by_id.values(), key=lambda script: script.name.lower())


class ScriptItem(ListItem):
    COMPONENT_CLASSES = {
        "script_category",
        "script_name",
        "script_version",
    }

    def __init__(self, script: Script) -> None:
        category, name = self._split_name(script.name)
        self.script = script
        self._category = category
        self._name = name
        self._raw_name = script.name
        self._version = script.version
        super().__init__(classes="script_row")

    @staticmethod
    def _split_name(raw_name: str | None) -> tuple[str, str]:
        if not raw_name:
            return "General", "(unnamed)"
        if ":" not in raw_name:
            return "General", raw_name
        category, name = raw_name.split(":", 1)
        name = name.strip()
        if not name:
            return "General", raw_name
        return category.strip() or "General", name

    def render(self) -> Text:
        width = self.size.width
        category = (self._category or "General") + ":"
        name_value = self._name or ""
        if not name_value.strip():
            name_value = self._raw_name or ""
        prefix = category
        if name_value.startswith(prefix):
            name_value = name_value[len(prefix) :].lstrip()

        version_value = f"v{self._version}" if self._version else "v?"

        left_plain = f"{category} {name_value}"
        right_plain = version_value
        if width <= 0:
            spacer = " "
        else:
            pad = width - len(left_plain) - len(right_plain)
            spacer = " " * max(1, pad)

        line = f"{left_plain}{spacer}{right_plain}"
        text = Text(line)

        category_start = 0
        category_end = len(category)
        name_start = len(category) + 1
        name_end = name_start + len(name_value)
        version_start = len(line) - len(right_plain)
        version_end = len(line)

        text.stylize(
            self.get_component_rich_style("script_category"),
            category_start,
            category_end,
        )
        if name_value:
            text.stylize(
                self.get_component_rich_style("script_name"),
                name_start,
                name_end,
            )
        text.stylize(
            self.get_component_rich_style("script_version"),
            version_start,
            version_end,
        )
        return text


class StaticTextItem(ListItem):
    def __init__(self, message: str, *, classes: str | None = None) -> None:
        self._message = message
        super().__init__(classes=classes)
        self.can_focus = False

    def render(self) -> Text:
        text = Text(self._message)
        text.stylize(self.rich_style)
        return text


class ScriptManager(ListView):
    FAST_CURSOR_STEP = 5
    BINDINGS = [
        Binding("g", "cursor_top", "To top", show=False),
        Binding("G", "cursor_bottom", "To bottom", key_display="G", show=False),
        Binding("k", "cursor_up", "Move cursor up", show=False),
        Binding("K", "cursor_up_fast", "Cursor up (fast)", key_display="K", show=False),
        Binding("j", "cursor_down", "Move cursor down", show=False),
        Binding(
            "J", "cursor_down_fast", "Cursor down (fast)", key_display="J", show=False
        ),
        Binding("R", "run_script", "Run selected script", show=True),
        Binding("enter", "show_readme", "Show readme", show=True),
    ]

    def __init__(
        self, config_paths: Sequence[Path] | Path, *, scripts_root: Path, id: str
    ) -> None:
        if isinstance(config_paths, Path):
            self.config_paths = [config_paths]
        else:
            self.config_paths = list(config_paths)
        self.scripts_root = scripts_root
        super().__init__(id=id)

    def _get_selected_script(self) -> Script | None:
        item = self.highlighted_child
        if isinstance(item, ScriptItem):
            return item.script
        return None

    def on_mount(self) -> None:
        self.border_title = "Scripts"
        self.load_scripts()

    def load_scripts(self) -> None:
        self.clear()

        if not any(path.exists() for path in self.config_paths):
            self.border_subtitle = ""
            self.append(StaticTextItem(f"No {SCRIPTS_CONFIG_FILENAME} found"))
            return

        try:
            scripts = load_scripts_configs(self.config_paths)
        except ValueError as exc:
            self.border_subtitle = ""
            self.append(StaticTextItem(f"Invalid config: {exc}"))
            return

        if not scripts:
            self.border_subtitle = ""
            self.append(StaticTextItem("No scripts configured"))
            return
        self._set_namespace_subtitle()

        for script in scripts:
            self.append(ScriptItem(script))

        self.call_after_refresh(self._focus_first_script)

    def _set_namespace_subtitle(self) -> None:
        namespace = ""
        settings = getattr(self.app, "settings", None)
        if isinstance(settings, dict):
            preferences = settings.get("userPreferences", {})
            if isinstance(preferences, dict):
                value = preferences.get("scriptNamespace", "")
                if isinstance(value, str):
                    namespace = value.strip()
        self.border_subtitle = f"Namespace: {namespace}" if namespace else ""

    def _focus_first_script(self) -> None:
        if not self.children:
            return
        self.index = 0
        self.scroll_to(y=0)

    def action_run_script(self) -> None:
        script = self._get_selected_script()
        if not script:
            return

        self.post_message(RunScriptRequest(script))

    def action_show_readme(self) -> None:
        script = self._get_selected_script()
        if not script:
            return

        readme_path = self.resolve_readme(script)
        self.post_message(ShowReadmeRequest(script, readme_path))

    def resolve_readme(self, script: Script) -> Path | None:
        script_path = Path(script.script)
        if script_path.is_absolute():
            full_script_path = script_path
        elif script_path.parts and script_path.parts[0] == "scripts":
            full_script_path = (self.scripts_root.parent / script_path).resolve()
        else:
            full_script_path = (self.scripts_root / script_path).resolve()
        script_path = full_script_path
        candidate = script_path.parent / "readme.md"
        return candidate if candidate.exists() else None

    def action_cursor_down_fast(self) -> None:
        for _ in range(self.FAST_CURSOR_STEP):
            super().action_cursor_down()

    def action_cursor_up_fast(self) -> None:
        for _ in range(self.FAST_CURSOR_STEP):
            super().action_cursor_up()

    def action_cursor_top(self) -> None:
        if len(self.children) > 1:
            self.index = 0
            self.scroll_to(y=0)

    def action_cursor_bottom(self) -> None:
        if len(self.children) > 1:
            self.index = len(self.children) - 1
