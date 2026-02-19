from __future__ import annotations

from pathlib import Path
from typing import Callable

from ferp.core.errors import FerpError
from ferp.services.monday.sync_gftv import sync as sync_gftv

_SYNC_HANDLERS: dict[str, Callable[[str, int, Path], dict[str, object]]] = {
    "gftv": sync_gftv,
}


def sync_monday_board(
    namespace: str, api_token: str, board_id: int, cache_path: Path
) -> dict[str, object]:
    handler = _SYNC_HANDLERS.get(namespace)
    if handler is None:
        raise FerpError(
            code="monday_handler_missing",
            message="No Monday sync handler registered.",
            detail=namespace,
        )
    return handler(api_token, board_id, cache_path)
