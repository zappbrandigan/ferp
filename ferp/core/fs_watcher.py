from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from textual.timer import Timer
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers.api import ObservedWatch

if TYPE_CHECKING:
    from watchdog.observers import Observer as WatchdogObserver
else:
    from watchdog.observers import Observer as WatchdogObserver


@dataclass(frozen=True)
class SnapshotResult:
    directory: Path
    exists: bool
    signature: tuple[str, ...] | None


class DirectoryChangeHandler(FileSystemEventHandler):
    """Watchdog handler that forwards filesystem activity to the UI thread."""

    def __init__(self, notify_change: Callable[[], None]) -> None:
        self._notify_change = notify_change

    def on_any_event(self, event: FileSystemEvent | None = None) -> None:  # type: ignore[override]
        if event is None:
            self._notify_change()
            return
        if event.event_type in {"created", "deleted", "moved"}:
            self._notify_change()


class FileTreeWatcher:
    """Manages filesystem watching and debounced refreshes for the FileTree."""

    def __init__(
        self,
        *,
        call_from_thread: Callable[[Callable[[], None]], object | None],
        refresh_callback: Callable[[], None],
        missing_callback: Callable[[Path], None] | None = None,
        snapshot_func: Callable[[Path], tuple[str, ...]],
        worker_factory: Callable[[Callable[[], SnapshotResult]], object],
        timer_factory: Callable[[float, Callable[[], None]], Timer],
        debounce_seconds: float = 2.0,
    ) -> None:
        self._call_from_thread = call_from_thread
        self._refresh_callback = refresh_callback
        self._missing_callback = missing_callback
        self._snapshot_func = snapshot_func
        self._worker_factory = worker_factory
        self._timer_factory = timer_factory
        self._debounce_seconds = debounce_seconds

        self._observer: WatchdogObserver | None = None  # type: ignore
        self._watch: ObservedWatch | None = None
        self._handler: DirectoryChangeHandler | None = None
        self._current_directory: Path | None = None
        self._refresh_timer: Timer | None = None
        self._last_snapshot: tuple[str, ...] | None = None
        self._snapshot_inflight = False
        self._pending_refresh = False
        self._notify_lock = threading.Lock()
        self._notify_pending = False

    def start(self, directory: Path) -> None:
        """Ensure the watcher is running and observing the provided directory."""
        self._current_directory = directory
        self._ensure_observer()
        self._restart_watch(directory)

    def stop(self) -> None:
        """Tear down the watch and stop the observer."""
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None

        observer = self._observer
        if observer is not None:
            if self._watch is not None:
                try:
                    observer.unschedule(self._watch)
                except Exception:
                    pass
                self._watch = None
            observer.stop()
            observer.join(timeout=1)

        self._observer = None
        self._handler = None

    def update_snapshot(
        self,
        directory: Path,
        signature: tuple[str, ...] | None = None,
    ) -> None:
        """Record the latest directory signature to prevent redundant refreshes."""
        if not directory.exists():
            self._last_snapshot = None
            return
        self._last_snapshot = (
            signature if signature is not None else self._snapshot_func(directory)
        )
        self._current_directory = directory

    def _ensure_observer(self) -> None:
        if self._observer is not None:
            return

        handler = DirectoryChangeHandler(
            notify_change=self._notify_from_thread,
        )
        observer = WatchdogObserver()
        observer.daemon = True
        observer.start()

        self._handler = handler
        self._observer = observer

    def _restart_watch(self, directory: Path) -> None:
        observer = self._observer
        handler = self._handler
        if observer is None or handler is None:
            return

        if self._watch is not None:
            try:
                observer.unschedule(self._watch)
            except Exception:
                pass
            self._watch = None

        if not directory.exists():
            return

        try:
            self._watch = observer.schedule(handler, str(directory), recursive=False)
        except Exception:
            self._watch = None

    def _queue_refresh(self) -> None:
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        self._refresh_timer = self._timer_factory(
            self._debounce_seconds, self._complete_refresh
        )

    def _complete_refresh(self) -> None:
        self._refresh_timer = None
        if self._snapshot_inflight:
            self._pending_refresh = True
            return

        directory = self._current_directory
        if directory is None:
            return

        self._snapshot_inflight = True
        self._worker_factory(lambda target=directory: self._snapshot_worker(target))

    def _snapshot_worker(self, target: Path) -> SnapshotResult:
        exists = target.exists()
        signature: tuple[str, ...] | None
        if not exists:
            signature = None
        else:
            try:
                signature = self._snapshot_func(target)
            except Exception:
                signature = tuple()
        return SnapshotResult(target, exists, signature)

    def handle_snapshot_result(self, result: SnapshotResult) -> None:
        self._snapshot_inflight = False

        if result.directory != self._current_directory:
            if self._pending_refresh:
                self._pending_refresh = False
                self._queue_refresh()
            return

        if not result.exists:
            if self._missing_callback is not None:
                self._missing_callback(result.directory)
        else:
            if result.signature != self._last_snapshot:
                self._refresh_callback()

        if self._pending_refresh:
            self._pending_refresh = False
            self._queue_refresh()

    def handle_snapshot_error(self) -> None:
        self._snapshot_inflight = False
        if self._pending_refresh:
            self._pending_refresh = False
            self._queue_refresh()

    def _notify_from_thread(self) -> None:
        with self._notify_lock:
            if self._notify_pending:
                return
            self._notify_pending = True

        def _queue_and_release() -> None:
            try:
                self._queue_refresh()
            finally:
                with self._notify_lock:
                    self._notify_pending = False

        try:
            self._call_from_thread(_queue_and_release)
        except Exception:
            with self._notify_lock:
                self._notify_pending = False
            raise
