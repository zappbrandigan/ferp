from __future__ import annotations

from pathlib import Path
from typing import Callable

from ferp.core.errors import FerpError
from ferp.core.fs_controller import FileSystemController
from ferp.widgets.dialogs import ConfirmDialog, InputDialog


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
        delete_handler: Callable[[Path], None],
        bulk_delete_handler: Callable[[list[Path]], None],
        bulk_paste_handler: Callable[[list[tuple[Path, Path]], bool, bool], None],
    ) -> None:
        self._present_input = present_input
        self._present_confirm = present_confirm
        self._show_error = show_error
        self._refresh_listing = refresh_listing
        self._fs = fs_controller
        self._delete_handler = delete_handler
        self._bulk_delete_handler = bulk_delete_handler
        self._bulk_paste_handler = bulk_paste_handler

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
            self._delete_handler(target)

        self._present_confirm(
            ConfirmDialog(f"Delete '{target.name}'?"),
            after,
        )

    def delete_paths(self, targets: list[Path]) -> None:
        existing = [target for target in targets if target.exists()]
        if not existing:
            return
        if len(existing) == 1:
            self.delete_path(existing[0])
            return

        def after(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self._bulk_delete_handler(existing)

        self._present_confirm(
            ConfirmDialog(f"Delete {len(existing)} items?"),
            after,
        )

    def rename_path(self, target: Path) -> None:
        if not target.exists():
            return

        name = target.name
        if name.endswith("."):
            suffix = ""
        else:
            suffix = target.suffix
        stem = name[: -len(suffix)] if suffix else name

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
                if not new_name.endswith(suffix):
                    new_name = f"{new_name}{suffix}"
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
        default_name = stem
        self._present_input(
            InputDialog("Enter new name", default=default_name),
            after,
        )

    def paste_paths(
        self,
        sources: list[Path],
        destination: Path,
        *,
        move: bool,
    ) -> None:
        if not destination.exists() or not destination.is_dir():
            self._show_error(
                FerpError(
                    code="paste_invalid_destination",
                    message="Destination must be an existing directory.",
                )
            )
            return

        unique_sources: list[Path] = []
        seen: set[Path] = set()
        for source in sources:
            if source in seen:
                continue
            seen.add(source)
            unique_sources.append(source)

        missing = [source for source in unique_sources if not source.exists()]
        if missing:
            sample = ", ".join(path.name for path in missing[:3])
            suffix = "..." if len(missing) > 3 else ""
            self._show_error(
                FerpError(
                    code="paste_missing_source",
                    message=f"Missing source item(s): {sample}{suffix}",
                )
            )
            return

        plan: list[tuple[Path, Path]] = []
        conflicts: list[Path] = []
        for source in unique_sources:
            destination_path = destination / source.name
            if destination_path.resolve() == source.resolve():
                continue
            if source.is_dir():
                try:
                    destination_path.resolve().relative_to(source.resolve())
                except ValueError:
                    pass
                else:
                    self._show_error(
                        FerpError(
                            code="paste_inside_self",
                            message="Cannot paste a folder inside itself.",
                        )
                    )
                    return
            if destination_path.exists():
                conflicts.append(destination_path)
            plan.append((source, destination_path))

        if not plan:
            self._show_error(
                FerpError(
                    code="paste_nothing",
                    message="Nothing to paste.",
                )
            )
            return

        def perform(overwrite: bool) -> None:
            self._bulk_paste_handler(plan, move, overwrite)

        if conflicts:
            prompt = f"Overwrite {len(conflicts)} existing item(s) in destination?"
            self._present_confirm(
                ConfirmDialog(prompt),
                lambda confirmed: perform(True) if confirmed else None,
            )
            return

        perform(False)
