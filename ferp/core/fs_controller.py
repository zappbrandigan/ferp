from __future__ import annotations

import os
import shutil
import stat
import uuid
from pathlib import Path

from ferp.core.errors import wrap_error


def _same_filesystem_entry(source: Path, destination: Path) -> bool:
    try:
        return source.samefile(destination)
    except OSError:
        return False


def _same_parent(source: Path, destination: Path) -> bool:
    try:
        return source.parent.samefile(destination.parent)
    except OSError:
        return source.parent == destination.parent


def _is_case_only_rename(source: Path, destination: Path) -> bool:
    return (
        source.name != destination.name
        and source.name.casefold() == destination.name.casefold()
        and _same_parent(source, destination)
        and _same_filesystem_entry(source, destination)
    )


def _temporary_rename_path(source: Path) -> Path:
    for _attempt in range(20):
        candidate = source.with_name(f".{source.name}.ferp-rename-{uuid.uuid4().hex}.tmp")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find temporary rename path for {source}")


class FileSystemController:
    """Encapsulates file-system mutations so the UI stays lean."""

    def create_path(
        self,
        target: Path,
        *,
        is_directory: bool,
        overwrite: bool = False,
    ) -> Path:
        try:
            if target.exists():
                if not overwrite:
                    raise FileExistsError(f"{target} already exists")
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()

            if is_directory:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
        except Exception as exc:
            raise wrap_error(
                exc,
                code="fs_create_failed",
                message="Failed to create path.",
            ) from exc

        return target

    def delete_path(self, target: Path) -> None:
        if not target.exists():
            return

        def _handle_remove_error(func, path, exc):  # type: ignore[no-untyped-def]
            if isinstance(exc, PermissionError):
                os.chmod(path, stat.S_IWRITE)
                func(path)
                return
            raise exc

        try:
            if target.is_dir():
                shutil.rmtree(target, onexc=_handle_remove_error)
            else:
                target.unlink()
        except Exception as exc:
            raise wrap_error(
                exc,
                code="fs_delete_failed",
                message="Failed to delete path.",
            ) from exc

    def rename_path(
        self, source: Path, destination: Path, *, overwrite: bool = False
    ) -> Path:
        try:
            if not source.exists():
                raise FileNotFoundError(f"{source} does not exist")

            same_entry = _same_filesystem_entry(source, destination)
            case_only_rename = _is_case_only_rename(source, destination)

            if destination.exists() and not same_entry:
                if not overwrite:
                    raise FileExistsError(f"{destination} already exists")
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()

            if source == destination and not case_only_rename:
                return destination

            destination.parent.mkdir(parents=True, exist_ok=True)
            if case_only_rename:
                temporary = _temporary_rename_path(source)
                source.rename(temporary)
                try:
                    temporary.rename(destination)
                except Exception:
                    if temporary.exists() and not source.exists():
                        temporary.rename(source)
                    raise
                return destination

            source.rename(destination)
            return destination
        except Exception as exc:
            raise wrap_error(
                exc,
                code="fs_rename_failed",
                message="Failed to rename path.",
            ) from exc

    def copy_path(
        self, source: Path, destination: Path, *, overwrite: bool = False
    ) -> Path:
        try:
            if not source.exists():
                raise FileNotFoundError(f"{source} does not exist")

            if destination.exists():
                if not overwrite:
                    raise FileExistsError(f"{destination} already exists")
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()

            if source == destination:
                return destination

            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
            return destination
        except Exception as exc:
            raise wrap_error(
                exc,
                code="fs_copy_failed",
                message="Failed to copy path.",
            ) from exc

    def move_path(
        self, source: Path, destination: Path, *, overwrite: bool = False
    ) -> Path:
        try:
            if not source.exists():
                raise FileNotFoundError(f"{source} does not exist")

            if destination.exists() and destination != source:
                if not overwrite:
                    raise FileExistsError(f"{destination} already exists")
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink()

            if source == destination:
                return destination

            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            return destination
        except Exception as exc:
            raise wrap_error(
                exc,
                code="fs_move_failed",
                message="Failed to move path.",
            ) from exc
