from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SortMode = Literal["name", "natural", "extension", "modified", "created", "size"]

SORT_MODE_LABELS: dict[SortMode, str] = {
    "name": "Name",
    "natural": "Natural",
    "extension": "Extension",
    "modified": "Modified",
    "created": "Created",
    "size": "Size",
}


@dataclass(frozen=True)
class DirectoryListingResult:
    path: Path
    token: int
    entries: list[FileListingEntry]
    signature: frozenset[str] = frozenset()
    error: str | None = None


@dataclass(frozen=True)
class FileListingEntry:
    path: Path
    name: str
    display_name: str
    is_dir: bool


def normalize_sort_mode(value: object) -> SortMode:
    text = str(value or "").strip().lower()
    if text in SORT_MODE_LABELS:
        return text  # type: ignore[return-value]
    return "name"


def _natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts = re.split(r"(\d+)", value)
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in parts
        if part
    )


def _safe_stat(entry: os.DirEntry[str]) -> os.stat_result | None:
    try:
        return entry.stat(follow_symlinks=False)
    except OSError:
        return None


def _entry_sort_key(
    entry: os.DirEntry[str],
    sort_by: SortMode,
    *,
    is_dir: bool | None = None,
) -> tuple[object, ...]:
    path = Path(entry.path)
    name = entry.name
    if is_dir is None:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False

    if sort_by == "name":
        underscore_dir_rank = 0 if is_dir and name.startswith("_") else 1
        return (underscore_dir_rank, name.casefold())

    if sort_by == "natural":
        return (_natural_key(name),)

    if sort_by == "extension":
        suffix = "" if is_dir else path.suffix.lstrip(".").casefold()
        return (suffix, name.casefold())

    if sort_by in {"modified", "created", "size"}:
        stat_result = _safe_stat(entry)
        if stat_result is None:
            metric = float("-inf")
        elif sort_by == "modified":
            metric = stat_result.st_mtime
        elif sort_by == "created":
            metric = stat_result.st_ctime
        else:
            metric = float(stat_result.st_size)
        return (metric, name.casefold())

    return (name.casefold(),)


def _sort_key(entry: os.DirEntry[str]) -> tuple[object, ...]:
    return _entry_sort_key(entry, "name")


def collect_directory_listing(
    directory: Path,
    token: int,
    *,
    hide_filtered_entries: bool = True,
    sort_by: SortMode = "name",
    sort_descending: bool = False,
) -> DirectoryListingResult:
    if _should_preflight_windows_remote_path(directory):
        if not _probe_windows_directory_access(directory):
            return DirectoryListingResult(
                directory,
                token,
                [],
                error="Drive is not currently accessible.",
            )
    try:
        with os.scandir(directory) as scan:
            filter_windows_home = _precompute_windows_home_filter(
                directory,
                hide_filtered_entries=hide_filtered_entries,
            )
            visible: list[tuple[os.DirEntry[str], bool]] = []
            for entry in scan:
                if not is_entry_visible(
                    entry.name,
                    directory,
                    hide_filtered_entries=hide_filtered_entries,
                    filter_windows_home=filter_windows_home,
                ):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    is_dir = False
                visible.append((entry, is_dir))
            mode = normalize_sort_mode(sort_by)
            if mode == "name":
                entries = sorted(
                    visible,
                    key=lambda item: (
                        0 if item[1] and item[0].name.startswith("_") else 1,
                        item[0].name.casefold(),
                    ),
                    reverse=sort_descending,
                )
            else:
                entries = sorted(
                    visible,
                    key=lambda item: _entry_sort_key(item[0], mode, is_dir=item[1]),
                    reverse=sort_descending,
                )
    except OSError as exc:
        return DirectoryListingResult(directory, token, [], error=str(exc))

    rows: list[FileListingEntry] = []
    for entry, is_dir in entries:
        listing_entry = _build_listing_entry(entry, is_dir=is_dir)
        if listing_entry is not None:
            rows.append(listing_entry)

    return DirectoryListingResult(
        directory,
        token,
        rows,
        build_listing_signature(rows),
    )


def snapshot_directory(
    path: Path,
    *,
    hide_filtered_entries: bool = True,
) -> tuple[str, ...]:
    try:
        with os.scandir(path) as scan:
            filter_windows_home = _precompute_windows_home_filter(
                path,
                hide_filtered_entries=hide_filtered_entries,
            )
            entries: list[tuple[os.DirEntry[str], bool]] = []
            for entry in scan:
                if not is_entry_visible(
                    entry.name,
                    path,
                    hide_filtered_entries=hide_filtered_entries,
                    filter_windows_home=filter_windows_home,
                ):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                entries.append((entry, is_dir))
    except OSError:
        return tuple()

    mode = normalize_sort_mode("name")
    entries = sorted(
        entries,
        key=lambda item: _entry_sort_key(item[0], mode, is_dir=item[1]),
    )

    signatures: list[str] = []
    for entry, is_dir in entries:
        signature = f"{entry.name}:{int(is_dir)}"
        signatures.append(signature)
    return tuple(signatures)


def build_listing_signature(entries: list[FileListingEntry]) -> frozenset[str]:
    return frozenset(entry.name for entry in entries)


def poll_directory_names(
    path: Path,
    *,
    hide_filtered_entries: bool = True,
) -> frozenset[str]:
    names: set[str] = set()
    with os.scandir(path) as scan:
        filter_windows_home = _precompute_windows_home_filter(
            path,
            hide_filtered_entries=hide_filtered_entries,
        )
        for entry in scan:
            if not is_entry_visible(
                entry.name,
                path,
                hide_filtered_entries=hide_filtered_entries,
                filter_windows_home=filter_windows_home,
            ):
                continue
            names.add(entry.name)
    return frozenset(names)


def _build_listing_entry(
    entry: os.DirEntry[str],
    *,
    is_dir: bool | None = None,
) -> FileListingEntry | None:
    entry_path = Path(entry.path)
    if is_dir is None:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            return None
    name = entry.name
    display_name = f"{name}/" if is_dir else name
    return FileListingEntry(
        path=entry_path,
        name=name,
        display_name=display_name,
        is_dir=is_dir,
    )


def is_entry_visible(
    entry: Path | str,
    directory: Path,
    *,
    hide_filtered_entries: bool = True,
    filter_windows_home: bool | None = None,
) -> bool:
    if not hide_filtered_entries:
        return True
    return not _should_skip_entry(
        entry,
        directory,
        filter_windows_home=filter_windows_home,
    )


def _should_skip_entry(
    entry: Path | str,
    directory: Path,
    *,
    filter_windows_home: bool | None = None,
) -> bool:
    name = entry if isinstance(entry, str) else entry.name
    if name.startswith((".", "~$")):
        return True
    if name.casefold() == "desktop.ini":
        return True
    if filter_windows_home is None:
        filter_windows_home = _precompute_windows_home_filter(
            directory,
            hide_filtered_entries=True,
        )
    if filter_windows_home:
        name_folded = name.casefold()
        if name_folded.startswith("ntuser") or name_folded in _WINDOWS_HIDDEN_NAMES:
            return True
    return False


_WINDOWS_HIDDEN_NAMES = {
    "intelgraphicsprofiles",
    "desktop.ini",
    "application data",
    "local settings",
    "cookies",
    "history",
    "recent",
    "sendto",
    "start menu",
    "templates",
    "printhood",
    "nethood",
}


def _should_filter_windows_home(directory: Path) -> bool:
    try:
        return directory.resolve() == Path.home().resolve()
    except OSError:
        return False


def _precompute_windows_home_filter(
    directory: Path,
    *,
    hide_filtered_entries: bool,
) -> bool:
    if not hide_filtered_entries or sys.platform != "win32":
        return False
    return _should_filter_windows_home(directory)


def _should_preflight_windows_remote_path(directory: Path) -> bool:
    if sys.platform != "win32":
        return False
    root = _windows_path_root(directory)
    if root is None:
        return False
    try:
        import ctypes

        drive_type = ctypes.windll.kernel32.GetDriveTypeW(root)
    except Exception:
        return False
    return int(drive_type) == 4


def _windows_path_root(directory: Path) -> str | None:
    drive = directory.drive
    if len(drive) != 2 or drive[1] != ":":
        return None
    return f"{drive}\\"


def _probe_windows_directory_access(directory: Path, *, timeout: float = 1.0) -> bool:
    target = str(directory)
    if not target:
        return False
    try:
        result = subprocess.run(
            ["cmd", "/d", "/c", f'cd /d "{target}"'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0
