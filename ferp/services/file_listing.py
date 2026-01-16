from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys

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
            entries = sorted(scan, key=lambda entry: entry.name.casefold())
    except OSError as exc:
        return DirectoryListingResult(directory, token, [], str(exc))

    rows: list[FileListingEntry] = []
    for entry in entries:
        entry_path = Path(entry.path)
        if _should_skip_entry(entry_path, directory):
            continue
        listing_entry = _build_listing_entry(entry)
        if listing_entry is not None:
            rows.append(listing_entry)

    return DirectoryListingResult(directory, token, rows)


def snapshot_directory(path: Path) -> tuple[str, ...]:
    try:
        with os.scandir(path) as scan:
            entries = sorted(
                entry.name
                for entry in scan
                if not _should_skip_entry(Path(entry.path), path)
            )
    except OSError:
        entries = []
    return tuple(entries)


def _build_listing_entry(entry: os.DirEntry[str]) -> FileListingEntry | None:
    try:
        stat = entry.stat()
    except OSError:
        return None

    entry_path = Path(entry.path)
    is_dir = entry.is_dir()
    stem = Path(entry.name).stem

    display_name = stem if not is_dir else f"{stem}/"

    type_label = "dir" if is_dir else entry_path.suffix.lstrip(".").lower()
    if not type_label:
        type_label = "file"

    return FileListingEntry(
        path=entry_path,
        display_name=display_name,
        char_count=len(stem),
        type_label=type_label,
        modified_ts=stat.st_mtime,
        created_ts=stat.st_ctime,
        is_dir=is_dir,
    )


def _should_skip_entry(entry: Path, directory: Path) -> bool:
    name = entry.name
    if name.startswith("."):
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
