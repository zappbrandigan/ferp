from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotifyTimeouts:
    quick: float = 2.0
    short: float = 3.0
    normal: float = 4.0
    long: float = 6.0
    extended: float = 8.0
