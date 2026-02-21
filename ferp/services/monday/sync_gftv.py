from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from ferp.core.errors import FerpError

MONDAY_REQUIRED_COLUMNS = (
    "Publisher",
    "Territory",
    "Control Type",
    "Effective Date",
    "Expiration Date",
    "Status",
)
MONDAY_SUBITEM_COLUMNS = (
    "Effective Date",
    "Territory",
    "Status",
)
MONDAY_NAME_VARIANT_COLUMN = "Observed Name Variants"


def sync(api_token: str, board_id: int, cache_path: Path) -> dict[str, object]:
    query = """
    query ($boardId: [ID!], $cursor: String) {
      boards(ids: $boardId) {
        name
        description
        groups { id title }
        items_page(limit: 500, cursor: $cursor) {
          cursor
          items {
            id
            name
            group { id }
            column_values { text column { title } }
            subitems {
              name
              column_values { text column { title } }
            }
          }
        }
      }
    }
    """
    headers = {
        "Authorization": api_token,
        "Content-Type": "application/json",
    }

    def fetch_page(cursor: str | None) -> dict[str, Any]:
        payload = json.dumps(
            {
                "query": query,
                "variables": {"boardId": [board_id], "cursor": cursor},
            }
        ).encode("utf-8")
        request = Request("https://api.monday.com/v2", data=payload, headers=headers)
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
        if "errors" in body:
            messages = "; ".join(
                error.get("message", "Unknown error") for error in body["errors"]
            )
            raise FerpError(
                code="monday_api_error",
                message="Monday API error.",
                detail=messages,
            )
        return body.get("data", {})

    data = fetch_page(None)
    boards = data.get("boards") or []
    if not boards:
        raise FerpError(
            code="monday_board_not_found",
            message="Monday board not found.",
        )

    board = boards[0]
    group_map = {
        group.get("id"): group.get("title")
        for group in board.get("groups", [])
        if group.get("id")
    }

    result: dict[str, Any] = {}
    publisher_count = 0
    skipped = 0
    board_description = (board.get("description") or "").strip()

    def build_col_map(column_values: list[dict[str, Any]]) -> dict[str, str]:
        col_map: dict[str, str] = {}
        for col in column_values:
            column = col.get("column") or {}
            title = column.get("title")
            if not title:
                continue
            col_map[title] = col.get("text") or ""
        return col_map

    def split_name_variants(value: str) -> list[str]:
        if not value:
            return []
        parts = [part.strip() for part in value.split(",")]
        return [part for part in parts if part]

    while True:
        items_page = board.get("items_page") or {}
        items = items_page.get("items") or []
        for item in items:
            column_values = item.get("column_values") or []
            col_map = build_col_map(column_values)

            if "Publisher" not in col_map:
                col_map["Publisher"] = item.get("name") or ""
            publisher = col_map.get("Publisher", "").strip()
            if not publisher:
                skipped += 1
                continue

            territory_mode = col_map.get("Territory", "").strip()
            status_value = col_map.get("Status", "").strip()
            if status_value in ["Inactive", "Active: Do Not Stamp"]:
                skipped += 1
                continue
            subitems = item.get("subitems") or []
            subitem_rows: list[dict[str, str]] = []
            if territory_mode in {"Multiple", "Split"}:
                for subitem in subitems:
                    subitem_values = subitem.get("column_values") or []
                    sub_map = build_col_map(subitem_values)
                    row_data = {
                        name.lower(): sub_map.get(name, "")
                        for name in MONDAY_SUBITEM_COLUMNS
                    }
                    row_data["territory_code"] = subitem.get("name") or ""
                    subitem_rows.append(row_data)

            group_info = item.get("group") or {}
            group_name = group_map.get(group_info.get("id"), "Ungrouped")
            group_key = group_name.lower()
            group_bucket = result.setdefault(group_key, [])
            row: dict[str, object] = {
                name.lower(): col_map.get(name, "") for name in MONDAY_REQUIRED_COLUMNS
            }
            row["observed_name_variants"] = split_name_variants(
                col_map.get(MONDAY_NAME_VARIANT_COLUMN, "")
            )
            if territory_mode == "Multiple" and subitem_rows:
                row["multi_territory"] = subitem_rows
            elif territory_mode == "Split" and subitem_rows:
                row["split_territory"] = subitem_rows
            group_bucket.append(row)
            publisher_count += 1

        cursor = items_page.get("cursor")
        if not cursor:
            break
        data = fetch_page(cursor)
        boards = data.get("boards") or []
        if not boards:
            break
        board = boards[0]

    if board_description:
        meta = result.setdefault("__meta__", {})
        if isinstance(meta, dict):
            meta["board_description"] = board_description

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    return {
        "cache_path": str(cache_path),
        "board_name": board.get("name", ""),
        "group_count": len(result),
        "publisher_count": publisher_count,
        "skipped": skipped,
    }
