from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ferp.widgets.file_tree import FileListingEntry


@dataclass(frozen=True)
class DirectoryListingResult:
    path: Path
    token: int
    entries: list[FileListingEntry]
    error: str | None = None


def collect_directory_listing(directory: Path, token: int) -> DirectoryListingResult:
    try:
        with os.scandir(directory) as scan:
            visible = []
            for entry in scan:
                entry_path = Path(entry.path)
                if _should_skip_entry(entry_path, directory):
                    continue
                visible.append(entry)
            entries = sorted(visible, key=_sort_key)
    except OSError as exc:
        return DirectoryListingResult(directory, token, [], str(exc))

    rows: list[FileListingEntry] = []
    for entry in entries:
        listing_entry = _build_listing_entry(entry)
        if listing_entry is not None:
            rows.append(listing_entry)

    return DirectoryListingResult(directory, token, rows)


def _sort_key(entry: os.DirEntry[str]) -> tuple[int, str]:
    try:
        is_dir = entry.is_dir(follow_symlinks=False)
    except OSError:
        is_dir = False
    name = entry.name
    underscore_dir_rank = 0 if is_dir and name.startswith("_") else 1
    return (underscore_dir_rank, name.casefold())


def snapshot_directory(path: Path) -> tuple[str, ...]:
    try:
        stat_result = path.stat()
    except OSError:
        return tuple()
    signature = f"{stat_result.st_mtime_ns}:{stat_result.st_size}:{stat_result.st_ino}"
    return (signature,)


def _build_listing_entry(entry: os.DirEntry[str]) -> FileListingEntry | None:
    entry_path = Path(entry.path)
    try:
        is_dir = entry.is_dir(follow_symlinks=False)
    except OSError:
        return None
    name = entry.name
    stem = Path(name).stem
    display_name = f"{name}/" if is_dir else stem

    type_label = "dir" if is_dir else entry_path.suffix.lstrip(".").lower()
    if not type_label:
        type_label = "file"

    search_blob = f"{display_name}\n{type_label}\n{entry_path.name}".casefold()
    return FileListingEntry(
        path=entry_path,
        display_name=display_name,
        char_count=len(name) if is_dir else len(stem),
        type_label=type_label,
        modified_ts=None,
        is_dir=is_dir,
        search_blob=search_blob,
    )


def _should_skip_entry(entry: Path, directory: Path) -> bool:
    name = entry.name
    if name.startswith("."):
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
