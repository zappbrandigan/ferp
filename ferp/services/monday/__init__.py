from __future__ import annotations

from pathlib import Path

from ferp.core.errors import FerpError
from ferp.services.monday.client import MondayClient
from ferp.services.monday.definitions import (
    MondaySyncDefinition,
    load_user_monday_sync_definitions,
    monday_sync_definition,
    monday_sync_definitions,
)


def sync_monday_board(
    namespace: str,
    definition_id: str,
    api_token: str,
    board_id: int,
    cache_path: Path,
    *,
    config_dir: Path | None = None,
) -> dict[str, object]:
    definition = monday_sync_definition(namespace, definition_id, config_dir=config_dir)
    if definition is None:
        raise FerpError(
            code="monday_handler_missing",
            message="No Monday sync handler registered.",
            detail=f"{namespace}:{definition_id}",
        )
    client = MondayClient(api_token)
    return definition.handler(client, board_id, cache_path)


__all__ = [
    "MondaySyncDefinition",
    "load_user_monday_sync_definitions",
    "monday_sync_definition",
    "monday_sync_definitions",
    "sync_monday_board",
]
