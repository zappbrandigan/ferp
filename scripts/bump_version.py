#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _usage() -> str:
    return "Usage: bump_version.py [patch|minor|major|X.Y.Z]"


def _parse_version(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(value)
    if not match:
        raise ValueError(f"Invalid version '{value}'. Expected X.Y.Z")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def main() -> int:
    if len(sys.argv) != 2:
        print(_usage(), file=sys.stderr)
        return 2

    arg = sys.argv[1].strip()
    version_file = Path(__file__).resolve().parents[1] / "ferp" / "__version__.py"
    text = version_file.read_text(encoding="utf-8")
    match = VERSION_RE.search(text)

    if not match:
        print(f"Could not find __version__ in {version_file}", file=sys.stderr)
        return 1

    current = match.group(1)

    if arg in {"patch", "minor", "major"}:
        major, minor, patch = _parse_version(current)
        if arg == "patch":
            patch += 1
        elif arg == "minor":
            minor += 1
            patch = 0
        else:
            major += 1
            minor = 0
            patch = 0
        new_version = f"{major}.{minor}.{patch}"
    else:
        _parse_version(arg)
        new_version = arg

    updated = VERSION_RE.sub(f'__version__ = "{new_version}"', text, count=1)
    version_file.write_text(updated, encoding="utf-8")
    print(new_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
