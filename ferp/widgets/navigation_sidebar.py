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
    DRIVE_ACCESS_CHECK_WORKER_NAME = "navigation_sidebar_drive_access_check"
    PATH_SCAN_WORKER_NAME = "navigation_sidebar_path_scan"

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
        self._option_sections: dict[str, str] = {}
        self._current_path: Path | None = None
        self._drive_state = drive_inventory.state
        self._known_place_entries: list[tuple[str, Path]] = (
            self._known_place_candidates()
        )
        self._pinned_place_entries: list[tuple[str, Path]] = []
        self._path_scan_request_id = 0
        self._pending_drive_check: Path | None = None
        self._background_scans_started = False

    def on_mount(self) -> None:
        self.border_title = "Quick Nav"
        self._state_store.subscribe(self._state_subscription)
        self._drive_inventory.subscribe(self._drive_subscription)
        self.refresh_items()
        self.call_after_refresh(self.refresh_path_entries)
        self.set_timer(
            0.1,
            self._start_background_drive_scan,
            name="nav-sidebar-start-drive-scan",
        )

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
        section = self._option_sections.get(option_id, "")
        drive_accessible = self._option_drive_access.get(option_id)
        if section == "drive":
            if drive_accessible is False:
                self._notify_drive_unavailable()
                self._ensure_drive_scan(force=True)
                return
            self._pending_drive_check = target
            self.run_worker(
                lambda drive=target: (
                    drive,
                    self._drive_inventory.probe_access(drive),
                ),
                name=self.DRIVE_ACCESS_CHECK_WORKER_NAME,
                thread=True,
            )
            return
        if drive_accessible is False:
            self._notify_drive_unavailable()
            self._ensure_drive_scan(force=True)
            return
        if not is_navigable_directory(target):
            if section == "pinned":
                remover = cast(
                    Callable[[Path], bool] | None,
                    getattr(self.app, "remove_pinned_entry", None),
                )
                if callable(remover):
                    remover(target)
                    self.refresh_path_entries()
            self.refresh_items()
            notify = getattr(self.app, "notify", None)
            if callable(notify):
                message = (
                    "Pinned folder no longer exists."
                    if section == "pinned"
                    else "Folder is not currently available."
                )
                notify(message)
            return
        self.post_message(NavigateRequest(target))

    @on(Worker.StateChanged)
    def _handle_worker_state(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.name == self.DRIVE_ACCESS_CHECK_WORKER_NAME:
            if worker.state != WorkerState.SUCCESS:
                self._pending_drive_check = None
                self._notify_drive_unavailable()
                return
            result = worker.result
            if (
                not isinstance(result, tuple)
                or len(result) != 2
                or not isinstance(result[0], Path)
                or not isinstance(result[1], bool)
            ):
                self._pending_drive_check = None
                return
            target, accessible = result
            if target != self._pending_drive_check:
                return
            self._pending_drive_check = None
            self._drive_inventory.set_drive_access(target, accessible)
            if not accessible:
                self._notify_drive_unavailable()
                return
            self.post_message(NavigateRequest(target))
            return
        if worker.name != self.DRIVE_SCAN_WORKER_NAME:
            if worker.name != self.PATH_SCAN_WORKER_NAME:
                return
            if worker.state != WorkerState.SUCCESS:
                return
            result = worker.result
            if not isinstance(result, tuple) or len(result) != 3:
                return
            request_id, known_places, pinned_places = result
            if request_id != self._path_scan_request_id:
                return
            if not isinstance(known_places, list) or not isinstance(
                pinned_places, list
            ):
                return
            self._known_place_entries = cast(list[tuple[str, Path]], known_places)
            self._pinned_place_entries = cast(list[tuple[str, Path]], pinned_places)
            self.refresh_items()
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
        option_sections: dict[str, str] = {}
        highlight_id: str | None = None
        best_depth = -1
        option_index = 0

        def add_section(
            title: str,
            items: list[tuple[str, Path]],
            *,
            section: str,
        ) -> None:
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
                option_sections[option_id] = section
                depth = self._match_depth(path)
                if depth > best_depth:
                    best_depth = depth
                    highlight_id = option_id

        add_section("Places", self._known_places(), section="place")
        add_section("Pinned", self._pinned_places(), section="pinned")

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
                option_sections[option_id] = "drive"
                if drive.accessible:
                    depth = self._match_depth(drive.path)
                    if depth > best_depth:
                        best_depth = depth
                        highlight_id = option_id
        else:
            content.append(Option("No drives detected.", disabled=True))

        self._option_paths = option_paths
        self._option_drive_access = option_drive_access
        self._option_sections = option_sections
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
        if self._background_scans_started:
            self._ensure_drive_scan()

    def _start_background_drive_scan(self) -> None:
        self._background_scans_started = True
        self._ensure_drive_scan()

    def refresh_path_entries(self) -> None:
        self._path_scan_request_id += 1
        request_id = self._path_scan_request_id
        pinned_getter = cast(
            Callable[[], list[Path]] | None,
            getattr(self.app, "pinned_paths", None),
        )
        pinned_paths = pinned_getter() if callable(pinned_getter) else []
        self.run_worker(
            lambda rid=request_id, paths=tuple(pinned_paths): (
                rid,
                self._resolve_entries(self._known_place_candidates()),
                self._resolve_entries(
                    [(path.name or str(path), path) for path in paths]
                ),
            ),
            name=self.PATH_SCAN_WORKER_NAME,
            thread=True,
        )

    def _handle_drive_inventory_update(self, state: DriveInventoryState) -> None:
        self._drive_state = state
        self.refresh_items()

    def _notify_drive_unavailable(self) -> None:
        notify = getattr(self.app, "notify", None)
        if callable(notify):
            notify(
                "Drive is mounted but not currently accessible. Connect to VPN and try again."
            )

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
        )
        return True

    def _known_places(self) -> list[tuple[str, Path]]:
        return list(self._known_place_entries)

    def _pinned_places(self) -> list[tuple[str, Path]]:
        return list(self._pinned_place_entries)

    @staticmethod
    def _known_place_candidates() -> list[tuple[str, Path]]:
        home = Path.home()
        return [
            ("Home", home),
            ("Desktop", home / "Desktop"),
            ("Documents", home / "Documents"),
            ("Downloads", home / "Downloads"),
        ]

    @staticmethod
    def _resolve_entries(
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
