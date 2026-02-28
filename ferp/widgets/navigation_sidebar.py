from __future__ import annotations

from pathlib import Path
from typing import Callable, cast

from textual import on
from textual.binding import Binding
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from ferp.core.messages import NavigateRequest
from ferp.core.path_navigation import is_navigable_directory
from ferp.core.state import AppState, AppStateStore
from ferp.services.drive_inventory import (
    DriveInventoryService,
    DriveInventoryState,
    DriveStatus,
)


class NavigationSidebar(OptionList):
    """Quick-jump sidebar for common locations, pinned items, and drives."""

    LABEL_MAX_WIDTH = 20
    DRIVE_SCAN_WORKER_NAME = "navigation_sidebar_drive_scan"

    BINDINGS = [
        Binding("g", "first", "Top", show=False),
        Binding("G", "last", "Bottom", key_display="G", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("r", "refresh_drives", "Refresh drives", show=False),
    ]

    def __init__(
        self,
        *,
        state_store: AppStateStore,
        drive_inventory: DriveInventoryService,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._state_store = state_store
        self._drive_inventory = drive_inventory
        self._state_subscription = self._handle_state_update
        self._drive_subscription = self._handle_drive_inventory_update
        self._option_paths: dict[str, Path] = {}
        self._option_drive_access: dict[str, bool] = {}
        self._current_path: Path | None = None
        self._drive_state = drive_inventory.state

    def on_mount(self) -> None:
        self.border_title = "Quick Nav"
        self._state_store.subscribe(self._state_subscription)
        self._drive_inventory.subscribe(self._drive_subscription)
        self.refresh_items()
        self._ensure_drive_scan()

    def on_unmount(self) -> None:
        self._state_store.unsubscribe(self._state_subscription)
        self._drive_inventory.unsubscribe(self._drive_subscription)

    @on(OptionList.OptionSelected)
    def _handle_selection(self, event: OptionList.OptionSelected) -> None:
        option_id = event.option_id
        if not option_id:
            return
        target = self._option_paths.get(option_id)
        if target is None:
            return
        drive_accessible = self._option_drive_access.get(option_id)
        if drive_accessible is False:
            notify = getattr(self.app, "notify", None)
            if callable(notify):
                notify(
                    "Drive is mounted but not currently accessible. Connect to VPN and try again."
                )
            self._ensure_drive_scan(force=True)
            return
        if drive_accessible is True:
            self.post_message(NavigateRequest(target))
            return
        if not is_navigable_directory(target):
            pruner = cast(
                Callable[[], int] | None,
                getattr(self.app, "prune_stale_pinned_entries", None),
            )
            removed = pruner() if callable(pruner) else 0
            self.refresh_items()
            notify = getattr(self.app, "notify", None)
            if callable(notify):
                message = (
                    "Pinned folder no longer exists."
                    if removed <= 1
                    else f"Removed {removed} stale pinned folders."
                )
                notify(message)
            return
        self.post_message(NavigateRequest(target))

    @on(Worker.StateChanged)
    def _handle_worker_state(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.name != self.DRIVE_SCAN_WORKER_NAME:
            return
        if worker.state == WorkerState.SUCCESS:
            result = cast(list[DriveStatus], worker.result or [])
            self._drive_inventory.complete_scan(result)
            return
        if worker.state in {WorkerState.ERROR, WorkerState.CANCELLED}:
            self._drive_inventory.fail_scan()

    def refresh_items(self) -> None:
        content: list[Option | None] = []
        option_paths: dict[str, Path] = {}
        option_drive_access: dict[str, bool] = {}
        highlight_id: str | None = None
        best_depth = -1
        option_index = 0

        def add_section(title: str, items: list[tuple[str, Path]]) -> None:
            nonlocal option_index, highlight_id, best_depth
            if not items:
                return
            if content:
                content.append(None)
            content.append(Option(f"[b]{title}[/b]", disabled=True))
            for label, path in items:
                option_id = f"nav_{option_index}"
                option_index += 1
                content.append(Option(self._truncate_label(label), id=option_id))
                option_paths[option_id] = path
                depth = self._match_depth(path)
                if depth > best_depth:
                    best_depth = depth
                    highlight_id = option_id

        add_section("Places", self._known_places())
        add_section("Pinned", self._pinned_places())

        if content:
            content.append(None)
        content.append(Option("[b]Drives[/b]", disabled=True))
        if not self._drive_state.loaded and self._drive_state.scanning:
            content.append(Option("Scanning drives...", disabled=True))
        elif self._drive_state.entries:
            for drive in self._drive_state.entries:
                option_id = f"nav_{option_index}"
                option_index += 1
                label = self._truncate_label(drive.label)
                if not drive.accessible:
                    offline = self._truncate_label(f"{drive.label} (offline)")
                    label = f"[dim]{offline}[/dim]"
                content.append(Option(label, id=option_id))
                option_paths[option_id] = drive.path
                option_drive_access[option_id] = drive.accessible
                if drive.accessible:
                    depth = self._match_depth(drive.path)
                    if depth > best_depth:
                        best_depth = depth
                        highlight_id = option_id
        else:
            content.append(Option("No drives detected.", disabled=True))

        self._option_paths = option_paths
        self._option_drive_access = option_drive_access
        self.set_options(content)

        if highlight_id is None:
            self.highlighted = None
            return
        try:
            self.highlighted = self.get_option_index(highlight_id)
        except Exception:
            self.highlighted = None

    def _handle_state_update(self, state: AppState) -> None:
        new_path = Path(state.current_path) if state.current_path else None
        if new_path == self._current_path:
            return
        self._current_path = new_path
        self.refresh_items()
        self._ensure_drive_scan()

    def _handle_drive_inventory_update(self, state: DriveInventoryState) -> None:
        self._drive_state = state
        self.refresh_items()

    def action_refresh_drives(self) -> None:
        if self._ensure_drive_scan(force=True):
            notify = getattr(self.app, "notify", None)
            if callable(notify):
                notify("Refreshing drives...")

    def _ensure_drive_scan(self, *, force: bool = False) -> bool:
        if not self._drive_inventory.request_refresh(force=force):
            return False
        self.run_worker(
            self._drive_inventory.scan_drives,
            name=self.DRIVE_SCAN_WORKER_NAME,
            thread=True,
            exclusive=True,
        )
        return True

    def _known_places(self) -> list[tuple[str, Path]]:
        home = Path.home()
        candidates = [
            ("Home", home),
            ("Desktop", home / "Desktop"),
            ("Documents", home / "Documents"),
            ("Downloads", home / "Downloads"),
        ]
        return self._normalize_entries(candidates)

    def _pinned_places(self) -> list[tuple[str, Path]]:
        pinned_getter = cast(
            Callable[[], list[Path]] | None,
            getattr(self.app, "pinned_paths", None),
        )
        if not callable(pinned_getter):
            return []
        candidates: list[tuple[str, Path]] = []
        for path in pinned_getter():
            if not is_navigable_directory(path):
                continue
            label = path.name or str(path)
            candidates.append((label, path))
        return self._normalize_entries(candidates)

    def _normalize_entries(
        self,
        entries: list[tuple[str, Path]],
    ) -> list[tuple[str, Path]]:
        normalized: list[tuple[str, Path]] = []
        seen: set[str] = set()
        for label, path in entries:
            try:
                resolved = path.expanduser().resolve()
            except OSError:
                continue
            if not is_navigable_directory(resolved):
                continue
            key = str(resolved)
            if key in seen:
                continue
            seen.add(key)
            normalized.append((label, resolved))
        return normalized

    def _match_depth(self, candidate: Path) -> int:
        current = self._current_path
        if current is None:
            return -1
        try:
            current.relative_to(candidate)
        except ValueError:
            return -1
        return len(candidate.parts)

    @classmethod
    def _truncate_label(cls, label: str) -> str:
        if len(label) <= cls.LABEL_MAX_WIDTH:
            return label
        if cls.LABEL_MAX_WIDTH <= 3:
            return label[: cls.LABEL_MAX_WIDTH]
        return f"{label[: cls.LABEL_MAX_WIDTH - 3]}..."
