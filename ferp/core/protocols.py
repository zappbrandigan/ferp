from pathlib import Path
from typing import Protocol

class AppWithPath(Protocol):
    current_path: Path
