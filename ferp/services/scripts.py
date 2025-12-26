import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ferp.domain.scripts import Script


@dataclass(frozen=True)
class ScriptExecutionContext:
    """Normalized FSCP execution details for a script."""

    script: Script
    script_path: Path
    target_path: Path
    target_kind: Literal["file", "directory"]
    args: list[str]


def build_execution_context(
    *,
    app_root: Path,
    current_path: Path,
    highlighted_path: Path | None,
    script: Script,
) -> ScriptExecutionContext:
    """Resolve script metadata into an execution context for the FSCP runner."""

    system = platform.system().lower()
    script_path = (
        script.script["windows"]
        if system == "windows"
        else script.script["other"]
    )
    full_path = (app_root / script_path).resolve()

    if not full_path.exists():
        raise FileNotFoundError(full_path)

    if full_path.suffix != ".py":
        raise ValueError(
            f"FSCP scripts must be Python files. Unsupported script: {full_path}"
        )

    if script.target == "current_directory":
        target_path = current_path
    else:
        if highlighted_path is None:
            raise ValueError("Select a file or directory before running this script.")
        target_path = highlighted_path

    if not target_path.exists():
        raise FileNotFoundError(target_path)

    target_kind: Literal["file", "directory"] = (
        "directory" if target_path.is_dir() else "file"
    )

    args = [str(target_path) if arg == "{target}" else arg for arg in script.args]

    return ScriptExecutionContext(
        script=script,
        script_path=full_path,
        target_path=target_path,
        target_kind=target_kind,
        args=args,
    )
