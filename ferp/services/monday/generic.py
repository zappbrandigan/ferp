from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from ferp.core.errors import FerpError
from ferp.services.monday.client import MondayClient

GenericTransformType = Literal["raw_items", "items_by_group", "items_by_key_column"]


def generic_sync(
    client: MondayClient,
    board_id: int,
    cache_path: Path,
    *,
    query: str,
    transform: GenericTransformType,
    key_column: str | None = None,
) -> dict[str, object]:
    board, items = _fetch_board_items(client, board_id, query)
    rows = [_normalize_item(item, board) for item in items]
    payload = _transform_rows(rows, transform=transform, key_column=key_column)
    meta = payload.setdefault("__meta__", {})
    if isinstance(meta, dict):
        meta["board_name"] = str(board.get("name") or "")
        description = str(board.get("description") or "").strip()
        if description:
            meta["board_description"] = description

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return {
        "cache_path": str(cache_path),
        "board_name": board.get("name", ""),
        "item_count": len(rows),
        "group_count": _group_count(rows),
        "publisher_count": len(rows),
        "skipped": 0,
    }


def _fetch_board_items(
    client: MondayClient, board_id: int, query: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    board: dict[str, Any] | None = None
    while True:
        data = client.execute(query, {"boardId": [board_id], "cursor": cursor})
        boards = data.get("boards") or []
        if not boards:
            raise FerpError(
                code="monday_board_not_found",
                message="Monday board not found.",
            )
        board = boards[0]
        items_page = board.get("items_page") or {}
        page_items = items_page.get("items") or []
        items.extend(item for item in page_items if isinstance(item, dict))
        cursor = items_page.get("cursor")
        if not cursor:
            break
    return board or {}, items


def _normalize_item(item: dict[str, Any], board: dict[str, Any]) -> dict[str, Any]:
    columns = _normalize_column_values(item.get("column_values") or [])

    group_map = {
        group.get("id"): group.get("title")
        for group in board.get("groups", []) or []
        if group.get("id")
    }
    group = item.get("group") or {}
    group_id = group.get("id")
    group_title = str(group_map.get(group_id) or "Ungrouped")

    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "group": group_title,
        "columns": columns,
        "subitems": _normalize_subitems(item.get("subitems") or []),
    }


def _normalize_column_values(column_values: list[dict[str, Any]]) -> dict[str, str]:
    columns: dict[str, str] = {}
    for value in column_values:
        column = value.get("column") or {}
        title = str(column.get("title") or "").strip()
        if title:
            columns[title] = str(value.get("text") or "")
    return columns


def _normalize_subitems(subitems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for subitem in subitems:
        if not isinstance(subitem, dict):
            continue
        rows.append(
            {
                "name": str(subitem.get("name") or ""),
                "columns": _normalize_column_values(
                    subitem.get("column_values") or []
                ),
            }
        )
    return rows


def _transform_rows(
    rows: list[dict[str, Any]],
    *,
    transform: GenericTransformType,
    key_column: str | None,
) -> dict[str, Any]:
    if transform == "raw_items":
        return {"items": rows}

    if transform == "items_by_group":
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(str(row.get("group") or "Ungrouped"), []).append(row)
        return {"groups": groups}

    if transform == "items_by_key_column":
        if not key_column:
            raise FerpError(
                code="monday_definition_invalid",
                message="Monday definition is invalid.",
                detail="items_by_key_column requires transform.keyColumn.",
            )
        keyed: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            columns = row.get("columns")
            if not isinstance(columns, dict):
                continue
            value = str(columns.get(key_column) or "").strip()
            if not value:
                continue
            keyed.setdefault(value, []).append(row)
        return keyed

    raise FerpError(
        code="monday_definition_invalid",
        message="Monday definition is invalid.",
        detail=f"Unsupported transform: {transform}",
    )


def _group_count(rows: list[dict[str, Any]]) -> int:
    return len({str(row.get("group") or "Ungrouped") for row in rows})
