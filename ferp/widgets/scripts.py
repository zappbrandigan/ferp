import json
from pathlib import Path

from textual.widgets import ListView, Label, ListItem
from textual.containers import Horizontal
from textual.binding import Binding

from ferp.core.messages import RunScriptRequest, ShowReadmeRequest
from ferp.domain.scripts import Script, ScriptConfig


def script_from_config(cfg: ScriptConfig) -> Script:
    return Script(
        id=cfg["id"],
        name=cfg["name"],
        version=cfg["version"],
        script=cfg["script"],
        args=cfg.get("args", []),
        requires_input=cfg["requires_input"],
        input_prompt=cfg.get("input_prompt"),
        target=cfg["target"]
    )


def load_scripts_config(path: Path) -> list[Script]:
    data = json.loads(path.read_text())

    if "scripts" not in data or not isinstance(data["scripts"], list):
        raise ValueError("Invalid config: missing 'scripts' list")

    scripts: list[Script] = []

    for raw in data["scripts"]:
        scripts.append(script_from_config(raw))  # type: ignore[arg-type]

    return sorted(scripts, key=lambda script: script.id)



class ScriptItem(ListItem):
    def __init__(self, script: Script) -> None:
        super().__init__(
            Horizontal(
                Label(script.name, classes="script_name"),
                Label(f"v{script.version}", classes="script_version"),
                id="script_item",
            )
        )
        self.script = script


class ScriptManager(ListView):

    BINDINGS = [
        Binding("g", "cursor_top", "To top", show=False),
        Binding("G", "cursor_bottom", "To bottom", key_display="shift+g", show=False),
        Binding("k", "cursor_up", "Move cursor up", show=False),
        Binding("K", "cursor_up_fast", "Cursor up (fast)", key_display="shift+k", show=False),
        Binding("j", "cursor_down", "Move cursor down", show=False),
        Binding("J", "cursor_down_fast", "Cursor down (fast)", key_display="shift+j", show=False),
        Binding("R", "run_script", "Run selected script", show=True),
        Binding("enter", "show_readme", "Show readme", show=True),
    ]

    def __init__(self, config_path: Path, id: str) -> None:
        self.config_path = config_path
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

        if not self.config_path.exists():
            self.append(ListItem(Label("No config.json found")))
            return

        try:
            scripts = load_scripts_config(self.config_path)
        except ValueError as exc:
            self.append(ListItem(Label(f"Invalid config: {exc}")))
            return

        if not scripts:
            self.append(ListItem(Label("No scripts configured")))
            return

        for script in scripts:
            self.append(ScriptItem(script))

        self.index = 0
        self.focus()

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
        base = self.config_path.parent.parent
        candidate = base / "scripts" / script.id / "readme.md"
        return candidate if candidate.exists() else None
    
    def action_cursor_down_fast(self) -> None:
        for _ in range(self._visible_item_count()):  
            super().action_cursor_down()

    def action_cursor_up_fast(self) -> None:
        for _ in range(self._visible_item_count()):  
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
    
