from pathlib import Path

from textual.message import Message

from ferp.domain.scripts import Script


class NavigateRequest(Message):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__()


class RunScriptRequest(Message):
    def __init__(self, script: Script) -> None:
        self.script = script
        super().__init__()


class DirectorySelectRequest(Message):
    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__()


class ShowReadmeRequest(Message):
    def __init__(self, script: Script, readme_path: Path | None) -> None:
        super().__init__()
        self.script = script
        self.readme_path = readme_path


class CreatePathRequest(Message):
    def __init__(self, base: Path, *, is_directory: bool) -> None:
        super().__init__()
        self.base = base
        self.is_directory = is_directory


class DeletePathRequest(Message):
    def __init__(self, target: Path) -> None:
        super().__init__()
        self.target = target


class RenamePathRequest(Message):
    def __init__(self, target: Path) -> None:
        super().__init__()
        self.target = target
