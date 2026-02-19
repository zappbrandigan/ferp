from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["error", "warning", "information"]

DEFAULT_SEVERITY_BY_CODE: dict[str, Severity] = {
    "paste_nothing": "information",
}


@dataclass
class FerpError(Exception):
    code: str
    message: str
    detail: str | None = None
    severity: Severity = "error"

    def __str__(self) -> str:
        if self.detail:
            return f"{self.message} ({self.detail})"
        return self.message


def format_error(error: BaseException) -> tuple[str, Severity]:
    if isinstance(error, FerpError):
        prefix = f"[{error.code}] " if error.code else ""
        severity = DEFAULT_SEVERITY_BY_CODE.get(error.code, error.severity)
        return f"{prefix}{error}", severity
    return f"{error}", "error"


def wrap_error(
    error: BaseException,
    *,
    code: str,
    message: str,
    severity: Severity = "error",
) -> FerpError:
    if isinstance(error, FerpError):
        return error
    detail = str(error)
    return FerpError(code=code, message=message, detail=detail, severity=severity)
