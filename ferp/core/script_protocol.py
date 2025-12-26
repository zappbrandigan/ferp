from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class ScriptExitCode(int, Enum):
    SUCCESS = 0
    ERROR = 1
    CONFIRM = 10
    INPUT = 11
    SELECT = 12


class ScriptRequestType(str, Enum):
    CONFIRM = "confirm"
    INPUT = "input"
    SELECT = "select"
    PROGRESS = "progress"


@dataclass(frozen=True)
class ScriptRequest:
    type: ScriptRequestType
    message: str
    payload: Dict[str, Any]

    @staticmethod
    def from_json(data: Dict[str, Any]) -> "ScriptRequest":
        return ScriptRequest(
            type=ScriptRequestType(data["type"]),
            message=str(data.get("message", "")),
            payload=dict(data.get("payload", {})),
        )
