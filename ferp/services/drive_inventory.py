from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, cast

import psutil

from ferp.core.settings_store import SettingsStore


@dataclass(frozen=True, slots=True)
class DriveStatus:
    label: str
    path: Path
    accessible: bool


@dataclass(frozen=True, slots=True)
class DriveInventoryState:
    entries: tuple[DriveStatus, ...] = ()
    scanning: bool = False
    loaded: bool = False
    last_checked_at: float = 0.0


class DriveInventoryService:
    """Cache and refresh mounted-drive inventory outside the sidebar widget."""

    _MACOS_EXCLUDED_FSTYPES = {
        "autofs",
        "devfs",
        "devtmpfs",
        "tmpfs",
    }
    _LINUX_EXCLUDED_FSTYPES = {
        "autofs",
        "devfs",
        "devtmpfs",
        "tmpfs",
        "proc",
        "sysfs",
        "cgroup2",
        "debugfs",
        "tracefs",
        "fusectl",
        "configfs",
        "securityfs",
        "pstore",
        "bpf",
        "hugetlbfs",
        "mqueue",
        "devpts",
        "binfmt_misc",
    }

    def __init__(
        self,
        *,
        settings: dict[str, Any] | None = None,
        settings_store: SettingsStore | None = None,
        ttl_seconds: float = 60.0,
    ) -> None:
        self._settings = settings
        self._settings_store = settings_store
        self._ttl_seconds = ttl_seconds
        self._listeners: set[Callable[[DriveInventoryState], None]] = set()
        self._state = self._load_state(settings or {})

    @property
    def state(self) -> DriveInventoryState:
        return self._state

    def subscribe(self, callback: Callable[[DriveInventoryState], None]) -> None:
        self._listeners.add(callback)
        callback(self._state)

    def unsubscribe(self, callback: Callable[[DriveInventoryState], None]) -> None:
        self._listeners.discard(callback)

    def request_refresh(self, *, force: bool = False) -> bool:
        if self._state.scanning:
            return False
        if not force and self._state.loaded and not self.is_stale():
            return False
        self._update_state(scanning=True)
        return True

    def is_known_drive_path(self, path: Path) -> bool:
        target = str(path).casefold() if os.name == "nt" else str(path)
        for entry in self._state.entries:
            candidate = (
                str(entry.path).casefold() if os.name == "nt" else str(entry.path)
            )
            if candidate == target:
                return True
        return False

    def is_stale(self) -> bool:
        if not self._state.loaded:
            return True
        if self._state.last_checked_at <= 0:
            return True
        return (time.time() - self._state.last_checked_at) >= self._ttl_seconds

    def complete_scan(self, entries: list[DriveStatus]) -> None:
        checked_at = time.time()
        normalized = tuple(sorted(entries, key=lambda item: item.label.casefold()))
        self._update_state(
            entries=normalized,
            scanning=False,
            loaded=True,
            last_checked_at=checked_at,
        )
        self._persist()

    def set_drive_access(self, path: Path, accessible: bool) -> bool:
        target = str(path).casefold() if os.name == "nt" else str(path)
        updated = False
        entries: list[DriveStatus] = []
        for entry in self._state.entries:
            candidate = (
                str(entry.path).casefold() if os.name == "nt" else str(entry.path)
            )
            if candidate == target:
                if entry.accessible != accessible:
                    updated = True
                    entries.append(
                        DriveStatus(
                            label=entry.label,
                            path=entry.path,
                            accessible=accessible,
                        )
                    )
                else:
                    entries.append(entry)
            else:
                entries.append(entry)
        if not updated:
            return False
        self._update_state(entries=tuple(entries))
        self._persist()
        return True

    def fail_scan(self) -> None:
        self._update_state(
            scanning=False,
            loaded=True,
            last_checked_at=time.time(),
        )

    def scan_drives(self) -> list[DriveStatus]:
        entries: list[DriveStatus] = []
        seen: set[str] = set()
        try:
            partitions = psutil.disk_partitions(all=self._partition_scan_includes_all())
        except Exception:
            partitions = []

        for partition in partitions:
            mountpoint = str(partition.mountpoint or "").strip()
            if not mountpoint:
                continue
            if not self._should_include_partition(partition):
                continue
            key = mountpoint.casefold() if os.name == "nt" else mountpoint
            if key in seen:
                continue
            seen.add(key)
            path = Path(mountpoint)
            accessible = True if sys.platform == "win32" else self._probe_access(path)
            entries.append(
                DriveStatus(
                    label=self._drive_label(mountpoint),
                    path=path,
                    accessible=accessible,
                )
            )
        return entries

    @staticmethod
    def _partition_scan_includes_all() -> bool:
        return sys.platform == "win32"

    @staticmethod
    def _drive_label(mountpoint: str) -> str:
        if os.name == "nt":
            return mountpoint
        if mountpoint == "/":
            return "/"
        return Path(mountpoint).name or mountpoint

    @staticmethod
    def probe_access(path: Path) -> bool:
        return DriveInventoryService._probe_access(path)

    @staticmethod
    def _probe_access(path: Path) -> bool:
        if sys.platform == "win32":
            if not str(path):
                return False
            try:
                result = subprocess.run(
                    ["cmd", "/d", "/c", "exit", "0"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.5,
                    check=False,
                    cwd=path,
                )
            except (OSError, subprocess.SubprocessError):
                return False
            return result.returncode == 0
        try:
            with os.scandir(path) as iterator:
                next(iterator, None)
            return True
        except OSError:
            return False

    @classmethod
    def _should_include_partition(cls, partition: object) -> bool:
        if sys.platform == "win32":
            return cls._should_include_windows_mount_point(partition)
        if sys.platform == "darwin":
            return cls._should_include_macos_mount_point(partition)
        return cls._should_include_linux_mount_point(partition)

    @classmethod
    def _should_include_windows_mount_point(cls, partition: object) -> bool:
        mountpoint = str(getattr(partition, "mountpoint", "") or "").strip()
        if not mountpoint:
            return False
        if len(mountpoint) < 2 or mountpoint[1] != ":":
            return False
        if not mountpoint[0].isalpha():
            return False
        return True

    @classmethod
    def _should_include_macos_mount_point(cls, partition: object) -> bool:
        mountpoint = str(getattr(partition, "mountpoint", "") or "").strip()
        fstype = str(getattr(partition, "fstype", "") or "").strip().lower()
        if not mountpoint:
            return False
        if fstype in cls._MACOS_EXCLUDED_FSTYPES:
            return False
        if mountpoint.startswith("/System/Volumes/"):
            return False
        if mountpoint.startswith("/System/") or mountpoint.startswith("/dev/"):
            return False
        if mountpoint.startswith("/private/var/") or mountpoint.startswith(
            "/private/tmp/"
        ):
            return False
        return True

    @classmethod
    def _should_include_linux_mount_point(cls, partition: object) -> bool:
        mountpoint = str(getattr(partition, "mountpoint", "") or "").strip()
        fstype = str(getattr(partition, "fstype", "") or "").strip().lower()
        if not mountpoint:
            return False
        if fstype in cls._LINUX_EXCLUDED_FSTYPES:
            return False
        return not mountpoint.startswith(
            (
                "/dev",
                "/proc",
                "/sys",
                "/run",
                "/boot",
                "/mnt/wslg",
                "/mnt/wsl",
            )
        )

    def _load_state(self, settings: dict[str, Any]) -> DriveInventoryState:
        raw = settings.get("driveInventory", {})
        if not isinstance(raw, dict):
            return DriveInventoryState()
        entries_data = raw.get("entries")
        loaded_entries: list[DriveStatus] = []
        if isinstance(entries_data, list):
            for item in entries_data:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip()
                path_raw = str(item.get("path") or "").strip()
                if not label or not path_raw:
                    continue
                try:
                    path = Path(path_raw)
                except (TypeError, ValueError):
                    continue
                loaded_entries.append(
                    DriveStatus(
                        label=label,
                        path=path,
                        accessible=bool(item.get("accessible", False)),
                    )
                )
        last_checked_raw = raw.get("lastCheckedAt", 0.0)
        try:
            last_checked_at = float(last_checked_raw)
        except (TypeError, ValueError):
            last_checked_at = 0.0
        loaded = bool(loaded_entries or last_checked_at)
        return DriveInventoryState(
            entries=tuple(loaded_entries),
            scanning=False,
            loaded=loaded,
            last_checked_at=last_checked_at,
        )

    def _persist(self) -> None:
        if self._settings is None or self._settings_store is None:
            return
        self._settings_store.update_drive_inventory(
            self._settings,
            entries=[
                {
                    "label": entry.label,
                    "path": str(entry.path),
                    "accessible": entry.accessible,
                }
                for entry in self._state.entries
            ],
            last_checked_at=self._state.last_checked_at,
        )

    def _update_state(self, **changes: object) -> None:
        state = self._state
        last_checked_value = changes.get("last_checked_at", state.last_checked_at)
        if isinstance(last_checked_value, (int, float)):
            last_checked_at = float(last_checked_value)
        else:
            last_checked_at = state.last_checked_at
        next_state = DriveInventoryState(
            entries=cast(
                tuple[DriveStatus, ...], changes.get("entries", state.entries)
            ),
            scanning=bool(changes.get("scanning", state.scanning)),
            loaded=bool(changes.get("loaded", state.loaded)),
            last_checked_at=last_checked_at,
        )
        if next_state == self._state:
            return
        self._state = next_state
        for callback in list(self._listeners):
            callback(self._state)
