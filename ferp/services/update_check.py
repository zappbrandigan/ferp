from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    current: str
    latest: str | None
    is_update: bool
    error: str | None
    checked_at: datetime | None


def check_for_update(
    package: str,
    current: str,
    cache_path: Path,
    *,
    ttl_seconds: int,
    force: bool = False,
) -> UpdateCheckResult:
    now = datetime.now(timezone.utc)
    if not force:
        cached = _read_cache(cache_path, ttl_seconds)
        if cached is not None:
            latest, checked_at = cached
            return UpdateCheckResult(
                ok=True,
                current=current,
                latest=latest,
                is_update=is_newer(latest, current),
                error=None,
                checked_at=checked_at,
            )

    try:
        latest = fetch_latest_version(package)
    except Exception as exc:
        cached = _read_cache(cache_path, None)
        latest = cached[0] if cached else None
        checked_at = cached[1] if cached else None
        return UpdateCheckResult(
            ok=cached is not None,
            current=current,
            latest=latest,
            is_update=is_newer(latest, current) if latest else False,
            error=str(exc),
            checked_at=checked_at,
        )

    _write_cache(cache_path, latest, now)
    return UpdateCheckResult(
        ok=True,
        current=current,
        latest=latest,
        is_update=is_newer(latest, current),
        error=None,
        checked_at=now,
    )


def fetch_latest_version(package: str) -> str:
    url = f"https://pypi.org/pypi/{package}/json"
    with urllib.request.urlopen(url, timeout=5) as response:
        payload = json.load(response)
    info = payload.get("info", {})
    version = info.get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("PyPI response missing latest version.")
    return version


def is_newer(latest: str, current: str) -> bool:
    def normalize(value: str) -> tuple[int, ...]:
        parts: list[int] = []
        for token in value.split("."):
            digits = []
            for ch in token:
                if ch.isdigit():
                    digits.append(ch)
                else:
                    break
            number = int("".join(digits) or "0")
            parts.append(number)
        while parts and parts[-1] == 0:
            parts.pop()
        return tuple(parts)

    latest_parts = normalize(latest)
    current_parts = normalize(current)
    max_len = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (max_len - len(latest_parts))
    current_parts += (0,) * (max_len - len(current_parts))
    return latest_parts > current_parts


def _read_cache(
    cache_path: Path, ttl_seconds: int | None
) -> tuple[str, datetime] | None:
    try:
        raw = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    latest = raw.get("latest")
    checked_at = raw.get("checked_at")
    if not isinstance(latest, str) or not latest:
        return None
    if not isinstance(checked_at, (int, float)):
        return None
    checked_at_dt = datetime.fromtimestamp(checked_at, tz=timezone.utc)
    if ttl_seconds is not None:
        age = (datetime.now(timezone.utc) - checked_at_dt).total_seconds()
        if age > ttl_seconds:
            return None
    return latest, checked_at_dt


def _write_cache(cache_path: Path, latest: str, checked_at: datetime) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "latest": latest,
        "checked_at": checked_at.timestamp(),
    }
    cache_path.write_text(json.dumps(payload))
