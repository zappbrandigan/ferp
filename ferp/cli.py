from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Sequence

from ferp import __version__
from ferp.app import main as run_app


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
        choices=["current_directory", "highlighted_file", "highlighted_directory"],
        default="current_directory",
        help="Which path FER​P should send to the script (default: current_directory).",
    )
    bundle_parser.add_argument(
        "--requires-input",
        action="store_true",
        help="Indicate that the script prompts for user input.",
    )
    bundle_parser.add_argument(
        "--arg",
        dest="args",
        action="append",
        default=[],
        help="Additional script argument (repeat for multiple). Defaults to '{target}'.",
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

    args_list = args.args or ["{target}"]

    manifest: dict[str, object] = {
        "id": script_id,
        "name": script_name,
        "version": args.script_version,
        "type": "python",
        "entrypoint": script_path.name,
        "target": args.target,
        "requires_input": bool(args.requires_input),
        "args": args_list,
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


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "bundle":
        args.handler(args)
        print(args)
        return

    if args.no_ui:
        return

    run_app()


if __name__ == "__main__":
    main()
