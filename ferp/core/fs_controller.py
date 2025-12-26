from __future__ import annotations

from pathlib import Path
import shutil


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
            shutil.rmtree(target)
        else:
            target.unlink()

    def rename_path(self, source: Path, destination: Path, *, overwrite: bool = False) -> Path:
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
