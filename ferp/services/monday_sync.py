from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

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


def sync_monday_board(
    api_token: str, board_id: int, cache_path: Path
) -> dict[str, object]:
    query = """
    query ($boardId: [ID!], $cursor: String) {
      boards(ids: $boardId) {
        name
        groups { id title }
        items_page(limit: 500, cursor: $cursor) {
          cursor
          items {
            id
            name
            group { id }
            column_values { text column { title } }
            subitems {
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
            raise RuntimeError(f"Monday API error: {messages}")
        return body.get("data", {})

    data = fetch_page(None)
    boards = data.get("boards") or []
    if not boards:
        raise RuntimeError("Monday board not found.")

    board = boards[0]
    group_map = {
        group.get("id"): group.get("title")
        for group in board.get("groups", [])
        if group.get("id")
    }

    result: dict[str, list[dict[str, object]]] = {}
    publisher_count = 0
    skipped = 0

    def build_col_map(column_values: list[dict[str, Any]]) -> dict[str, str]:
        col_map: dict[str, str] = {}
        for col in column_values:
            column = col.get("column") or {}
            title = column.get("title")
            if not title:
                continue
            col_map[title] = col.get("text") or ""
        return col_map

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

            subitems = item.get("subitems") or []
            multi_territory = []
            for subitem in subitems:
                subitem_values = subitem.get("column_values") or []
                sub_map = build_col_map(subitem_values)
                multi_territory.append(
                    {
                        name.lower(): sub_map.get(name, "")
                        for name in MONDAY_SUBITEM_COLUMNS
                    }
                )

            group_info = item.get("group") or {}
            group_name = group_map.get(group_info.get("id"), "Ungrouped")
            group_key = group_name.lower()
            group_bucket = result.setdefault(group_key, [])
            row: dict[str, object] = {
                name.lower(): col_map.get(name, "") for name in MONDAY_REQUIRED_COLUMNS
            }
            if multi_territory:
                row["multi_territory"] = multi_territory
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

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    return {
        "cache_path": str(cache_path),
        "board_name": board.get("name", ""),
        "group_count": len(result),
        "publisher_count": publisher_count,
        "skipped": skipped,
    }
