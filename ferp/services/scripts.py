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


def build_execution_context(
    *,
    app_root: Path,
    current_path: Path,
    selected_path: Path | None,
    script: Script,
) -> ScriptExecutionContext:
    """Resolve script metadata into an execution context for the FSCP runner."""

    full_path = (app_root / script.script).resolve()

    if not full_path.exists():
        raise FileNotFoundError(full_path)

    if full_path.suffix != ".py":
        raise ValueError(
            f"FSCP scripts must be Python files. Unsupported script: {full_path}"
        )

    if script.target == "current_directory":
        target_path = current_path
    elif script.target in {"highlighted_file", "highlighted_directory"}:
        if selected_path is None:
            raise ValueError("Select a file or directory before running this script.")
        target_path = selected_path
    else:
        raise ValueError(f"Unsupported script target: {script.target}")

    if not target_path.exists():
        raise FileNotFoundError(target_path)

    target_kind: Literal["file", "directory"] = (
        "directory" if target_path.is_dir() else "file"
    )
    if script.target == "highlighted_file" and target_kind != "file":
        raise ValueError(
            f"'{script.name}' expects a file. Highlight a file and try again."
        )
    if script.target == "highlighted_directory" and target_kind != "directory":
        raise ValueError(
            f"'{script.name}' expects a directory. Highlight a folder and try again."
        )
    if script.target == "highlighted_file":
        allowed_extensions = _normalize_extensions(script.file_extensions)
        if allowed_extensions:
            name = target_path.name.lower()
            if not any(name.endswith(ext) for ext in allowed_extensions):
                extensions_label = ", ".join(sorted(allowed_extensions))
                raise ValueError(
                    f"'{script.name}' expects {extensions_label} file(s). "
                    "Highlight a matching file and try again."
                )

    return ScriptExecutionContext(
        script=script,
        script_path=full_path,
        target_path=target_path,
        target_kind=target_kind,
    )


def _normalize_extensions(extensions: list[str] | None) -> list[str]:
    if not extensions:
        return []
    normalized: list[str] = []
    for ext in extensions:
        cleaned = ext.strip().lower()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned}"
        normalized.append(cleaned)
    return normalized
