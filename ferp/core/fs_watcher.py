from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from textual.timer import Timer


@dataclass(frozen=True)
class SnapshotResult:
    directory: Path
    exists: bool
    signature: frozenset[str] | None


class FileTreeWatcher:
    """Long-running polling watcher for the current directory."""

    def __init__(
        self,
        *,
        call_from_thread: Callable[[Callable[[], None]], object | None],
        refresh_callback: Callable[[], None],
        missing_callback: Callable[[Path], None] | None = None,
        snapshot_func: Callable[[Path], frozenset[str]],
        worker_factory: Callable[[Callable[[], SnapshotResult]], object],
        timer_factory: Callable[[float, Callable[[], None]], Timer],
        debounce_seconds: float = 2.0,
    ) -> None:
        self._call_from_thread = call_from_thread
        self._refresh_callback = refresh_callback
        self._missing_callback = missing_callback
        self._snapshot_func = snapshot_func
        self._poll_seconds = debounce_seconds

        self._current_directory: Path | None = None
        self._last_snapshot: frozenset[str] | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None

        # Retained for constructor compatibility with existing call sites.
        self._worker_factory = worker_factory
        self._timer_factory = timer_factory

    def start(self, directory: Path) -> None:
        """Start polling the provided directory."""
        with self._state_lock:
            self._current_directory = directory
            self._running = True
        self._ensure_thread()

    def stop(self) -> None:
        """Pause polling without tearing down the background thread."""
        with self._state_lock:
            self._running = False
            self._current_directory = None

    def update_snapshot(
        self,
        directory: Path,
        signature: frozenset[str] | None = None,
    ) -> None:
        """Update the baseline snapshot from the latest rendered listing."""
        with self._state_lock:
            self._current_directory = directory
            if signature is not None:
                self._last_snapshot = signature
                return
        try:
            snapshot = self._snapshot_func(directory)
        except Exception:
            snapshot = None
        with self._state_lock:
            if self._current_directory == directory:
                self._last_snapshot = snapshot

    def handle_snapshot_result(self, result: SnapshotResult) -> None:
        callback = self._apply_snapshot_result(result)
        if callback is not None:
            callback()

    def handle_snapshot_error(self) -> None:
        return None

    def _notify_from_thread(self) -> None:
        self._schedule_poll_once()

    def _ensure_thread(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="ferp-file-tree-watcher",
            daemon=True,
        )
        self._thread.start()

    def _poll_loop(self) -> None:
        while not self._stop_event.wait(self._poll_seconds):
            self._poll_once()

    def _poll_once(self) -> None:
        with self._state_lock:
            if not self._running:
                return
            directory = self._current_directory
        if directory is None:
            return

        exists = directory.exists()
        signature: frozenset[str] | None
        if not exists:
            signature = None
        else:
            try:
                signature = self._snapshot_func(directory)
            except Exception:
                signature = frozenset()

        callback = self._apply_snapshot_result(
            SnapshotResult(directory=directory, exists=exists, signature=signature)
        )
        if callback is not None:
            self._call_from_thread(callback)

    def _apply_snapshot_result(
        self,
        result: SnapshotResult,
    ) -> Callable[[], None] | None:
        with self._state_lock:
            if result.directory != self._current_directory:
                return None

            if not result.exists:
                if self._last_snapshot is None or self._missing_callback is None:
                    return None
                missing_callback = self._missing_callback
                self._last_snapshot = None
                return lambda target=result.directory, callback=missing_callback: (
                    callback(target)
                )

            if result.signature == self._last_snapshot:
                return None

            self._last_snapshot = result.signature
            return self._refresh_callback

    def _schedule_poll_once(self) -> None:
        self._call_from_thread(self._poll_once)
