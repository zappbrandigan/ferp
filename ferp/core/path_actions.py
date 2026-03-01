from __future__ import annotations

from pathlib import Path
from typing import Callable

from ferp.core.errors import FerpError
from ferp.core.fs_controller import FileSystemController
from ferp.services.archive_ops import ArchiveFormat
from ferp.widgets.archive_dialogs import ArchiveCreateDialog, ArchiveCreateDialogResult
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
        suppress_watcher_refreshes: Callable[[float], None] | None = None,
        fs_controller: FileSystemController,
        delete_handler: Callable[[Path], None],
        bulk_delete_handler: Callable[[list[Path]], None],
        bulk_paste_handler: Callable[[list[tuple[Path, Path]], bool, bool], None],
        present_archive_create: Callable[
            [ArchiveCreateDialog, Callable[[ArchiveCreateDialogResult | None], None]],
            None,
        ]
        | None = None,
        archive_create_handler: Callable[
            [list[Path], Path, ArchiveFormat, int, bool], None
        ]
        | None = None,
        archive_extract_handler: Callable[[Path, Path, bool], None] | None = None,
    ) -> None:
        self._present_input = present_input
        self._present_archive_create = present_archive_create
        self._present_confirm = present_confirm
        self._show_error = show_error
        self._refresh_listing = refresh_listing
        self._suppress_watcher_refreshes = suppress_watcher_refreshes
        self._fs = fs_controller
        self._delete_handler = delete_handler
        self._bulk_delete_handler = bulk_delete_handler
        self._bulk_paste_handler = bulk_paste_handler
        self._archive_create_handler = archive_create_handler
        self._archive_extract_handler = archive_extract_handler

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
                if self._suppress_watcher_refreshes is not None:
                    self._suppress_watcher_refreshes(0.5)
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
            if self._suppress_watcher_refreshes is not None:
                self._suppress_watcher_refreshes(0.5)
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

    def create_archive(self, sources: list[Path], destination_dir: Path) -> None:
        if not self._present_archive_create or not self._archive_create_handler:
            self._show_error(
                FerpError(
                    code="archive_create_failed",
                    message="Archive creation is not available.",
                )
            )
            return
        archive_create_handler = self._archive_create_handler
        present_archive_create = self._present_archive_create
        if not destination_dir.exists() or not destination_dir.is_dir():
            self._show_error(
                FerpError(
                    code="archive_create_failed",
                    message="Destination must be an existing directory.",
                )
            )
            return

        unique_sources: list[Path] = []
        seen: set[Path] = set()
        missing: list[Path] = []
        for source in sources:
            resolved = source.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if not source.exists():
                missing.append(source)
                continue
            unique_sources.append(source)

        if missing:
            sample = ", ".join(path.name for path in missing[:3])
            suffix = "..." if len(missing) > 3 else ""
            self._show_error(
                FerpError(
                    code="archive_create_failed",
                    message=f"Missing source item(s): {sample}{suffix}",
                )
            )
            return

        if not unique_sources:
            self._show_error(
                FerpError(
                    code="archive_create_failed",
                    message="No files selected to archive.",
                    severity="warning",
                )
            )
            return

        default_output = self._default_archive_name(unique_sources, destination_dir)

        def after(result: ArchiveCreateDialogResult | None) -> None:
            if result is None:
                return
            output_path = self._resolve_destination_path(
                destination_dir, result.output_path
            )
            output_path = self._ensure_archive_suffix(output_path, result.format)
            if any(
                output_path.resolve() == source.resolve() for source in unique_sources
            ):
                self._show_error(
                    FerpError(
                        code="archive_create_failed",
                        message="Archive output cannot overwrite a selected source.",
                    )
                )
                return
            for source in unique_sources:
                if not source.is_dir():
                    continue
                try:
                    output_path.resolve().relative_to(source.resolve())
                except ValueError:
                    continue
                self._show_error(
                    FerpError(
                        code="archive_create_failed",
                        message="Cannot create an archive inside a selected folder.",
                    )
                )
                return

            def perform(overwrite: bool) -> None:
                archive_create_handler(
                    unique_sources,
                    output_path,
                    result.format,
                    result.compression_level,
                    overwrite,
                )

            if output_path.exists():
                self._present_confirm(
                    ConfirmDialog(f"'{output_path.name}' exists. Overwrite?"),
                    lambda confirmed: perform(True) if confirmed else None,
                )
                return
            perform(False)

        present_archive_create(
            ArchiveCreateDialog(default_output=default_output),
            after,
        )

    def extract_archive(self, target: Path, destination_dir: Path) -> None:
        if not self._archive_extract_handler:
            self._show_error(
                FerpError(
                    code="archive_extract_failed",
                    message="Archive extraction is not available.",
                )
            )
            return
        archive_extract_handler = self._archive_extract_handler
        if not target.exists() or not target.is_file():
            self._show_error(
                FerpError(
                    code="archive_invalid_target",
                    message="Select a valid archive file.",
                )
            )
            return
        if target.suffix.lower() not in {".zip", ".7z"}:
            self._show_error(
                FerpError(
                    code="archive_invalid_target",
                    message="Only .zip and .7z archives can be extracted.",
                )
            )
            return

        default_output = target.stem

        def after(value: str | None) -> None:
            if not value:
                return
            candidate = Path(value).expanduser()
            if not candidate.is_absolute() and len(candidate.parts) != 1:
                self._show_error(
                    FerpError(
                        code="archive_invalid_target",
                        message="Enter a single destination folder name.",
                    )
                )
                return
            output_dir = self._resolve_destination_path(destination_dir, value)

            def perform(overwrite: bool) -> None:
                archive_extract_handler(target, output_dir, overwrite)

            if output_dir.exists():
                self._present_confirm(
                    ConfirmDialog(f"'{output_dir.name}' exists. Overwrite?"),
                    lambda confirmed: perform(True) if confirmed else None,
                )
                return
            perform(False)

        self._present_input(
            InputDialog(
                "Extract Archive: Destination Folder",
                default=default_output,
                subtitle="Enter confirm | Esc cancel",
            ),
            after,
        )

    @staticmethod
    def _default_archive_name(sources: list[Path], destination_dir: Path) -> str:
        if len(sources) == 1:
            source = sources[0]
            base = source.stem if source.is_file() else source.name
        else:
            base = destination_dir.name or "archive"
        return f"{base}.zip"

    @staticmethod
    def _resolve_destination_path(base_dir: Path, value: str) -> Path:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).expanduser()
        return candidate.resolve()

    @staticmethod
    def _ensure_archive_suffix(path: Path, archive_format: str) -> Path:
        suffix = ".zip" if archive_format == "zip" else ".7z"
        if path.name.endswith(suffix):
            return path
        if path.suffix.lower() in {".zip", ".7z"}:
            return path.with_suffix(suffix)
        return path.with_name(f"{path.name}{suffix}")
