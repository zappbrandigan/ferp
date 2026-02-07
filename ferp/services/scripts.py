from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ferp.domain.scripts import Script, TargetSelection


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

    allowed_targets = _normalize_targets(script.target)
    allow_current = "current_directory" in allowed_targets
    allow_file = "highlighted_file" in allowed_targets
    allow_dir = "highlighted_directory" in allowed_targets

    target_path: Path | None = None
    if selected_path is not None and (allow_file or allow_dir):
        target_path = selected_path
    elif allow_current:
        target_path = current_path

    if target_path is None:
        raise ValueError("Select a file or directory before running this script.")

    if not target_path.exists():
        raise FileNotFoundError(target_path)

    target_kind: Literal["file", "directory"] = (
        "directory" if target_path.is_dir() else "file"
    )
    if target_path is selected_path:
        if target_kind == "file" and not allow_file:
            raise ValueError(
                f"'{script.name}' expects a directory. Highlight a folder and try again."
            )
        if target_kind == "directory" and not allow_dir:
            raise ValueError(
                f"'{script.name}' expects a file. Highlight a file and try again."
            )
    elif target_path is current_path and not allow_current:
        raise ValueError(
            f"'{script.name}' expects a file or directory selection. "
            "Highlight a target and try again."
        )

    if target_kind == "file" and allow_file:
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


def _normalize_targets(targets: TargetSelection) -> set[str]:
    return set(targets)
