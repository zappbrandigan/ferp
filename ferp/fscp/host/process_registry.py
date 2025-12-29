from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Iterable

from ferp.fscp.protocol.state import HostState


_TERMINAL_STATES = {
    HostState.TERMINATED,
    HostState.ERR_PROTOCOL,
    HostState.ERR_TRANSPORT,
}


@dataclass(frozen=True)
class ProcessMetadata:
    script_name: str
    script_id: str | None
    target_path: Path


@dataclass
class ProcessRecord:
    handle: str
    pid: int | None
    metadata: ProcessMetadata
    state: HostState
    start_time: float
    exit_code: int | None = None
    end_time: float | None = None
    termination_mode: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_STATES


class ProcessRegistry:
    """Tracks processes spawned by the FSCP host."""

    def __init__(self) -> None:
        self._records: dict[str, ProcessRecord] = {}
        self._lock = Lock()
        self._counter = itertools.count(1)

    def register(self, metadata: ProcessMetadata, *, pid: int | None, state: HostState) -> ProcessRecord:
        handle = f"proc-{next(self._counter)}"
        record = ProcessRecord(
            handle=handle,
            pid=pid,
            metadata=metadata,
            state=state,
            start_time=time.time(),
        )
        with self._lock:
            self._records[handle] = record
        return record

    def update_state(self, handle: str, state: HostState) -> None:
        with self._lock:
            record = self._records.get(handle)
            if record is None:
                return
            record.state = state
            if state in _TERMINAL_STATES:
                record.end_time = record.end_time or time.time()

    def record_exit(self, handle: str, exit_code: int | None, *, termination_mode: str | None) -> None:
        with self._lock:
            record = self._records.get(handle)
            if record is None:
                return
            record.exit_code = exit_code
            if termination_mode:
                record.termination_mode = termination_mode
            record.end_time = record.end_time or time.time()
            if record.state not in _TERMINAL_STATES:
                record.state = HostState.TERMINATED

    def list_all(self) -> list[ProcessRecord]:
        with self._lock:
            return [self._clone(record) for record in self._records.values()]

    def list_active(self) -> list[ProcessRecord]:
        with self._lock:
            return [self._clone(record) for record in self._records.values() if not record.is_terminal]

    def prune_finished(self) -> list[ProcessRecord]:
        with self._lock:
            finished = [handle for handle, record in self._records.items() if record.is_terminal]
            removed = [self._records.pop(handle) for handle in finished]
        return [self._clone(record) for record in removed]

    def _clone(self, record: ProcessRecord) -> ProcessRecord:
        return ProcessRecord(
            handle=record.handle,
            pid=record.pid,
            metadata=record.metadata,
            state=record.state,
            start_time=record.start_time,
            exit_code=record.exit_code,
            end_time=record.end_time,
            termination_mode=record.termination_mode,
        )

__all__ = [
    "ProcessMetadata",
    "ProcessRecord",
    "ProcessRegistry",
]
