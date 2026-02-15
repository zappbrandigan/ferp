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
_BUMP_ORDER = {"patch": 0, "minor": 1, "major": 2}


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


def _load_config_paths(root: Path) -> list[Path]:
    config_paths: list[Path] = []
    default_config = root / "config.json"
    if default_config.exists():
        config_paths.append(default_config)
    config_paths.extend(sorted(root.glob("*/config.json")))
    if not config_paths:
        raise FileNotFoundError(f"No config.json found under {root}")
    return config_paths


def _namespace_id_for_config(path: Path, root: Path) -> str:
    if path.parent == root:
        return "core"
    return path.parent.name


def _merge_bump(current: str | None, incoming: str) -> str:
    if current is None:
        return incoming
    if _BUMP_ORDER.get(incoming, 0) > _BUMP_ORDER.get(current, 0):
        return incoming
    return current


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
    config_paths = _load_config_paths(submodule_root)
    configs: dict[Path, tuple[dict, list[dict]]] = {}
    scripts_by_id: dict[str, tuple[Path, dict]] = {}
    for config_path in config_paths:
        data, scripts = _load_config(config_path)
        configs[config_path] = (data, scripts)
        for entry in scripts:
            script_id = str(entry.get("id", "")).strip()
            if not script_id:
                continue
            scripts_by_id.setdefault(script_id, (config_path, entry))

    changes: list[dict] = []
    bumped_paths: set[Path] = set()
    namespace_bumps: dict[str, str] = {}
    for script_id, bump in args.bump:
        resolved = scripts_by_id.get(script_id)
        if not resolved:
            print(f"Unknown script id: {script_id}", file=sys.stderr)
            return 2
        config_path, entry = resolved
        current = str(entry.get("version", "")).strip()
        if not current:
            print(f"Missing version for script: {script_id}", file=sys.stderr)
            return 2
        new_version = _bump_version(current, bump)
        if new_version == current:
            print(f"Version unchanged for {script_id} ({current}).", file=sys.stderr)
            return 2
        entry["version"] = new_version
        bumped_paths.add(config_path)
        namespace_id = _namespace_id_for_config(config_path, submodule_root)
        bump_level = bump if bump in _BUMP_ORDER else "patch"
        namespace_bumps[namespace_id] = _merge_bump(
            namespace_bumps.get(namespace_id), bump_level
        )
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

    if not bumped_paths:
        print("No config files updated.", file=sys.stderr)
        return 2

    if namespace_bumps:
        for config_path in bumped_paths:
            data, _scripts = configs[config_path]
            namespace_id = _namespace_id_for_config(config_path, submodule_root)
            bump_level = namespace_bumps.get(namespace_id)
            if not bump_level:
                continue
            current_version = str(data.get("version") or "").strip()
            base_version = current_version or "0.0.0"
            try:
                new_version = _bump_version(base_version, bump_level)
            except ValueError:
                new_version = "0.0.1"
            if new_version != current_version:
                data["version"] = new_version

    for path in bumped_paths:
        data, _scripts = configs[path]
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    commit_message = args.message or f"build(release): bump script versions {args.tag}"
    if not args.no_commit:
        _run(
            ["git", "add", *[str(path) for path in sorted(bumped_paths)]],
            cwd=submodule_root,
        )
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
