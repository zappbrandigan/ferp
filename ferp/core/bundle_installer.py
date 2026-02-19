from __future__ import annotations

import json
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from ferp.core.dependency_manager import ScriptDependencyManager
from ferp.core.errors import FerpError
from ferp.core.worker_groups import WorkerGroup
from ferp.core.worker_registry import worker_handler
from ferp.domain.scripts import TargetSelection, normalize_targets
from ferp.widgets.scripts import ScriptManager

if TYPE_CHECKING:
    from ferp.core.app import Ferp


@dataclass(frozen=True)
class ScriptBundleManifest:
    id: str
    name: str
    version: str
    target: TargetSelection
    entrypoint: str
    readme: str | None
    dependencies: list[str]
    file_extensions: list[str]


@dataclass(frozen=True)
class InstalledBundleResult:
    manifest: ScriptBundleManifest
    script_path: Path
    readme_path: Path | None


class ScriptBundleInstaller:
    """Handles installing zipped FSCP script bundles."""

    def __init__(self, app: "Ferp") -> None:
        self._app = app
        self._app_root = app.app_root
        self._scripts_dir = app.scripts_dir
        self._config_file = app._paths.config_file

    def start_install(self, bundle_path: Path) -> None:
        self._app.notify(
            f"Installing bundle: {bundle_path}",
            timeout=self._app.notify_timeouts.long,
        )
        self._app.run_worker(
            lambda: self._process_script_bundle(bundle_path),
            group=WorkerGroup.BUNDLE_INSTALL,
            exclusive=True,
            thread=True,
        )

    @worker_handler(WorkerGroup.BUNDLE_INSTALL)
    def handle_worker_state(self, event: Worker.StateChanged) -> bool:
        worker = event.worker
        if worker.group != WorkerGroup.BUNDLE_INSTALL:
            return False

        if event.state is WorkerState.SUCCESS:
            result = worker.result
            if isinstance(result, InstalledBundleResult):
                self._handle_bundle_install_result(result)
            return True

        if event.state is WorkerState.ERROR:
            error = worker.error or RuntimeError("Bundle installation failed.")
            if not isinstance(error, FerpError):
                detail = None if isinstance(error, RuntimeError) else str(error)
                error = FerpError(
                    code="bundle_install_failed",
                    message="Bundle installation failed.",
                    detail=detail,
                )
            self._app.show_error(error)
            return True

        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _process_script_bundle(self, bundle_path: Path) -> InstalledBundleResult:
        path = bundle_path.expanduser()
        if not path.exists():
            raise FileNotFoundError(f"No bundle found at {path}")
        if not path.is_file():
            raise ValueError(f"Bundle path must point to a file: {path}")
        if path.suffix.lower() != ".ferp":
            raise ValueError("Bundles must be supplied as .ferp archives.")

        with zipfile.ZipFile(path) as archive:
            manifest_member = self._find_manifest_member(archive)
            raw_manifest = archive.read(manifest_member).decode("utf-8")
            manifest = self._parse_bundle_manifest(json.loads(raw_manifest))

            script_member = self._resolve_archive_member(archive, manifest.entrypoint)
            script_bytes = archive.read(script_member)

            script_dir = self._scripts_dir / manifest.id
            if script_dir.exists():
                shutil.rmtree(script_dir)
            script_dir.mkdir(parents=True, exist_ok=True)
            script_target = script_dir / "script.py"
            script_target.write_bytes(script_bytes)

            readme_path: Path | None = None
            if manifest.readme:
                readme_member = self._resolve_archive_member(archive, manifest.readme)
                readme_text = archive.read(readme_member).decode("utf-8")
                readme_path = script_dir / "readme.md"
                readme_path.write_text(readme_text, encoding="utf-8")

        self._update_scripts_config(manifest, script_target)
        dependency_manager = ScriptDependencyManager(
            self._config_file, python_executable=sys.executable
        )
        dependency_manager.install_for_scripts([manifest.id])

        return InstalledBundleResult(
            manifest=manifest,
            script_path=script_target,
            readme_path=readme_path,
        )

    def _handle_bundle_install_result(self, result: InstalledBundleResult) -> None:
        message = (
            f"Bundle installed: {result.manifest.name} v{result.manifest.version} "
            f"({result.manifest.id})"
        )
        self._app.notify(message, timeout=self._app.notify_timeouts.normal)
        scripts_panel = self._app.query_one(ScriptManager)
        scripts_panel.load_scripts()
        scripts_panel.focus()

    def _find_manifest_member(self, archive: zipfile.ZipFile) -> str:
        for name in archive.namelist():
            normalized = name.rstrip("/")
            if normalized.endswith("manifest.json"):
                return name
        raise FileNotFoundError("Bundle is missing manifest.json")

    def _resolve_archive_member(self, archive: zipfile.ZipFile, reference: str) -> str:
        normalized = reference.replace("\\", "/").strip("/")
        if not normalized:
            raise ValueError("Invalid reference inside bundle manifest.")

        files = [
            info.filename.rstrip("/")
            for info in archive.infolist()
            if not info.is_dir()
        ]

        for name in files:
            if name == normalized:
                return name

        matches = [name for name in files if name.endswith(normalized)]
        if not matches:
            raise FileNotFoundError(f"Unable to locate '{reference}' in bundle.")
        if len(matches) > 1:
            raise ValueError(f"Reference '{reference}' is ambiguous in bundle.")
        return matches[0]

    def _parse_bundle_manifest(self, payload: dict[str, Any]) -> ScriptBundleManifest:
        for key in ("id", "name", "version", "entrypoint", "target"):
            if key not in payload:
                raise ValueError(f"Manifest missing required field '{key}'.")

        try:
            target = normalize_targets(payload["target"])
        except ValueError as exc:
            raise ValueError(
                "Manifest 'target' must be one or more of 'current_directory', "
                "'highlighted_file', or 'highlighted_directory'."
            ) from exc

        readme = payload.get("readme")
        if readme is not None:
            readme = str(readme).strip()
            if not readme:
                readme = None

        deps_raw = payload.get("dependencies", [])
        if deps_raw is None:
            dependencies: list[str] = []
        elif isinstance(deps_raw, list):
            dependencies = [str(dep).strip() for dep in deps_raw if str(dep).strip()]
        else:
            raise ValueError(
                "Manifest 'dependencies' must be an array of requirement strings."
            )

        file_ext_raw = payload.get("file_extensions", [])
        if file_ext_raw is None:
            file_extensions: list[str] = []
        elif isinstance(file_ext_raw, list):
            file_extensions = [
                str(ext).strip() for ext in file_ext_raw if str(ext).strip()
            ]
        else:
            raise ValueError("Manifest 'file_extensions' must be an array of strings.")

        return ScriptBundleManifest(
            id=str(payload["id"]),
            name=str(payload["name"]),
            version=str(payload["version"]),
            target=target,
            entrypoint=str(payload["entrypoint"]),
            readme=readme,
            dependencies=dependencies,
            file_extensions=file_extensions,
        )

    def _update_scripts_config(
        self,
        manifest: ScriptBundleManifest,
        script_path: Path,
    ) -> None:
        config_path = self._config_file
        if not config_path.exists():
            raise FileNotFoundError(f"Unable to locate config at {config_path}")

        data = json.loads(config_path.read_text())
        scripts = data.setdefault("scripts", [])

        rel_path = script_path.relative_to(self._app_root).as_posix()
        entry: dict[str, Any] = {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "script": rel_path,
            "target": list(manifest.target),
        }
        if manifest.file_extensions:
            entry["file_extensions"] = manifest.file_extensions
        if manifest.dependencies:
            entry["dependencies"] = manifest.dependencies

        for index, existing in enumerate(scripts):
            if existing.get("id") == manifest.id:
                scripts[index] = entry
                break
        else:
            scripts.append(entry)

        config_path.write_text(json.dumps(data, indent=2) + "\n")
