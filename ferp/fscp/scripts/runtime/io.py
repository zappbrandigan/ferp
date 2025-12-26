import json
import sys
from multiprocessing.connection import Connection
from typing import Any, Dict, Optional

_connection: Optional[Connection] = None


def configure_connection(conn: Connection) -> None:
    """Attach a multiprocessing pipe connection for script IO."""
    global _connection
    _connection = conn


def read_message() -> Dict[str, Any]:
    """Read a single FSCP message from the configured transport."""
    if _connection is not None:
        try:
            payload = _connection.recv()
        except EOFError as exc:
            raise EOFError("Host closed pipe") from exc

        if not isinstance(payload, dict):
            raise ValueError("Invalid payload received from host")

        return payload

    line = sys.stdin.readline()
    if not line:
        raise EOFError("Host closed stdin")

    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from host: {exc}") from exc


def write_message(msg: Dict[str, Any]) -> None:
    """Write a single FSCP message to the configured transport."""
    if _connection is not None:
        _connection.send(msg)
        return

    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()
