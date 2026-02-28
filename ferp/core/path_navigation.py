from __future__ import annotations

from pathlib import Path, PurePath
from typing import TypeVar

_PathT = TypeVar("_PathT", bound=PurePath)


def parent_directory(path: _PathT) -> _PathT | None:
    parent = path.parent
    if parent == path:
        return None
    return parent


def can_navigate_up(path: PurePath) -> bool:
    return parent_directory(path) is not None


def is_navigable_directory(path: Path) -> bool:
    return path.exists() and path.is_dir()
