from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import zipfile

import requests


def update_scripts_from_release(repo_url: str, scripts_dir: Path) -> str:
    owner, repo = _parse_github_repo(repo_url)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ferp",
    }

    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("Failed to fetch latest release metadata.") from exc

    zip_url = payload.get("zipball_url")
    if not zip_url:
        raise RuntimeError("Latest release is missing a zipball URL.")

    tag_name = str(payload.get("tag_name") or "").strip()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / "scripts.zip"
        try:
            response = requests.get(zip_url, headers=headers, timeout=60)
            response.raise_for_status()
            archive_path.write_bytes(response.content)
        except requests.RequestException as exc:
            raise RuntimeError("Failed to download release archive.") from exc

        extract_dir = tmp_path / "extract"
        try:
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract_dir)
        except zipfile.BadZipFile as exc:
            raise RuntimeError("Release archive is not a valid zip file.") from exc

        source_dir = _find_release_payload_dir(extract_dir)
        _replace_scripts_payload(source_dir, scripts_dir)

    return tag_name


def _find_release_payload_dir(extract_dir: Path) -> Path:
    root_dirs = [path for path in extract_dir.iterdir() if path.is_dir()]
    if not root_dirs:
        raise RuntimeError("Release archive did not contain any directories.")

    if len(root_dirs) == 1:
        root = root_dirs[0]
        nested_scripts = root / "scripts"
        if _payload_has_scripts(nested_scripts):
            return nested_scripts
        if _payload_has_scripts(root):
            return root

    for config_path in extract_dir.rglob("config.json"):
        candidate = config_path.parent
        if _payload_has_scripts(candidate):
            return candidate
        nested = candidate / "scripts"
        if _payload_has_scripts(nested):
            return nested

    raise RuntimeError("Release archive did not include scripts payload.")


def _payload_has_scripts(candidate: Path) -> bool:
    if not candidate.exists() or not candidate.is_dir():
        return False
    return any(path.name == "script.py" for path in candidate.rglob("script.py"))


def _parse_github_repo(repo_url: str) -> tuple[str, str]:
    url = repo_url.strip().removesuffix(".git")
    if "github.com/" not in url:
        raise ValueError("Only GitHub URLs are supported for release updates.")
    owner_repo = url.split("github.com/", 1)[1].strip("/")
    parts = owner_repo.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("Invalid GitHub repository URL.")
    return parts[0], parts[1]


def _replace_scripts_payload(source_dir: Path, scripts_dir: Path) -> None:
    if scripts_dir.exists():
        git_dir = scripts_dir / ".git"
        if git_dir.exists():
            for entry in scripts_dir.iterdir():
                if entry.name == ".git":
                    continue
                if entry.is_dir():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
        else:
            shutil.rmtree(scripts_dir)
    shutil.copytree(source_dir, scripts_dir, dirs_exist_ok=True)
