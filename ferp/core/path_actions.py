from __future__ import annotations

from pathlib import Path
from typing import Callable

from ferp.widgets.dialogs import ConfirmDialog, InputDialog
from ferp.core.fs_controller import FileSystemController


class PathActionController:
    """Orchestrates file/directory creation and deletion prompts."""

    def __init__(
        self,
        *,
        present_input: Callable[[InputDialog, Callable[[str | None], None]], None],
        present_confirm: Callable[[ConfirmDialog, Callable[[bool | None], None]], None],
        show_error: Callable[[BaseException], None],
        refresh_listing: Callable[[], None],
        fs_controller: FileSystemController,
    ) -> None:
        self._present_input = present_input
        self._present_confirm = present_confirm
        self._show_error = show_error
        self._refresh_listing = refresh_listing
        self._fs = fs_controller

    def create_path(self, base: Path, *, is_directory: bool) -> None:
        parent = base if base.is_dir() else base.parent
        default_name = "New Folder" if is_directory else "New File.txt"

        def after(name: str | None) -> None:
            if not name:
                return
            target = parent / name

            def perform(overwrite: bool) -> None:
                try:
                    self._fs.create_path(
                        target,
                        is_directory=is_directory,
                        overwrite=overwrite,
                    )
                except Exception as exc:
                    self._show_error(exc)
                    return
                self._refresh_listing()

            if target.exists():
                self._present_confirm(
                    ConfirmDialog(f"'{target.name}' exists. Overwrite?"),
                    lambda confirmed: perform(True) if confirmed else None,
                )
                return

            perform(False)

        self._present_input(
            InputDialog("Enter name", default=default_name),
            after,
        )

    def delete_path(self, target: Path) -> None:
        if not target.exists():
            return

        def after(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                self._fs.delete_path(target)
            except Exception as exc:
                self._show_error(exc)
                return
            self._refresh_listing()

        self._present_confirm(
            ConfirmDialog(f"Delete '{target.name}'?"),
            after,
        )

    def rename_path(self, target: Path) -> None:
        if not target.exists():
            return

        suffix = "".join(target.suffixes)

        def perform(overwrite: bool) -> None:
            try:
                self._fs.rename_path(target, destination, overwrite=overwrite)
            except Exception as exc:
                self._show_error(exc)
                return
            self._refresh_listing()

        def after(name: str | None) -> None:
            if not name:
                return
            nonlocal destination
            new_name = name
            if suffix:
                new_name = f"{name}{suffix}"
            destination = target.with_name(new_name)
            if destination == target:
                return

            if destination.exists():
                self._present_confirm(
                    ConfirmDialog(f"'{destination.name}' exists. Overwrite?"),
                    lambda confirmed: perform(True) if confirmed else None,
                )
                return

            perform(False)

        destination = target
        default_name = target.stem if suffix else target.name
        self._present_input(
            InputDialog("Enter new name", default=default_name),
            after,
        )
