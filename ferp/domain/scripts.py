from typing import TypedDict, List, Literal, Optional
from typing_extensions import NotRequired
from dataclasses import dataclass


class ScriptPathMap(TypedDict):
    windows: str
    other: str

TargetType = Literal[
    "current_directory",
    "highlighted_file",
    "highlighted_directory",
]

class ScriptConfig(TypedDict):
    id: str
    name: str
    version: str
    type: Literal["shell", "python"]
    script: ScriptPathMap
    args: List[str]
    requires_input: bool
    input_prompt: NotRequired[str]
    target: TargetType
    file_extensions: NotRequired[List[str]]


@dataclass(frozen=True)
class Script:
    id: str
    name: str
    version: str
    script: ScriptPathMap
    args: List[str]
    requires_input: bool
    input_prompt: Optional[str]
    target: TargetType
    file_extensions: Optional[List[str]]
