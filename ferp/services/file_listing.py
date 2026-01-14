from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
        entries = sorted(directory.iterdir())
    except OSError as exc:
        return DirectoryListingResult(directory, token, [], str(exc))

    rows: list[FileListingEntry] = []
    for entry in entries:
        if _should_skip_entry(entry, directory):
            continue
        listing_entry = _build_listing_entry(entry)
        if listing_entry is not None:
            rows.append(listing_entry)

    return DirectoryListingResult(directory, token, rows)


def snapshot_directory(path: Path) -> tuple[str, ...]:
    try:
        entries = sorted(
            entry.name
            for entry in path.iterdir()
            if not _should_skip_entry(entry, path)
        )
    except OSError:
        entries = []
    return tuple(entries)


def _build_listing_entry(path: Path) -> FileListingEntry | None:
    try:
        stat = path.stat()
    except OSError:
        return None

    created = datetime.strftime(datetime.fromtimestamp(stat.st_ctime), "%x %I:%S %p")
    modified = datetime.strftime(datetime.fromtimestamp(stat.st_mtime), "%x %I:%S %p")

    display_name = path.stem if not path.is_dir() else f"{path.stem}/"

    type_label = "dir" if path.is_dir() else path.suffix.lstrip(".").lower()
    if not type_label:
        type_label = "file"

    return FileListingEntry(
        path=path,
        display_name=display_name,
        char_count=len(path.stem),
        type_label=type_label,
        modified_label=modified,
        created_label=created,
        is_dir=path.is_dir(),
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
