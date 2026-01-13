from __future__ import annotations

from typing import Any, TYPE_CHECKING, cast

from textual.command import CommandListItem, SimpleCommand, SimpleProvider
from textual.screen import Screen
from textual.style import Style

if TYPE_CHECKING:
    from ferp.core.app import Ferp


class FerpCommandProvider(SimpleProvider):
    """Command palette provider for Ferp-specific actions."""

    _COMMAND_DEFS: tuple[tuple[str, str, str], ...] = (
        (
            "Install Script Bundle…",
            "Install a zipped FSCP script bundle into Ferp.",
            "_command_install_script_bundle",
        ),
        (
            "Refresh File Tree",
            "Reload the current directory listing.",
            "_command_refresh_file_tree",
            ),
        (
            "Reload Script Catalog",
            "Re-read script metadata from config/config.json.",
            "_command_reload_scripts",
        ),
        (
            "Open Latest Log",
            "Open the most recent transcript log file.",
            "_command_open_latest_log",
        ),
        (
            "Show Processes",
            "View and manage tracked script processes.",
            "_command_show_processes",
        ),
        (
            "Set Startup Directory…",
            "Update the startup directory stored in settings.json.",
            "_command_set_startup_directory",
        ),
    )

    def __init__(self, screen: Screen[Any], match_style: Style | None = None) -> None:
        app = cast("Ferp", screen.app)
        commands: list[CommandListItem] = [
            SimpleCommand(label, getattr(app, handler_name), description)
            for label, description, handler_name in self._COMMAND_DEFS
        ]
        super().__init__(screen, commands)
        if match_style is not None:
            self._SimpleProvider__match_style = match_style  # type: ignore[attr-defined]
