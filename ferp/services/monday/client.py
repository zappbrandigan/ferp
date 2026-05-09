from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen

from ferp.core.errors import FerpError

MONDAY_API_URL = "https://api.monday.com/v2"


class MondayClient:
    """Small Monday GraphQL client shared by board sync definitions."""

    def __init__(self, api_token: str, *, endpoint: str = MONDAY_API_URL) -> None:
        self._api_token = api_token
        self._endpoint = endpoint

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": self._api_token,
            "Content-Type": "application/json",
        }
        payload = json.dumps(
            {
                "query": query,
                "variables": variables,
            }
        ).encode("utf-8")
        request = Request(self._endpoint, data=payload, headers=headers)
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
        data = body.get("data", {})
        return data if isinstance(data, dict) else {}

