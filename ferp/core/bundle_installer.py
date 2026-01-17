from __future__ import annotations

import json
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markup import escape
from textual.worker import Worker, WorkerState

from ferp.widgets.output_panel import ScriptOutputPanel
from ferp.widgets.scripts import ScriptManager
from ferp.core.dependency_manager import ScriptDependencyManager

if TYPE_CHECKING:
    from ferp.core.app import Ferp


@dataclass(frozen=True)
class ScriptBundleManifest:
    id: str
    name: str
    version: str
    script_type: str
    args: list[str]
    requires_input: bool
    input_prompt: str | None
    target: str
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
        panel = self._app.query_one(ScriptOutputPanel)
        panel.update_content(
            "[bold $primary]Installing bundle…[/bold $primary]\n"
            + escape(str(bundle_path))
            + "\n[dim]Preparing package...[/dim]"
        )
        self._app.run_worker(
            lambda: self._process_script_bundle(bundle_path),
            group="bundle_install",
            exclusive=True,
            thread=True,
        )

    def handle_worker_state(self, event: Worker.StateChanged) -> bool:
        worker = event.worker
        if worker.group != "bundle_install":
            return False

        if event.state is WorkerState.SUCCESS:
            result = worker.result
            if isinstance(result, InstalledBundleResult):
                self._handle_bundle_install_result(result)
            return True

        if event.state is WorkerState.ERROR:
            error = worker.error or RuntimeError("Bundle installation failed.")
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
        panel = self._app.query_one(ScriptOutputPanel)
        rel_script = result.script_path.relative_to(self._app_root)

        lines = [
            "[bold $success]Script bundle installed[/bold $success]",
            f"[bold $primary]Name:[/bold $primary] {escape(result.manifest.name)}",
            f"[bold $primary]Version:[/bold $primary] {escape(result.manifest.version)}",
            f"[bold $primary]Config ID:[/bold $primary] {escape(result.manifest.id)}",
            f"[bold $primary]Script:[/bold $primary] {escape(str(rel_script))}",
        ]

        if result.readme_path:
            rel_readme = result.readme_path.relative_to(self._app_root)
            lines.append(
                f"[bold $primary]README:[/bold $primary] {escape(str(rel_readme))}"
            )

        if result.manifest.dependencies:
            deps = ", ".join(result.manifest.dependencies)
            lines.append(f"[bold $primary]Dependencies:[/bold $primary] {escape(deps)}")

        panel.update_content("\n".join(lines))
        ## Need to test the following line
        panel.refresh()

        scripts_panel = self._app.query_one(ScriptManager)
        scripts_panel.load_scripts()
        ## Need to test the following line
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

        target = str(payload["target"])
        if target not in {
            "current_directory",
            "highlighted_file",
            "highlighted_directory",
        }:
            raise ValueError(
                "Manifest 'target' must be 'current_directory', "
                "'highlighted_file', or 'highlighted_directory'."
            )

        requires_input = bool(payload.get("requires_input", False))
        args_raw = payload.get("args", [])
        if not isinstance(args_raw, list):
            raise ValueError("Manifest 'args' must be a list.")
        args = [str(arg) for arg in args_raw]

        input_prompt = payload.get("input_prompt")
        if input_prompt is not None:
            input_prompt = str(input_prompt)

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
            script_type="python",
            args=args,
            requires_input=requires_input,
            input_prompt=input_prompt,
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
            "type": manifest.script_type,
            "script": {
                "windows": rel_path,
                "other": rel_path,
            },
            "args": manifest.args,
            "requires_input": manifest.requires_input,
            "target": manifest.target,
        }

        if manifest.input_prompt:
            entry["input_prompt"] = manifest.input_prompt
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
