from __future__ import annotations

import contextlib
import io
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from multiprocessing import util as mp_util
from multiprocessing.connection import Connection
from pathlib import Path
from runpy import run_path
from threading import Lock
from typing import IO, Any, Callable, Literal, cast

from ferp.core.config import get_runtime_config
from ferp.core.paths import SETTINGS_FILENAME
from ferp.fscp.host import Host
from ferp.fscp.host.managed_process import WorkerFn
from ferp.fscp.host.process_registry import (
    ProcessMetadata,
    ProcessRegistry,
)
from ferp.fscp.protocol.messages import Message, MessageDirection, MessageType
from ferp.fscp.protocol.state import HostState
from ferp.fscp.scripts.runtime.io import configure_connection
from ferp.fscp.transcript.events import TranscriptEvent
from ferp.services.scripts import ScriptExecutionContext


def _patch_spawnv_passfds() -> None:
    """Work around macOS passing invalid fds to spawnv."""
    original_spawn = mp_util.spawnv_passfds

    def safe_spawn(exe, args, passfds):  # type: ignore[override]
        filtered = tuple(fd for fd in passfds if isinstance(fd, int) and fd >= 0)
        return original_spawn(exe, args, filtered)

    mp_util.spawnv_passfds = safe_spawn  # type: ignore[assignment]


_patch_spawnv_passfds()


def _read_app_version() -> str:
    try:
        from ferp.__version__ import __version__
    except Exception:
        return "unknown"
    return __version__


def _read_build_label() -> str:
    if get_runtime_config().dev_config:
        return "dev"
    return "release"


def _read_os_version() -> str:
    if sys.platform == "darwin":
        mac_version = platform.mac_ver()[0]
        return mac_version or platform.release()
    if sys.platform.startswith("win"):
        return platform.version()
    return platform.release()


def _build_environment(
    app_root: Path,
    cache_dir: Path,
    namespace: str | None,
    settings_file: Path,
) -> dict[str, Any]:
    """Build the SDK environment payload for script initialization."""
    cache_root = cache_dir
    if namespace:
        cache_dir = cache_root / namespace
        cache_dir.mkdir(parents=True, exist_ok=True)
    return {
        "app": {
            "name": "ferp",
            "version": _read_app_version(),
            "build": _read_build_label(),
        },
        "host": {
            "platform": sys.platform,
            "os": platform.system(),
            "os_version": _read_os_version(),
            "arch": platform.machine(),
            "python": platform.python_version(),
        },
        "paths": {
            "app_root": str(app_root),
            "cwd": str(Path.cwd()),
            "cache_root": str(cache_root),
            "cache_dir": str(cache_dir),
            "settings_file": str(settings_file),
        },
    }


class ScriptStatus(Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_INPUT = "waiting_input"


@dataclass(frozen=True)
class ScriptInputRequest:
    id: str
    prompt: str
    default: str | None = None
    secret: bool = False
    mode: Literal["input", "confirm"] = "input"
    fields: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    show_text_input: bool = True
    text_input_style: Literal["single_line", "multiline"] = "single_line"


@dataclass(frozen=True)
class ScriptResult:
    status: ScriptStatus
    transcript: list[TranscriptEvent] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    exit_code: int | None = None
    error: str | None = None
    input_request: ScriptInputRequest | None = None


@dataclass
class HostSession:
    context: ScriptExecutionContext
    host: Host
    pending_request: ScriptInputRequest | None = None


def _script_worker_entry(script_path: str, app_root: str, conn: Connection) -> None:
    os.chdir(app_root)
    configure_connection(conn)

    class _NullWriter(io.TextIOBase):
        def write(self, _s: str) -> int:
            return 0

        def flush(self) -> None:
            return None

    with (
        contextlib.redirect_stdout(cast(IO[str], _NullWriter())),
        contextlib.redirect_stderr(cast(IO[str], _NullWriter())),
    ):
        run_path(script_path, run_name="__main__")


class ScriptRunner:
    """Run FSCP-compatible scripts inside a managed Host."""

    _TERMINAL_STATES = {
        HostState.TERMINATED,
        HostState.ERR_PROTOCOL,
        HostState.ERR_TRANSPORT,
    }

    def __init__(
        self,
        app_root: Path,
        cache_dir: Path,
        progress_handler: Callable[[dict[str, Any]], None] | None = None,
        process_registry: ProcessRegistry | None = None,
        namespace_resolver: Callable[[], str | None] | None = None,
        settings_file: Path | None = None,
    ) -> None:
        self.app_root = app_root
        self.cache_dir = cache_dir
        self._session: HostSession | None = None
        self._lock = Lock()
        self._progress_handler = progress_handler
        self.process_registry = process_registry or ProcessRegistry()
        self._namespace_resolver = namespace_resolver
        self._settings_file = settings_file

    @property
    def active_script_name(self) -> str | None:
        session = self._session
        if session is None:
            return None
        return session.context.script.name

    @property
    def active_target(self) -> Path | None:
        session = self._session
        if session is None:
            return None
        return session.context.target_path

    @property
    def active_process_handle(self) -> str | None:
        session = self._session
        if session is None:
            return None
        return session.host.process_handle

    def start(self, context: ScriptExecutionContext) -> ScriptResult:
        worker = self._create_worker(context.script_path)
        metadata = ProcessMetadata(
            script_name=context.script.name,
            script_id=context.script.id,
            target_path=context.target_path,
        )
        host = Host(
            worker=worker,
            process_registry=self.process_registry,
            process_metadata=metadata,
        )
        session = HostSession(context=context, host=host)

        with self._lock:
            if self._session is not None:
                raise RuntimeError("A script is already running.")
            self._session = session

        try:
            host.start()
            namespace = self._namespace_resolver() if self._namespace_resolver else None
            settings_file = self._settings_file or (self.app_root / SETTINGS_FILENAME)
            environment = _build_environment(
                self.app_root, self.cache_dir, namespace, settings_file
            )
            init_payload = {
                "target": {
                    "path": str(context.target_path),
                    "kind": context.target_kind,
                },
                "params": {
                    "script": {
                        "id": context.script.id,
                        "name": context.script.name,
                        "version": context.script.version,
                        "path": str(context.script_path),
                    },
                },
                "environment": environment,
            }
            host.send(Message(type=MessageType.INIT, payload=init_payload))
            return self._drive_host(session)
        except Exception:
            with self._lock:
                self._session = None
            host.shutdown(force=True)
            raise

    def provide_input(self, value: str) -> ScriptResult:
        with self._lock:
            session = self._require_session()
            request = session.pending_request
            if request is None:
                raise RuntimeError("No pending input request.")
            payload = {"id": request.id, "value": value}
            session.pending_request = None
            host = session.host

        host.provide_input(payload)
        return self._drive_host(session)

    def abort(
        self,
        reason: str | None = None,
        *,
        graceful_timeout: float = 2.0,
    ) -> ScriptResult | None:
        with self._lock:
            session = self._session
            if session is None:
                return None
            self._session = None

        host = session.host
        try:
            if graceful_timeout > 0:
                try:
                    host.request_cancel()
                except Exception:
                    pass

                deadline = time.time() + graceful_timeout
                while time.time() < deadline:
                    host.poll()
                    updates = host.drain_progress_updates()
                    if updates:
                        for payload in updates:
                            self._publish_progress(payload)
                    if host.state in self._TERMINAL_STATES:
                        break
                    time.sleep(0.05)

            if host.state not in self._TERMINAL_STATES:
                host.shutdown(force=True)
        finally:
            return ScriptResult(
                status=ScriptStatus.FAILED,
                transcript=list(host.transcript),
                results=list(host.results),
                error=reason or "Script canceled.",
            )

    def _publish_progress(self, payload: dict[str, Any]) -> None:
        handler = self._progress_handler
        if handler:
            handler(payload)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drive_host(self, session: HostSession) -> ScriptResult:
        host = session.host

        while True:
            host.poll()
            updates = host.drain_progress_updates()
            if updates:
                for payload in updates:
                    self._publish_progress(payload)

            if host.state is HostState.AWAITING_INPUT:
                request = self._extract_input_request(host)
                session.pending_request = request
                return ScriptResult(
                    status=ScriptStatus.WAITING_INPUT,
                    transcript=list(host.transcript),
                    results=list(host.results),
                    input_request=request,
                )

            if host.state in self._TERMINAL_STATES:
                return self._finalize(session)

            time.sleep(0.05)

    def _finalize(self, session: HostSession) -> ScriptResult:
        host = session.host
        transcript = list(host.transcript)
        results = list(host.results)
        exit_code = self._extract_exit_code(transcript)
        state = host.state

        success = state is HostState.TERMINATED and (exit_code in (None, 0))
        status = ScriptStatus.COMPLETED if success else ScriptStatus.FAILED
        error = None if success else self._derive_error_message(host, exit_code)

        self._cleanup_session()

        return ScriptResult(
            status=status,
            transcript=transcript,
            results=results,
            exit_code=exit_code,
            error=error,
        )

    def _cleanup_session(self) -> None:
        with self._lock:
            self._session = None

    def _require_session(self) -> HostSession:
        session = self._session
        if session is None:
            raise RuntimeError("No active FSCP session.")
        return session

    def _create_worker(self, script_path: Path) -> WorkerFn:
        return partial(
            _script_worker_entry,
            str(script_path),
            str(self.app_root),
        )

    def _extract_input_request(self, host: Host) -> ScriptInputRequest:
        for event in reversed(host.transcript):
            msg = event.message
            if msg and msg.type is MessageType.REQUEST_INPUT:
                payload = msg.payload or {}
                raw_id = payload.get("id")
                if raw_id is None:
                    break
                mode = str(payload.get("mode", "input"))
                if mode not in {"input", "confirm"}:
                    mode = "input"
                raw_fields = payload.get("fields")
                fields: list[dict[str, Any]] = []
                if isinstance(raw_fields, list):
                    for item in raw_fields:
                        if isinstance(item, dict):
                            fields.append(dict(item))
                raw_suggestions = payload.get("suggestions")
                suggestions: list[str] = []
                if isinstance(raw_suggestions, list):
                    for value in raw_suggestions:
                        if isinstance(value, str) and value:
                            suggestions.append(value)
                show_text_input = payload.get("show_text_input", True)
                if not isinstance(show_text_input, bool):
                    show_text_input = True
                text_input_style = payload.get("text_input_style", "single_line")
                if text_input_style not in {"single_line", "multiline"}:
                    text_input_style = "single_line"
                return ScriptInputRequest(
                    id=str(raw_id),
                    prompt=str(payload.get("prompt", "")),
                    default=payload.get("default"),
                    secret=bool(payload.get("secret", False)),
                    mode=mode,  # type: ignore
                    fields=fields,
                    suggestions=suggestions,
                    show_text_input=show_text_input,
                    text_input_style=text_input_style,
                )

        raise RuntimeError("FSCP host entered input state without payload.")

    def _extract_exit_code(
        self,
        transcript: list[TranscriptEvent],
    ) -> int | None:
        for event in reversed(transcript):
            msg = event.message
            if msg and msg.type is MessageType.EXIT:
                payload = msg.payload or {}
                code = payload.get("code")
                if isinstance(code, int):
                    return code
        return None

    def _derive_error_message(
        self,
        host: Host,
        exit_code: int | None,
    ) -> str:
        detail = self._latest_system_note(host)

        if host.state is HostState.ERR_PROTOCOL:
            base = "Script failed due to an FSCP protocol violation."
        elif host.state is HostState.ERR_TRANSPORT:
            base = "Script failed due to a transport error."
        else:
            base = "Script exited with errors."

        if exit_code not in (None, 0):
            base = f"{base} (exit code {exit_code})"

        return f"{base} {detail}".strip()

    def _latest_system_note(self, host: Host) -> str:
        for event in reversed(host.transcript):
            if event.direction is MessageDirection.INTERNAL and event.raw:
                return event.raw
        return ""
