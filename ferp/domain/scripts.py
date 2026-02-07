from dataclasses import dataclass
from typing import List, Literal, Optional, Sequence, TypedDict

from typing_extensions import NotRequired

TargetType = Literal[
    "current_directory",
    "highlighted_file",
    "highlighted_directory",
]
TargetConfig = TargetType | Sequence[TargetType]
TargetSelection = tuple[TargetType, ...]


class ScriptConfig(TypedDict):
    id: str
    name: str
    version: str
    script: str
    target: TargetConfig
    file_extensions: NotRequired[List[str]]


def normalize_targets(value: TargetConfig) -> TargetSelection:
    if isinstance(value, str):
        targets: list[TargetType] = [value]  # type: ignore[list-item]
    else:
        targets = [item for item in value if isinstance(item, str)]
    normalized: list[TargetType] = []
    for target in targets:
        if target not in {
            "current_directory",
            "highlighted_file",
            "highlighted_directory",
        }:
            raise ValueError(f"Unsupported script target: {target}")
        if target not in normalized:
            normalized.append(target)
    if not normalized:
        raise ValueError("Script target must include at least one entry.")
    return tuple(normalized)


@dataclass(frozen=True)
class Script:
    id: str
    name: str
    version: str
    script: str
    target: TargetSelection
    file_extensions: Optional[List[str]] = None
