from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
        entries = sorted(directory.iterdir())
    except OSError as exc:
        return DirectoryListingResult(directory, token, [], str(exc))

    rows: list[FileListingEntry] = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        listing_entry = _build_listing_entry(entry)
        if listing_entry is not None:
            rows.append(listing_entry)

    return DirectoryListingResult(directory, token, rows)


def snapshot_directory(path: Path) -> tuple[str, ...]:
    try:
        entries = sorted(entry.name for entry in path.iterdir())
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
