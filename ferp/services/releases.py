from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from ferp.core.errors import FerpError
from ferp.services.update_check import is_newer

_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "ferp",
}


def update_scripts_from_release(
    repo_url: str, scripts_dir: Path, *, dry_run: bool = False
) -> str:
    payload = _fetch_latest_release(repo_url)

    zip_url = payload.get("zipball_url")
    if not zip_url:
        raise FerpError(
            code="release_missing_zip",
            message="Latest release is missing a zipball URL.",
        )

    tag_name = str(payload.get("tag_name") or "").strip()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / "scripts.zip"
        try:
            response = requests.get(zip_url, headers=_GITHUB_HEADERS, timeout=60)
            response.raise_for_status()
            archive_path.write_bytes(response.content)
        except requests.RequestException as exc:
            raise FerpError(
                code="release_download_failed",
                message="Failed to download release archive.",
                detail=str(exc),
            ) from exc

        extract_dir = tmp_path / "extract"
        try:
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract_dir)
        except zipfile.BadZipFile as exc:
            raise FerpError(
                code="release_bad_zip",
                message="Release archive is not a valid zip file.",
            ) from exc

        source_dir = _find_release_payload_dir(extract_dir)
        if not dry_run:
            _replace_scripts_payload(source_dir, scripts_dir)

    return tag_name


@dataclass(frozen=True)
class NamespaceVersionInfo:
    core_version: str | None
    namespace_versions: dict[str, str]


@dataclass(frozen=True)
class ScriptUpdateResult:
    ok: bool
    namespace: str
    latest_core: str | None
    latest_namespace: str | None
    stored_core: str | None
    stored_namespace: str | None
    core_update: bool
    namespace_update: bool
    is_update: bool
    error: str | None
    checked_at: datetime | None


def fetch_namespace_index(repo_url: str) -> tuple[str, dict]:
    payload = _fetch_latest_release(repo_url)
    tag_name = str(payload.get("tag_name") or "").strip()
    assets = _release_assets(payload)

    index_url = assets.get("namespaces.json")
    if not index_url:
        raise FerpError(
            code="release_missing_namespaces",
            message="Latest release is missing namespaces.json.",
        )

    try:
        response = requests.get(index_url, timeout=30)
        response.raise_for_status()
        index_payload = response.json()
    except requests.RequestException as exc:
        raise FerpError(
            code="namespaces_download_failed",
            message="Failed to download namespaces.json.",
            detail=str(exc),
        ) from exc
    except json.JSONDecodeError as exc:
        raise FerpError(
            code="namespaces_invalid_json",
            message="namespaces.json is not valid JSON.",
        ) from exc

    return tag_name, index_payload


def update_scripts_from_namespace_release(
    repo_url: str,
    scripts_dir: Path,
    *,
    namespace: str,
    dry_run: bool = False,
) -> tuple[str, NamespaceVersionInfo]:
    tag_name, index_payload = fetch_namespace_index(repo_url)
    namespaces = index_payload.get("namespaces", [])
    if not isinstance(namespaces, list):
        raise FerpError(
            code="namespaces_missing_list",
            message="namespaces.json is missing a namespaces list.",
        )

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
        raise FerpError(
            code="namespaces_missing_core",
            message="namespaces.json does not include a core asset.",
        )
    namespace_asset = _find_asset_id(namespace)
    if not namespace_asset:
        raise FerpError(
            code="namespaces_missing_namespace",
            message=f"namespaces.json does not include '{namespace}'.",
        )

    payload = _fetch_latest_release(repo_url)
    assets = _release_assets(payload)
    core_url = assets.get(core_asset)
    namespace_url = assets.get(namespace_asset)
    if not core_url or not namespace_url:
        raise FerpError(
            code="release_assets_missing",
            message="Release assets missing for selected namespace.",
        )

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
                raise FerpError(
                    code="release_asset_bad_zip",
                    message="Release asset is not a valid zip file.",
                ) from exc

        if not dry_run:
            _replace_scripts_payload(payload_dir, scripts_dir)

    version_info = _extract_namespace_versions(index_payload)
    return tag_name, version_info


def check_for_script_updates(
    repo_url: str,
    cache_path: Path,
    *,
    ttl_seconds: int,
    namespace: str,
    stored_core: str | None,
    stored_namespace: str | None,
) -> ScriptUpdateResult:
    now = datetime.now(timezone.utc)
    cached = _read_scripts_cache(cache_path, ttl_seconds)
    if cached is None:
        try:
            _tag_name, index_payload = fetch_namespace_index(repo_url)
            version_info = _extract_namespace_versions(index_payload)
            _write_scripts_cache(cache_path, version_info, now)
            checked_at = now
        except Exception as exc:
            cached = _read_scripts_cache(cache_path, None)
            if cached is None:
                return ScriptUpdateResult(
                    ok=False,
                    namespace=namespace,
                    latest_core=None,
                    latest_namespace=None,
                    stored_core=stored_core,
                    stored_namespace=stored_namespace,
                    core_update=False,
                    namespace_update=False,
                    is_update=False,
                    error=str(exc),
                    checked_at=None,
                )
            version_info, checked_at = cached
            latest_core = version_info.core_version
            latest_namespace = version_info.namespace_versions.get(namespace)
            core_update = _is_newer_version(latest_core, stored_core)
            namespace_update = _is_newer_version(latest_namespace, stored_namespace)
            return ScriptUpdateResult(
                ok=True,
                namespace=namespace,
                latest_core=latest_core,
                latest_namespace=latest_namespace,
                stored_core=stored_core,
                stored_namespace=stored_namespace,
                core_update=core_update,
                namespace_update=namespace_update,
                is_update=core_update or namespace_update,
                error=str(exc),
                checked_at=checked_at,
            )
    else:
        version_info, checked_at = cached

    latest_core = version_info.core_version
    latest_namespace = version_info.namespace_versions.get(namespace)
    core_update = _is_newer_version(latest_core, stored_core)
    namespace_update = _is_newer_version(latest_namespace, stored_namespace)
    return ScriptUpdateResult(
        ok=True,
        namespace=namespace,
        latest_core=latest_core,
        latest_namespace=latest_namespace,
        stored_core=stored_core,
        stored_namespace=stored_namespace,
        core_update=core_update,
        namespace_update=namespace_update,
        is_update=core_update or namespace_update,
        error=None,
        checked_at=checked_at,
    )


def _fetch_latest_release(repo_url: str) -> dict:
    owner, repo = _parse_github_repo(repo_url)
    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    try:
        response = requests.get(api_url, headers=_GITHUB_HEADERS, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise FerpError(
            code="release_metadata_failed",
            message="Failed to fetch latest release metadata.",
            detail=str(exc),
        ) from exc
    if not isinstance(payload, dict):
        raise FerpError(
            code="release_metadata_invalid",
            message="Release metadata response is not valid JSON.",
        )
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
        raise FerpError(
            code="release_asset_download_failed",
            message=f"Failed to download asset from {url}.",
            detail=str(exc),
        ) from exc


def _find_release_payload_dir(extract_dir: Path) -> Path:
    root_dirs = [path for path in extract_dir.iterdir() if path.is_dir()]
    if not root_dirs:
        raise FerpError(
            code="release_missing_directories",
            message="Release archive did not contain any directories.",
        )

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

    raise FerpError(
        code="release_missing_payload",
        message="Release archive did not include scripts payload.",
    )


def _payload_has_scripts(candidate: Path) -> bool:
    if not candidate.exists() or not candidate.is_dir():
        return False
    return any(path.name == "script.py" for path in candidate.rglob("script.py"))


def _parse_github_repo(repo_url: str) -> tuple[str, str]:
    url = repo_url.strip().removesuffix(".git")
    if "github.com/" not in url:
        raise FerpError(
            code="release_invalid_repo",
            message="Only GitHub URLs are supported for release updates.",
        )
    owner_repo = url.split("github.com/", 1)[1].strip("/")
    parts = owner_repo.split("/")
    if len(parts) != 2 or not all(parts):
        raise FerpError(
            code="release_invalid_repo",
            message="Invalid GitHub repository URL.",
        )
    return parts[0], parts[1]


def _replace_scripts_payload(source_dir: Path, scripts_dir: Path) -> None:
    if scripts_dir.exists():
        shutil.rmtree(scripts_dir)
    shutil.copytree(source_dir, scripts_dir, dirs_exist_ok=True)


def _extract_namespace_versions(index_payload: dict) -> NamespaceVersionInfo:
    namespaces = index_payload.get("namespaces", [])
    if not isinstance(namespaces, list):
        return NamespaceVersionInfo(core_version=None, namespace_versions={})
    core_version = _coerce_version(index_payload.get("core_version"))
    results: dict[str, str] = {}
    for entry in namespaces:
        if not isinstance(entry, dict):
            continue
        namespace_id = str(entry.get("id") or "").strip()
        if not namespace_id:
            continue
        version = _coerce_version(entry.get("version"))
        if not version:
            continue
        if namespace_id == "core":
            core_version = version
        else:
            results[namespace_id] = version
    return NamespaceVersionInfo(core_version=core_version, namespace_versions=results)


def _coerce_version(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    version = value.strip()
    return version or None


def _normalize_version(value: str) -> str:
    return value.strip().lstrip("v")


def _is_newer_version(latest: str | None, current: str | None) -> bool:
    if not latest or not current:
        return False
    return is_newer(_normalize_version(latest), _normalize_version(current))


def _read_scripts_cache(
    cache_path: Path, ttl_seconds: int | None
) -> tuple[NamespaceVersionInfo, datetime] | None:
    try:
        raw = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    checked_at = raw.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        return None
    checked_at_dt = datetime.fromtimestamp(checked_at, tz=timezone.utc)
    if ttl_seconds is not None:
        age = (datetime.now(timezone.utc) - checked_at_dt).total_seconds()
        if age > ttl_seconds:
            return None
    core_version = _coerce_version(raw.get("core"))
    namespaces = raw.get("namespaces")
    namespace_versions: dict[str, str] = {}
    if isinstance(namespaces, dict):
        for key, value in namespaces.items():
            key_text = str(key).strip()
            version = _coerce_version(value)
            if key_text and version:
                namespace_versions[key_text] = version
    return NamespaceVersionInfo(core_version, namespace_versions), checked_at_dt


def _write_scripts_cache(
    cache_path: Path, version_info: NamespaceVersionInfo, checked_at: datetime
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "core": version_info.core_version,
        "namespaces": version_info.namespace_versions,
        "checked_at": checked_at.timestamp(),
    }
    cache_path.write_text(json.dumps(payload))
