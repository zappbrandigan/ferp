from dataclasses import dataclass
from typing import List, Literal, Optional, TypedDict

from typing_extensions import NotRequired

TargetType = Literal[
    "current_directory",
    "highlighted_file",
    "highlighted_directory",
]


class ScriptConfig(TypedDict):
    id: str
    name: str
    version: str
    script: str
    target: TargetType
    file_extensions: NotRequired[List[str]]


@dataclass(frozen=True)
class Script:
    id: str
    name: str
    version: str
    script: str
    target: TargetType
    file_extensions: Optional[List[str]] = None
