from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any


def get_logger(name: str = "ferp") -> logging.Logger:
    return logging.getLogger(name)


def configure_logging(
    *,
    level: str = "info",
    format_name: str = "json",
    stream=None,
    log_dir: Path | None = None,
    filename: str = "host.log",
) -> None:
    normalized = level.strip().upper()
    level_value = getattr(logging, normalized, logging.INFO)
    if format_name == "json":
        formatter = logging.Formatter("%(message)s")
    else:
        formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
    if stream is None:
        env_dir = os.environ.get("FERP_LOG_DIR")
        if env_dir:
            log_dir = Path(env_dir)
        if log_dir is not None:
            log_dir.mkdir(parents=True, exist_ok=True)
            stream = open(log_dir / filename, "a", encoding="utf-8")
        else:
            handler = logging.NullHandler()
            root = logging.getLogger()
            root.setLevel(level_value)
            if not root.handlers:
                root.addHandler(handler)
            return
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(level_value)
    if not root.handlers:
        root.addHandler(handler)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, sort_keys=True))
