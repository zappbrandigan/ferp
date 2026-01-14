from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def run_terminal_command(
    command: str,
    cwd: Path,
    interactive_denylist: Iterable[str],
) -> dict[str, object]:
    command = command.strip()
    if not command:
        return {
            "command": "",
            "cwd": str(cwd),
            "stdout": "",
            "stderr": "",
            "returncode": 0,
        }

    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    if tokens and tokens[0] in set(interactive_denylist):
        return {
            "command": command,
            "cwd": str(cwd),
            "stdout": "",
            "stderr": f'"{tokens[0]}" requires a full terminal. Please use your system terminal.',
            "returncode": 1,
        }

    try:
        if sys.platform == "win32":
            shell_cmd = _build_windows_shell_command(command)
            completed = subprocess.run(
                shell_cmd,
                cwd=cwd,
                shell=False,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
            )
        else:
            completed = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=30,
            )
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "cwd": str(cwd),
            "stdout": "",
            "stderr": "Command timed out after 30 seconds.",
            "returncode": -1,
        }

    return {
        "command": command,
        "cwd": str(cwd),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }


def format_terminal_output(payload: dict[str, object]) -> str:
    command = payload.get("command", "")
    cwd = payload.get("cwd", "")
    stdout = payload.get("stdout", "")
    stderr = payload.get("stderr", "")
    returncode = payload.get("returncode", 0)

    lines = [
        f"[bold $primary]Command:[/bold $primary] {command}",
        f"[bold $primary]Directory:[/bold $primary] {cwd}",
        f"[bold $primary]Exit Code:[/bold $primary] {returncode}",
    ]

    if stdout:
        lines.append("\n[bold $success]stdout:[/bold $success]\n" + str(stdout).strip())

    if stderr:
        lines.append("\n[bold $error]stderr:[/bold $error]\n" + str(stderr).strip())

    return "\n".join(lines)


def _build_windows_shell_command(command: str) -> list[str]:
    for candidate in ("pwsh.exe", "powershell.exe"):
        if shutil.which(candidate):
            return [candidate, "-NoProfile", "-Command", command]
    return ["cmd.exe", "/c", command]
