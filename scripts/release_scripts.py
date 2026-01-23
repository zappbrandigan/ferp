#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_semver(value: str) -> tuple[int, int, int]:
    match = SEMVER_RE.match(value)
    if not match:
        raise ValueError(f"Invalid version '{value}'. Expected X.Y.Z")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _bump_version(current: str, bump: str) -> str:
    bump = bump.strip()
    if bump in {"patch", "minor", "major"}:
        major, minor, patch = _parse_semver(current)
        if bump == "patch":
            patch += 1
        elif bump == "minor":
            minor += 1
            patch = 0
        else:
            major += 1
            minor = 0
            patch = 0
        return f"{major}.{minor}.{patch}"

    _parse_semver(bump)
    return bump


def _run(cmd: list[str], cwd: Path) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def _tag_exists(tag: str, cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--tags", "--verify", "--quiet", f"refs/tags/{tag}"],
        cwd=cwd,
        check=False,
    )
    return result.returncode == 0


def _tag_exists_on_remote(tag: str, cwd: Path, remote: str) -> bool:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "--exit-code", remote, f"refs/tags/{tag}"],
        cwd=cwd,
        check=False,
    )
    return result.returncode == 0


def _load_config(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    scripts = data.get("scripts")
    if not isinstance(scripts, list):
        raise ValueError("config.json is missing a 'scripts' list.")
    return data, scripts


def _release_notes(changes: list[dict]) -> str:
    lines = ["## Script updates", ""]
    for change in changes:
        name = change["name"]
        script_id = change["id"]
        before = change["before"]
        after = change["after"]
        lines.append(f"- {name} ({script_id}): {before} -> {after}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump script versions, tag, and create a GitHub release."
    )
    parser.add_argument(
        "--bump",
        nargs=2,
        action="append",
        metavar=("SCRIPT_ID", "VERSION"),
        help="Script ID and bump (patch/minor/major or X.Y.Z). Can be repeated.",
    )
    parser.add_argument(
        "--tag", required=True, help="Git tag to create (e.g. v2024.01.20)."
    )
    parser.add_argument(
        "--message",
        help="Commit message to use (defaults to 'Release scripts <tag>').",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print notes only.")
    parser.add_argument("--no-commit", action="store_true", help="Skip git commit.")
    parser.add_argument("--no-tag", action="store_true", help="Skip git tag.")
    parser.add_argument(
        "--force-tag", action="store_true", help="Overwrite existing tag."
    )
    parser.add_argument(
        "--push-tag", action="store_true", help="Push tag before GitHub release."
    )
    parser.add_argument(
        "--remote",
        default="origin",
        help="Git remote to use for tag checks/push (default: origin).",
    )
    parser.add_argument("--no-gh", action="store_true", help="Skip GitHub release.")

    args = parser.parse_args()
    if not args.bump:
        print("At least one --bump is required.", file=sys.stderr)
        return 2

    main_root = Path(__file__).resolve().parents[1]
    submodule_root = main_root / "ferp" / "scripts"
    config_path = submodule_root / "config.json"
    data, scripts = _load_config(config_path)

    changes: list[dict] = []
    for script_id, bump in args.bump:
        entry = next(
            (script for script in scripts if script.get("id") == script_id), None
        )
        if not entry:
            print(f"Unknown script id: {script_id}", file=sys.stderr)
            return 2
        current = str(entry.get("version", "")).strip()
        if not current:
            print(f"Missing version for script: {script_id}", file=sys.stderr)
            return 2
        new_version = _bump_version(current, bump)
        if new_version == current:
            print(f"Version unchanged for {script_id} ({current}).", file=sys.stderr)
            return 2
        entry["version"] = new_version
        changes.append(
            {
                "id": script_id,
                "name": entry.get("name", script_id),
                "before": current,
                "after": new_version,
            }
        )

    notes = _release_notes(changes)
    if args.dry_run:
        print(notes)
        return 0

    if not args.no_tag and _tag_exists(args.tag, submodule_root):
        if args.force_tag:
            print(f"Overwriting existing tag {args.tag}.")
        else:
            print(
                f"Tag {args.tag} already exists. Use --force-tag or --no-tag.",
                file=sys.stderr,
            )
            return 2

    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    commit_message = args.message or f"build(release): bump script versions {args.tag}"
    if not args.no_commit:
        _run(["git", "add", str(config_path)], cwd=submodule_root)
        _run(["git", "commit", "-m", commit_message], cwd=submodule_root)

    if not args.no_tag:
        cmd = ["git", "tag", "-a", args.tag, "-m", commit_message]
        if args.force_tag:
            cmd.insert(2, "-f")
        _run(cmd, cwd=submodule_root)

    if not args.no_gh:
        release_title = args.tag
        if not _tag_exists_on_remote(args.tag, submodule_root, args.remote):
            if args.push_tag:
                _run(["git", "push", args.remote, args.tag], cwd=submodule_root)
            else:
                print(
                    f"Tag {args.tag} is not on {args.remote}. Use --push-tag or push it before continuing.",
                    file=sys.stderr,
                )
                return 2
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            handle.write(notes)
            notes_path = Path(handle.name)
        try:
            _run(
                [
                    "gh",
                    "release",
                    "create",
                    args.tag,
                    "--title",
                    release_title,
                    "--notes-file",
                    str(notes_path),
                ],
                cwd=submodule_root,
            )
        finally:
            notes_path.unlink(missing_ok=True)

    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
