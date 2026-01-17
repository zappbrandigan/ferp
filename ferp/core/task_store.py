from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Task:
    id: str
    text: str
    completed: bool = False
    created_at: datetime = field(default_factory=_utcnow)
    completed_at: datetime | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "text": self.text,
            "completed": self.completed,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> Task:
        created_at = payload.get("created_at")
        completed_at = payload.get("completed_at")
        return cls(
            id=str(payload.get("id") or uuid.uuid4()),
            text=str(payload.get("text") or "").strip(),
            completed=bool(payload.get("completed", False)),
            created_at=datetime.fromisoformat(created_at)
            if isinstance(created_at, str)
            else _utcnow(),
            completed_at=datetime.fromisoformat(completed_at)
            if isinstance(completed_at, str)
            else None,
        )


class TaskStore:
    """File-backed store for lightweight tasks."""

    def __init__(self, storage_path: Path) -> None:
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._tasks: list[Task] = []
        self._listeners: set[Callable[[Sequence[Task]], None]] = set()
        self.load()

    def load(self) -> list[Task]:
        if not self.storage_path.exists():
            self._tasks = []
            return []

        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._tasks = []
            return []

        if not isinstance(data, list):
            self._tasks = []
            return []

        tasks: list[Task] = []
        for raw in data:
            if isinstance(raw, dict):
                tasks.append(Task.from_json(raw))
        self._tasks = tasks
        return list(self._tasks)

    def save(self) -> None:
        payload = [task.to_json() for task in self._tasks]
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def subscribe(self, callback: Callable[[Sequence[Task]], None]) -> None:
        self._listeners.add(callback)
        callback(tuple(self._tasks))

    def unsubscribe(self, callback: Callable[[Sequence[Task]], None]) -> None:
        self._listeners.discard(callback)

    def _emit(self) -> None:
        snapshot = tuple(self._tasks)
        for callback in list(self._listeners):
            callback(snapshot)

    def all(self) -> list[Task]:
        return list(self._tasks)

    def sorted(self) -> list[Task]:
        indexed = list(enumerate(self._tasks))
        indexed.sort(key=lambda pair: (pair[1].completed, pair[0]))
        return [task for _, task in indexed]

    def add(self, text: str) -> Task:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Task text is required.")
        new_task = Task(
            id=str(uuid.uuid4()),
            text=normalized,
            completed=False,
            created_at=_utcnow(),
            completed_at=None,
        )
        self._tasks.append(new_task)
        self.save()
        self._emit()
        return new_task

    def delete(self, task_id: str) -> None:
        before = len(self._tasks)
        self._tasks = [task for task in self._tasks if task.id != task_id]
        if len(self._tasks) != before:
            self.save()
            self._emit()

    def update_text(self, task_id: str, new_text: str) -> Task | None:
        normalized = new_text.strip()
        if not normalized:
            return None
        for task in self._tasks:
            if task.id == task_id:
                task.text = normalized
                self.save()
                self._emit()
                return task
        return None

    def toggle(self, task_id: str) -> Task | None:
        for task in self._tasks:
            if task.id == task_id:
                task.completed = not task.completed
                task.completed_at = _utcnow() if task.completed else None
                self.save()
                self._emit()
                return task
        return None

    def clear_completed(self) -> None:
        any_removed = any(task.completed for task in self._tasks)
        if not any_removed:
            return
        self._tasks = [task for task in self._tasks if not task.completed]
        self.save()
        self._emit()

    def import_tasks(self, tasks: Iterable[Task]) -> None:
        """Replace the current list with provided tasks (used for testing)."""
        self._tasks = list(tasks)
        self.save()
        self._emit()
