from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests


def update_scripts_from_release(
    repo_url: str, scripts_dir: Path, *, dry_run: bool = False
) -> str:
    payload = _fetch_latest_release(repo_url)

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
        if not dry_run:
            _replace_scripts_payload(source_dir, scripts_dir)

    return tag_name


def fetch_namespace_index(repo_url: str) -> tuple[str, dict]:
    payload = _fetch_latest_release(repo_url)
    tag_name = str(payload.get("tag_name") or "").strip()
    assets = _release_assets(payload)

    index_url = assets.get("namespaces.json")
    if not index_url:
        raise RuntimeError("Latest release is missing namespaces.json.")

    try:
        response = requests.get(index_url, timeout=30)
        response.raise_for_status()
        index_payload = response.json()
    except requests.RequestException as exc:
        raise RuntimeError("Failed to download namespaces.json.") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("namespaces.json is not valid JSON.") from exc

    return tag_name, index_payload


def update_scripts_from_namespace_release(
    repo_url: str,
    scripts_dir: Path,
    *,
    namespace: str,
    dry_run: bool = False,
) -> str:
    tag_name, index_payload = fetch_namespace_index(repo_url)
    namespaces = index_payload.get("namespaces", [])
    if not isinstance(namespaces, list):
        raise RuntimeError("namespaces.json is missing a namespaces list.")

    def _find_asset_id(ns_id: str) -> str:
        for entry in namespaces:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("id", "")).strip() == ns_id:
                asset = str(entry.get("asset", "")).strip()
                if asset:
                    return asset
        return ""

    core_asset = _find_asset_id("core")
    if not core_asset:
        raise RuntimeError("namespaces.json does not include a core asset.")
    namespace_asset = _find_asset_id(namespace)
    if not namespace_asset:
        raise RuntimeError(f"namespaces.json does not include '{namespace}'.")

    payload = _fetch_latest_release(repo_url)
    assets = _release_assets(payload)
    core_url = assets.get(core_asset)
    namespace_url = assets.get(namespace_asset)
    if not core_url or not namespace_url:
        raise RuntimeError("Release assets missing for selected namespace.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        core_zip = tmp_path / core_asset
        ns_zip = tmp_path / namespace_asset
        _download_asset(core_url, core_zip)
        _download_asset(namespace_url, ns_zip)

        payload_dir = tmp_path / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)

        for archive_path in (core_zip, ns_zip):
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    archive.extractall(payload_dir)
            except zipfile.BadZipFile as exc:
                raise RuntimeError("Release asset is not a valid zip file.") from exc

        if not dry_run:
            _replace_scripts_payload(payload_dir, scripts_dir)

    return tag_name


def _fetch_latest_release(repo_url: str) -> dict:
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
    if not isinstance(payload, dict):
        raise RuntimeError("Release metadata response is not valid JSON.")
    return payload


def _release_assets(payload: dict) -> dict[str, str]:
    assets = payload.get("assets", [])
    if not isinstance(assets, list):
        return {}
    results: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        url = str(asset.get("browser_download_url") or "").strip()
        if name and url:
            results[name] = url
    return results


def _download_asset(url: str, target: Path) -> None:
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        target.write_bytes(response.content)
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to download asset from {url}.") from exc


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
        shutil.rmtree(scripts_dir)
    shutil.copytree(source_dir, scripts_dir, dirs_exist_ok=True)
