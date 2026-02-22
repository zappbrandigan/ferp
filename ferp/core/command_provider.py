from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncGenerator, Iterable, cast

from textual.command import (
    CommandListItem,
    DiscoveryHit,
    Hit,
    Provider,
    SimpleCommand,
    SimpleProvider,
)
from textual.screen import Screen
from textual.style import Style
from textual.system_commands import SystemCommandsProvider

if TYPE_CHECKING:
    from ferp.core.app import Ferp


class FerpCommandProvider(SimpleProvider):
    """Command palette provider for FERP-specific actions."""

    _COMMAND_DEFS: tuple[tuple[str, str, str], ...] = (
        (
            "Add Script Bundle",
            "Add a custom .ferp script bundle.",
            "_command_install_script_bundle",
        ),
        (
            "Add/Update Default Scripts",
            "Add or update scripts from an existing namespace. This will overwrite any custom script bundles.",
            "_command_install_default_scripts",
        ),
        (
            "Open Latest Log",
            "Open the log file for the most recent script run.",
            "_command_open_latest_log",
        ),
        (
            "Open User Guide",
            "Open the bundled FERP user guide.",
            "_command_open_user_guide",
        ),
        (
            "Pull Monday Board Data",
            "Fetch data from the Monday board.",
            "_command_sync_monday_board",
        ),
        (
            "Set Monday API Token",
            "Update the Monday API token.",
            "_command_set_monday_api_token",
        ),
        (
            "Set Monday Board ID",
            "Update the Monday board id for the active namespace.",
            "_command_set_monday_board_id",
        ),
        (
            "Set Startup Directory",
            "Update the startup directory.",
            "_command_set_startup_directory",
        ),
        (
            "Upgrade FERP",
            "Upgrade FERP to the latest version.",
            "_command_upgrade_app",
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


class FerpCombinedCommandProvider(Provider):
    """Combines system, app, and screen providers for stable discovery ordering."""

    def __init__(
        self,
        screen: Screen[Any],
        match_style: Style | None = None,
    ) -> None:
        super().__init__(screen, match_style)
        screen_commands = getattr(screen, "COMMANDS", None)
        screen_providers: Iterable[type[Provider]] = (
            sorted(screen_commands, key=lambda item: item.__name__)
            if screen_commands
            else ()
        )
        providers: list[Provider] = [
            FerpCommandProvider(screen, match_style),
            SystemCommandsProvider(screen, match_style),
        ]
        for provider_cls in screen_providers:
            providers.append(provider_cls(screen, match_style))
        self._providers = providers

    async def discover(self) -> AsyncGenerator[DiscoveryHit | Hit, None]:
        for provider in self._providers:
            async for hit in provider.discover():
                if hit.prompt not in [
                    "Add Script Bundle",
                    "Set Monday API Token",
                    "Set Monday Board ID",
                ]:
                    yield hit

    async def search(self, query: str) -> AsyncGenerator[DiscoveryHit | Hit, None]:
        for provider in self._providers:
            async for hit in provider.search(query):
                yield hit
