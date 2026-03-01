from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ferp.widgets.file_tree import FileListingEntry

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
    error: str | None = None


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


def _entry_sort_key(entry: os.DirEntry[str], sort_by: SortMode) -> tuple[object, ...]:
    path = Path(entry.path)
    name = entry.name
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
    try:
        with os.scandir(directory) as scan:
            visible: list[os.DirEntry[str]] = []
            for entry in scan:
                entry_path = Path(entry.path)
                if not is_entry_visible(
                    entry_path,
                    directory,
                    hide_filtered_entries=hide_filtered_entries,
                ):
                    continue
                visible.append(entry)
            mode = normalize_sort_mode(sort_by)
            entries = sorted(
                visible,
                key=lambda item: _entry_sort_key(item, mode),
                reverse=sort_descending,
            )
    except OSError as exc:
        return DirectoryListingResult(directory, token, [], str(exc))

    rows: list[FileListingEntry] = []
    for entry in entries:
        listing_entry = _build_listing_entry(entry)
        if listing_entry is not None:
            rows.append(listing_entry)

    return DirectoryListingResult(directory, token, rows)


def snapshot_directory(
    path: Path,
    *,
    hide_filtered_entries: bool = True,
) -> tuple[str, ...]:
    try:
        with os.scandir(path) as scan:
            entries: list[os.DirEntry[str]] = []
            for entry in scan:
                entry_path = Path(entry.path)
                if not is_entry_visible(
                    entry_path,
                    path,
                    hide_filtered_entries=hide_filtered_entries,
                ):
                    continue
                entries.append(entry)
    except OSError:
        return tuple()

    mode = normalize_sort_mode("name")
    entries = sorted(entries, key=lambda item: _entry_sort_key(item, mode))

    signatures: list[str] = []
    for entry in entries:
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            continue
        signature = f"{entry.name}:{int(is_dir)}"
        signatures.append(signature)
    return tuple(signatures)


def _build_listing_entry(entry: os.DirEntry[str]) -> FileListingEntry | None:
    entry_path = Path(entry.path)
    try:
        is_dir = entry.is_dir(follow_symlinks=False)
    except OSError:
        return None
    name = entry.name
    display_name = f"{name}/" if is_dir else name

    type_label = "dir" if is_dir else entry_path.suffix.lstrip(".").lower()
    if not type_label:
        type_label = "file"

    search_blob = f"{display_name}\n{type_label}\n{entry_path.name}".casefold()
    return FileListingEntry(
        path=entry_path,
        display_name=display_name,
        char_count=len(name),
        type_label=type_label,
        is_dir=is_dir,
        search_blob=search_blob,
    )


def is_entry_visible(
    entry: Path,
    directory: Path,
    *,
    hide_filtered_entries: bool = True,
) -> bool:
    if not hide_filtered_entries:
        return True
    return not _should_skip_entry(entry, directory)


def _should_skip_entry(entry: Path, directory: Path) -> bool:
    name = entry.name
    if name.startswith((".", "~$")):
        return True
    if name.casefold() == "desktop.ini":
        return True
    if sys.platform == "win32" and _should_filter_windows_home(directory):
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
