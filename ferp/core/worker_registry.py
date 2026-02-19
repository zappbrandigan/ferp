from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any, Callable, ParamSpec, Protocol, TypeVar


class WorkerEvent(Protocol):
    @property
    def worker(self) -> Any: ...


WorkerHandler = Callable[[WorkerEvent], bool]
P = ParamSpec("P")
R = TypeVar("R")


def worker_handler(
    groups: str | Iterable[str],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    group_list = (groups,) if isinstance(groups, str) else tuple(groups)

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        setattr(fn, "_worker_groups", group_list)
        return fn

    return decorator


class WorkerRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, list[WorkerHandler]] = {}

    def register(self, group: str, handler: WorkerHandler) -> None:
        self._handlers.setdefault(group, []).append(handler)

    def bind(self, target: object) -> None:
        for name, member in vars(type(target)).items():
            if isinstance(member, staticmethod):
                func = member.__func__
            elif isinstance(member, classmethod):
                func = member.__func__
            elif inspect.isfunction(member):
                func = member
            else:
                continue
            groups = getattr(func, "_worker_groups", None)
            if not groups:
                continue
            value = getattr(target, name)
            for group in groups:
                self.register(group, value)

    def dispatch(self, event: WorkerEvent) -> bool:
        worker = event.worker
        group = getattr(worker, "group", None)
        if not isinstance(group, str):
            return False
        handlers = self._handlers.get(group, [])
        for handler in handlers:
            handled = handler(event)
            if handled:
                return True
        return False
