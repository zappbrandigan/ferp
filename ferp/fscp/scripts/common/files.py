from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable


_SKIP_FILE_PREFIXES = ("._", "~$")


def collect_files(
    root: Path,
    pattern: str,
    recursive: bool,
    *,
    check_cancel: Callable[[], None] | None = None,
) -> list[Path]:
    """Collect files matching pattern from a root file or directory.

    When recursive is enabled, skips any paths under directories that start with "_".
    Skips files with common placeholder prefixes (e.g., "._", "~$").
    """
    if root.is_file():
        if root.name.startswith(_SKIP_FILE_PREFIXES):
            return []
        return [root]
    if recursive:
        files: list[Path] = []
        for path in root.rglob(pattern):
            if check_cancel is not None:
                check_cancel()
            if (
                path.is_file()
                and not any(part.startswith("_") for part in path.parts)
                and not path.name.startswith(_SKIP_FILE_PREFIXES)
            ):
                files.append(path)
        return sorted(files)
    files = []
    for path in root.glob(pattern):
        if check_cancel is not None:
            check_cancel()
        if path.is_file() and not path.name.startswith(_SKIP_FILE_PREFIXES):
            files.append(path)
    return sorted(files)


def build_destination(
    directory: Path,
    base: str,
    suffix: str,
    overwrite: bool = False,
    *,
    base_dir: Path | None = None,
    counter_padding: int = 2,
    force_suffix: bool = False,
) -> Path:
    """Build a non-colliding destination path with an optional counter suffix.

    Use base_dir to override the output directory, and force_suffix to always
    append a counter even if the base path does not exist yet.
    """
    target_dir = base_dir if base_dir is not None else directory
    candidate = target_dir / f"{base}{suffix}"
    if overwrite or (not candidate.exists() and not force_suffix):
        return candidate

    counter = 1
    while True:
        candidate = target_dir / f"{base}_{counter:0{counter_padding}d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def build_archive_destination(
    directory: Path,
    filename: str,
    *,
    counter_padding: int = 2,
) -> Path:
    """Build a non-colliding archive destination for an existing filename."""
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    base = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        candidate = directory / f"{base}_{counter:0{counter_padding}d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def move_to_dir(
    path: Path,
    destination_dir: Path,
    *,
    base: str | None = None,
    overwrite: bool = False,
    force_suffix: bool = False,
    use_shutil: bool = False,
) -> Path:
    """Move path into destination_dir using a non-colliding filename."""
    if path.parent == destination_dir:
        return path
    destination_dir.mkdir(parents=True, exist_ok=True)
    name_base = base if base is not None else path.stem
    destination = build_destination(
        destination_dir,
        name_base,
        path.suffix,
        overwrite=overwrite,
        force_suffix=force_suffix,
    )
    if use_shutil:
        shutil.move(str(path), destination)
        return destination
    return path.rename(destination)
