from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ferp.core.script_runner import ScriptResult


@dataclass(frozen=True, slots=True)
class ScriptRunState:
    phase: str = "idle"
    script_name: str | None = None
    target_path: Path | None = None
    input_prompt: str | None = None
    progress_message: str = ""
    progress_line: str = ""
    progress_current: float | None = None
    progress_total: float | None = None
    progress_unit: str = ""
    result: ScriptResult | None = None
    transcript_path: Path | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FileTreeState:
    filter_query: str = ""
    current_listing_path: Path | None = None
    last_selected_path: Path | None = None
    selection_history: dict[Path, Path] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskListState:
    active_tag_filter: frozenset[str] = frozenset()
    highlighted_task_id: str | None = None


@dataclass(frozen=True, slots=True)
class AppState:
    current_path: str = ""
    highlighted_path: Path | None = None
    status: str = "Ready"
    cache_updated_at: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)
    script_run: ScriptRunState = field(default_factory=ScriptRunState)


class AppStateStore:
    def __init__(self, initial: AppState | None = None) -> None:
        self._state = initial or AppState()
        self._listeners: set[Callable[[AppState], None]] = set()

    @property
    def state(self) -> AppState:
        return self._state

    def subscribe(self, callback: Callable[[AppState], None]) -> None:
        self._listeners.add(callback)
        callback(self._state)

    def unsubscribe(self, callback: Callable[[AppState], None]) -> None:
        self._listeners.discard(callback)

    def set_current_path(self, value: str) -> None:
        self._update_state(current_path=value)

    def set_highlighted_path(self, value: Path | None) -> None:
        self._update_state(highlighted_path=value)

    def set_status(self, value: str) -> None:
        self._update_state(status=value)

    def set_cache_updated_at(self, value: datetime) -> None:
        self._update_state(cache_updated_at=value)

    def update_script_run(self, **changes: object) -> None:
        self._update_state(script_run=replace(self._state.script_run, **changes))

    def _update_state(self, **changes: object) -> None:
        new_state = replace(self._state, **changes)
        if new_state == self._state:
            return
        self._state = new_state
        for callback in list(self._listeners):
            callback(self._state)


class FileTreeStateStore:
    def __init__(self, initial: FileTreeState | None = None) -> None:
        self._state = initial or FileTreeState()
        self._listeners: set[Callable[[FileTreeState], None]] = set()

    @property
    def state(self) -> FileTreeState:
        return self._state

    def subscribe(self, callback: Callable[[FileTreeState], None]) -> None:
        self._listeners.add(callback)
        callback(self._state)

    def unsubscribe(self, callback: Callable[[FileTreeState], None]) -> None:
        self._listeners.discard(callback)

    def set_filter_query(self, value: str) -> None:
        self._update_state(filter_query=value)

    def set_current_listing_path(self, value: Path | None) -> None:
        self._update_state(current_listing_path=value)

    def set_last_selected_path(self, value: Path | None) -> None:
        self._update_state(last_selected_path=value)

    def clear_selection_history(self) -> None:
        self._update_state(selection_history={})

    def update_selection_history(self, directory: Path, selected: Path) -> None:
        history = dict(self._state.selection_history)
        history[directory] = selected
        self._update_state(selection_history=history)

    def _update_state(self, **changes: object) -> None:
        new_state = replace(self._state, **changes)
        if new_state == self._state:
            return
        self._state = new_state
        for callback in list(self._listeners):
            callback(self._state)


class TaskListStateStore:
    def __init__(self, initial: TaskListState | None = None) -> None:
        self._state = initial or TaskListState()
        self._listeners: set[Callable[[TaskListState], None]] = set()

    @property
    def state(self) -> TaskListState:
        return self._state

    def subscribe(self, callback: Callable[[TaskListState], None]) -> None:
        self._listeners.add(callback)
        callback(self._state)

    def unsubscribe(self, callback: Callable[[TaskListState], None]) -> None:
        self._listeners.discard(callback)

    def set_active_tag_filter(self, value: set[str]) -> None:
        self._update_state(active_tag_filter=frozenset(value))

    def set_highlighted_task_id(self, value: str | None) -> None:
        self._update_state(highlighted_task_id=value)

    def _update_state(self, **changes: object) -> None:
        new_state = replace(self._state, **changes)
        if new_state == self._state:
            return
        self._state = new_state
        for callback in list(self._listeners):
            callback(self._state)
