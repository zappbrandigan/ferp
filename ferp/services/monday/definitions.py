from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ferp.core.errors import FerpError
from ferp.services.monday.client import MondayClient
from ferp.services.monday.generic import GenericTransformType, generic_sync

MondaySyncHandler = Callable[[MondayClient, int, Path], dict[str, object]]


@dataclass(frozen=True)
class MondaySyncDefinition:
    """A shipped Monday board query/transform that can be synced by FERP."""

    id: str
    namespace: str
    label: str
    description: str
    cache_filename: str
    handler: MondaySyncHandler
    legacy_board_id_key: str = "boardId"
    shipped: bool = True
    board_id: int | None = None


_SHIPPED_DEFINITIONS: tuple[MondaySyncDefinition, ...] = ()


def monday_sync_definitions(
    namespace: str, *, config_dir: Path | None = None
) -> tuple[MondaySyncDefinition, ...]:
    definitions = [defn for defn in _SHIPPED_DEFINITIONS if defn.namespace == namespace]
    if config_dir is None:
        return tuple(definitions)

    shipped_keys = {(definition.namespace, definition.id) for definition in definitions}
    for definition in load_user_monday_sync_definitions(config_dir):
        if definition.namespace != namespace:
            continue
        if (definition.namespace, definition.id) in shipped_keys:
            continue
        definitions.append(definition)
    return tuple(definitions)


def monday_sync_definition(
    namespace: str, definition_id: str, *, config_dir: Path | None = None
) -> MondaySyncDefinition | None:
    for definition in monday_sync_definitions(namespace, config_dir=config_dir):
        if definition.id == definition_id:
            return definition
    return None


def load_user_monday_sync_definitions(config_dir: Path) -> tuple[MondaySyncDefinition, ...]:
    monday_dir = config_dir / "monday"
    if not monday_dir.exists():
        return ()

    definitions: list[MondaySyncDefinition] = []
    for path in sorted(monday_dir.glob("*.json")):
        definitions.append(_load_definition_file(path))
    return tuple(definitions)


def _load_definition_file(path: Path) -> MondaySyncDefinition:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FerpError(
            code="monday_definition_invalid",
            message="Monday definition is invalid.",
            detail=str(path),
        ) from exc
    if not isinstance(payload, dict):
        raise _invalid_definition(path, "definition must be a JSON object")

    definition_id = _required_text(payload, "id", path)
    namespace = _required_text(payload, "namespace", path)
    label = _required_text(payload, "label", path)
    cache_filename = _required_text(payload, "cacheFilename", path)
    description = str(payload.get("description") or "").strip()
    query = _definition_query(payload, path)
    transform, key_column = _definition_transform(payload, path)
    legacy_key = str(payload.get("legacyBoardIdKey") or "boardId").strip() or "boardId"
    board_id = _optional_int(payload.get("boardId"), path, "boardId")

    def handler(
        client: MondayClient,
        board_id: int,
        cache_path: Path,
        *,
        query_text: str = query,
        transform_type: GenericTransformType = transform,
        key_column_name: str | None = key_column,
    ) -> dict[str, object]:
        return generic_sync(
            client,
            board_id,
            cache_path,
            query=query_text,
            transform=transform_type,
            key_column=key_column_name,
        )

    return MondaySyncDefinition(
        id=definition_id,
        namespace=namespace,
        label=label,
        description=description,
        cache_filename=cache_filename,
        handler=handler,
        legacy_board_id_key=legacy_key,
        shipped=False,
        board_id=board_id,
    )


def _definition_query(payload: dict[str, Any], path: Path) -> str:
    query = str(payload.get("query") or "").strip()
    query_file = str(payload.get("queryFile") or "").strip()
    if query and query_file:
        raise _invalid_definition(path, "provide either query or queryFile, not both")
    if query:
        return query
    if not query_file:
        raise _invalid_definition(path, "query or queryFile is required")
    resolved = (path.parent / query_file).resolve()
    try:
        return resolved.read_text(encoding="utf-8")
    except Exception as exc:
        raise _invalid_definition(path, f"could not read queryFile: {query_file}") from exc


def _definition_transform(
    payload: dict[str, Any], path: Path
) -> tuple[GenericTransformType, str | None]:
    raw_transform = payload.get("transform")
    if isinstance(raw_transform, str):
        transform_type = raw_transform
        key_column = None
    elif isinstance(raw_transform, dict):
        transform_type = str(raw_transform.get("type") or "").strip()
        key_column = str(raw_transform.get("keyColumn") or "").strip() or None
    else:
        raise _invalid_definition(path, "transform is required")

    if transform_type not in {"raw_items", "items_by_group", "items_by_key_column"}:
        raise _invalid_definition(path, f"unsupported transform: {transform_type}")
    if transform_type == "items_by_key_column" and not key_column:
        raise _invalid_definition(
            path, "items_by_key_column requires transform.keyColumn"
        )
    return transform_type, key_column  # type: ignore[return-value]


def _required_text(payload: dict[str, Any], key: str, path: Path) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise _invalid_definition(path, f"{key} is required")
    return value


def _optional_int(value: Any, path: Path, key: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise _invalid_definition(path, f"{key} must be a number") from exc


def _invalid_definition(path: Path, detail: str) -> FerpError:
    return FerpError(
        code="monday_definition_invalid",
        message="Monday definition is invalid.",
        detail=f"{path}: {detail}",
    )
