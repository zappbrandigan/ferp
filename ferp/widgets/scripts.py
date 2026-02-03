import json
from pathlib import Path
from typing import Sequence

from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Label, ListItem, ListView

from ferp.core.messages import RunScriptRequest, ShowReadmeRequest
from ferp.domain.scripts import Script, ScriptConfig


def script_from_config(cfg: ScriptConfig) -> Script:
    return Script(
        id=cfg["id"],
        name=cfg["name"],
        version=cfg["version"],
        script=cfg["script"],
        target=cfg["target"],
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
    def __init__(self, script: Script) -> None:
        category, name = (
            script.name.split(":", 1)
            if ":" in script.name
            else ("General", script.name)
        )
        super().__init__(
            Horizontal(
                Label(f"{category}:", classes="script_category"),
                Label(name, classes="script_name"),
                Label(f"v{script.version}", classes="script_version"),
                id="script_item",
            )
        )
        self.script = script


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
            self.append(ListItem(Label("No config.json found")))
            return

        try:
            scripts = load_scripts_configs(self.config_paths)
        except ValueError as exc:
            self.append(ListItem(Label(f"Invalid config: {exc}")))
            return

        if not scripts:
            self.append(ListItem(Label("No scripts configured")))
            return

        for script in scripts:
            self.append(ScriptItem(script))

        self.call_after_refresh(self._focus_first_script)

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

    def _visible_item_count(self) -> int:
        if not self.children:
            return 0

        first = self.children[0]
        row_height = first.size.height

        if row_height <= 0:
            return 0

        return (self.size.height // row_height) - 1
