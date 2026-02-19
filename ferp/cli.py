from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Sequence

from platformdirs import user_config_path

from ferp import __version__
from ferp.app import main as run_app
from ferp.core.config import get_runtime_config
from ferp.core.paths import APP_AUTHOR, APP_NAME, SETTINGS_FILENAME
from ferp.core.settings_store import SettingsStore
from typing import cast

from ferp.domain.scripts import TargetType, normalize_targets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ferp",
        description="FERP — For Executing Repetitive Processes",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Print version and exit.",
    )

    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="Parse CLI arguments without launching the UI.",
    )

    subparsers = parser.add_subparsers(dest="command")

    bundle_parser = subparsers.add_parser(
        "bundle",
        help="Package a Python FSCP script (and optional README) into a .ferp bundle.",
    )
    bundle_parser.add_argument(
        "script",
        help="Path to the Python script to bundle.",
    )
    bundle_parser.add_argument(
        "readme",
        nargs="?",
        help="Optional README/guide to include.",
    )
    bundle_parser.add_argument(
        "--id",
        dest="script_id",
        help="Unique script identifier. Defaults to the script's filename stem.",
    )
    bundle_parser.add_argument(
        "--name",
        dest="script_name",
        help="Human-friendly script name. Defaults to the script's filename.",
    )
    bundle_parser.add_argument(
        "--version",
        dest="script_version",
        default="1.0.0",
        help="Script version recorded in the manifest (default: 1.0.0).",
    )
    bundle_parser.add_argument(
        "--target",
        default="current_directory",
        help=(
            "Which path FER​P should send to the script. "
            "Use a comma-separated list to allow multiple targets "
            "(default: current_directory)."
        ),
    )
    bundle_parser.add_argument(
        "--dependency",
        dest="dependencies",
        action="append",
        default=[],
        help="Add a pip requirement specifier (repeat for multiple).",
    )
    bundle_parser.add_argument(
        "-o",
        "--output",
        help="Output file (.ferp). Defaults to <script_id>.ferp in the current directory.",
    )
    bundle_parser.set_defaults(handler=handle_bundle)

    config_parser = subparsers.add_parser(
        "print-config",
        help=f"Print resolved runtime config and {SETTINGS_FILENAME} to stdout.",
    )
    config_parser.set_defaults(handler=handle_print_config)

    return parser


def handle_bundle(args: argparse.Namespace) -> None:
    script_path = Path(args.script).expanduser()
    if not script_path.exists() or not script_path.is_file():
        raise SystemExit(f"Script not found: {script_path}")
    if script_path.suffix.lower() != ".py":
        raise SystemExit("Bundles currently support Python (.py) scripts only.")

    readme_path: Path | None = None
    if args.readme:
        readme_path = Path(args.readme).expanduser()
        if not readme_path.exists() or not readme_path.is_file():
            raise SystemExit(f"README not found: {readme_path}")

    script_id = args.script_id or _slugify(script_path.stem)
    if not script_id:
        raise SystemExit("Unable to derive script id. Use --id to specify one.")

    script_name = args.script_name or script_path.stem.replace("_", " ").title()

    bundle_path = (
        Path(args.output).expanduser()
        if args.output
        else Path.cwd() / f"{script_id}.ferp"
    )
    if bundle_path.suffix.lower() != ".ferp":
        bundle_path = bundle_path.with_suffix(".ferp")

    raw_target = args.target
    target_values = [value.strip() for value in str(raw_target).split(",") if value]
    if target_values:
        allowed = {
            "current_directory",
            "highlighted_file",
            "highlighted_directory",
        }
        for value in target_values:
            if value not in allowed:
                raise SystemExit(f"Unsupported script target: {value}")
        target = normalize_targets(cast(list[TargetType], target_values))
    else:
        target = normalize_targets("current_directory")

    manifest: dict[str, object] = {
        "id": script_id,
        "name": script_name,
        "version": args.script_version,
        "entrypoint": script_path.name,
        "target": list(target),
    }

    if readme_path:
        manifest["readme"] = readme_path.name
    dependencies = [dep.strip() for dep in args.dependencies if dep and dep.strip()]
    if dependencies:
        manifest["dependencies"] = dependencies

    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.write(script_path, arcname=script_path.name)
        if readme_path:
            archive.write(readme_path, arcname=readme_path.name)

    print(f"Bundle created: {bundle_path}")


def _slugify(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in value.lower())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


def _redact_secrets(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            tokens = ("token", "secret", "password", "api_key", "apikey")
            if any(token in key_text for token in tokens):
                redacted[key] = "***"
            else:
                redacted[key] = _redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def handle_print_config(_args: argparse.Namespace) -> None:
    config_dir = Path(user_config_path(APP_NAME, APP_AUTHOR))
    settings_path = config_dir / SETTINGS_FILENAME
    settings_store = SettingsStore(settings_path)
    payload = {
        "runtime": get_runtime_config().model_dump(),
        "settings_path": str(settings_path),
        "settings": settings_store.load(),
    }
    print(json.dumps(_redact_secrets(payload), indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in {"bundle", "print-config"}:
        args.handler(args)
        return

    if args.no_ui:
        return

    run_app()


if __name__ == "__main__":
    main()
