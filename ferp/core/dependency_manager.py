from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence


class ScriptDependencyManager:
    """Install script dependencies from the user config."""

    def __init__(self, config_file: Path, python_executable: str | None = None) -> None:
        self._config_file = config_file
        self._python_executable = python_executable or sys.executable

    def install_for_scripts(self, script_ids: Iterable[str] | None = None) -> None:
        dependencies = self._collect_dependencies(script_ids)
        if not dependencies:
            return
        self._install_dependencies(dependencies)

    def _collect_dependencies(self, script_ids: Iterable[str] | None) -> list[str]:
        if not self._config_file.exists():
            raise FileNotFoundError(f"Unable to locate config at {self._config_file}")

        data = json.loads(self._config_file.read_text())
        scripts = data.get("scripts", [])
        selected_ids = {script_id for script_id in script_ids} if script_ids else None
        seen: set[str] = set()
        deps: list[str] = []

        for script in scripts:
            script_id = str(script.get("id", ""))
            if selected_ids is not None and script_id not in selected_ids:
                continue
            for dep in script.get("dependencies", []) or []:
                dep_text = str(dep).strip()
                if not dep_text or dep_text in seen:
                    continue
                seen.add(dep_text)
                deps.append(dep_text)

        return deps

    def _install_dependencies(self, dependencies: Sequence[str]) -> None:
        pip_cmd = [self._python_executable, "-m", "pip", "install", *dependencies]
        try:
            subprocess.run(
                pip_cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else ""
            raise RuntimeError(
                f"Failed to install dependencies ({', '.join(dependencies)}).\n{stderr}"
            ) from exc
