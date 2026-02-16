from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path


class FileSystemController:
    """Encapsulates file-system mutations so the UI stays lean."""

    def create_path(
        self,
        target: Path,
        *,
        is_directory: bool,
        overwrite: bool = False,
    ) -> Path:
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

        return target

    def delete_path(self, target: Path) -> None:
        if not target.exists():
            return

        if target.is_dir():
            def _handle_remove_error(func, path, exc):
                if isinstance(exc, PermissionError):
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                    return
                raise exc

            shutil.rmtree(target, onexc=_handle_remove_error)
        else:
            target.unlink()

    def rename_path(
        self, source: Path, destination: Path, *, overwrite: bool = False
    ) -> Path:
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

    def copy_path(
        self, source: Path, destination: Path, *, overwrite: bool = False
    ) -> Path:
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

    def move_path(
        self, source: Path, destination: Path, *, overwrite: bool = False
    ) -> Path:
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
