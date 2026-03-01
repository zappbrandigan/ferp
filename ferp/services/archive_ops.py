from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence

import py7zr

from ferp.core.errors import FerpError, wrap_error

ArchiveFormat = Literal["zip", "7z"]


@dataclass(frozen=True)
class CreateArchiveResult:
    output_path: Path
    format: ArchiveFormat
    source_count: int
    entry_count: int


@dataclass(frozen=True)
class ExtractArchiveResult:
    archive_path: Path
    output_dir: Path
    entry_count: int


def create_archive(
    sources: Sequence[Path],
    output_path: Path,
    *,
    format: ArchiveFormat,
    compression_level: int,
) -> CreateArchiveResult:
    normalized_sources = _normalize_sources(sources)
    if not normalized_sources:
        raise FerpError(
            code="archive_create_failed",
            message="No source items were provided.",
            severity="warning",
        )
    format = _normalize_archive_format(format)
    level = _normalize_compression_level(compression_level)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temp_output_path(output_path)
    entry_count = _count_source_entries(normalized_sources)
    try:
        if format == "zip":
            _create_zip_archive(normalized_sources, temp_path, level)
        else:
            _create_7z_archive(normalized_sources, temp_path, level)
        temp_path.replace(output_path)
    except Exception as exc:
        _cleanup_temp_file(temp_path)
        raise wrap_error(
            exc,
            code="archive_create_failed",
            message="Failed to create archive.",
        ) from exc

    return CreateArchiveResult(
        output_path=output_path,
        format=format,
        source_count=len(normalized_sources),
        entry_count=entry_count,
    )


def extract_archive(
    archive_path: Path,
    output_dir: Path,
) -> ExtractArchiveResult:
    archive_format = _format_from_path(archive_path)
    temp_dir = _temp_output_dir(output_dir)
    entry_count = 0
    try:
        if archive_format == "zip":
            entry_count = _extract_zip_archive(archive_path, temp_dir)
        else:
            entry_count = _extract_7z_archive(archive_path, temp_dir)
        _flatten_duplicate_root(temp_dir, expected_root=output_dir.name)
        temp_dir.replace(output_dir)
    except Exception as exc:
        _cleanup_temp_dir(temp_dir)
        raise wrap_error(
            exc,
            code="archive_extract_failed",
            message="Failed to extract archive.",
        ) from exc

    return ExtractArchiveResult(
        archive_path=archive_path,
        output_dir=output_dir,
        entry_count=entry_count,
    )


def _normalize_sources(sources: Sequence[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for source in sources:
        resolved = source.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(source)
    return unique


def _normalize_archive_format(value: str) -> ArchiveFormat:
    text = str(value).strip().lower()
    if text in {"zip", "7z"}:
        return text  # type: ignore[return-value]
    raise FerpError(
        code="archive_unsupported_format",
        message=f"Unsupported archive format: {value}",
    )


def _normalize_compression_level(value: int) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError) as exc:
        raise FerpError(
            code="archive_create_failed",
            message="Invalid compression level.",
            detail=str(value),
        ) from exc
    if not 0 <= level <= 9:
        raise FerpError(
            code="archive_create_failed",
            message="Compression level must be between 0 and 9.",
            detail=str(level),
        )
    return level


def _temp_output_path(output_path: Path) -> Path:
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{output_path.stem}.",
        suffix=f"{output_path.suffix}.tmp",
        dir=output_path.parent,
    )
    os.close(handle)
    return Path(temp_name)


def _temp_output_dir(output_dir: Path) -> Path:
    return Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.",
            suffix=".tmp",
            dir=output_dir.parent,
        )
    )


def _count_source_entries(sources: Sequence[Path]) -> int:
    total = 0
    for source in sources:
        total += 1
        if source.is_dir():
            total += sum(1 for _ in source.rglob("*"))
    return total


def _create_zip_archive(sources: Sequence[Path], temp_path: Path, level: int) -> None:
    if level <= 0:
        with zipfile.ZipFile(
            temp_path,
            "w",
            compression=zipfile.ZIP_STORED,
        ) as archive:
            _write_sources_to_zip(archive, sources)
        return

    with zipfile.ZipFile(
        temp_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=level,
    ) as archive:
        _write_sources_to_zip(archive, sources)


def _write_sources_to_zip(archive: zipfile.ZipFile, sources: Sequence[Path]) -> None:
    for source in sources:
        if source.is_file():
            archive.write(source, arcname=source.name)
            continue
        _write_directory_tree_zip(archive, source)


def _write_directory_tree_zip(archive: zipfile.ZipFile, directory: Path) -> None:
    archive.write(directory, arcname=directory.name)
    for child in sorted(directory.rglob("*")):
        relative = child.relative_to(directory.parent)
        archive.write(child, arcname=str(relative))


def _create_7z_archive(sources: Sequence[Path], temp_path: Path, level: int) -> None:
    if level <= 0:
        filters = [{"id": py7zr.FILTER_COPY}]
    else:
        filters = [{"id": py7zr.FILTER_LZMA2, "preset": level}]
    with py7zr.SevenZipFile(temp_path, "w", filters=filters) as archive:
        for source in sources:
            if source.is_file():
                archive.write(source, arcname=source.name)
                continue
            archive.writeall(source, arcname=source.name)


def _extract_zip_archive(archive_path: Path, temp_dir: Path) -> int:
    with zipfile.ZipFile(archive_path, "r") as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        _validate_member_names(names)
        archive.extractall(temp_dir)
        return len(members)


def _extract_7z_archive(archive_path: Path, temp_dir: Path) -> int:
    with py7zr.SevenZipFile(archive_path, "r") as archive:
        names = archive.getnames()
        _validate_member_names(names)
        archive.extractall(path=temp_dir)
        return len(names)


def _validate_member_names(names: Sequence[str]) -> None:
    for name in names:
        if not _is_safe_member_name(name):
            raise FerpError(
                code="archive_unsafe_member",
                message="Archive contains unsafe paths.",
                detail=name,
            )


def _is_safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute():
        return False
    for part in path.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            return False
    return True


def _flatten_duplicate_root(root: Path, *, expected_root: str) -> None:
    if not expected_root:
        return
    nested = root / expected_root
    if not nested.exists() or not nested.is_dir():
        return

    for child in list(nested.iterdir()):
        destination = root / child.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        child.rename(destination)
    nested.rmdir()


def _format_from_path(path: Path) -> ArchiveFormat:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return "zip"
    if suffix == ".7z":
        return "7z"
    raise FerpError(
        code="archive_invalid_target",
        message="Unsupported archive type.",
        detail=path.suffix,
    )


def _cleanup_temp_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _cleanup_temp_dir(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
