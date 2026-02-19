from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from ferp.core.errors import wrap_error


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
