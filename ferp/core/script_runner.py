from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from multiprocessing import util as mp_util
from multiprocessing.connection import Connection
from pathlib import Path
from runpy import run_path
from threading import Lock
from typing import Any, Callable, Literal

from ferp.fscp.host import Host
from ferp.fscp.host.managed_process import WorkerFn
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
        progress_handler: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.app_root = app_root
        self._session: HostSession | None = None
        self._lock = Lock()
        self._progress_handler = progress_handler

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

    def start(self, context: ScriptExecutionContext) -> ScriptResult:
        worker = self._create_worker(context.script_path)
        host = Host(worker=worker)
        session = HostSession(context=context, host=host)

        with self._lock:
            if self._session is not None:
                raise RuntimeError("A script is already running.")
            self._session = session

        try:
            host.start()
            init_payload = {
                "target": {
                    "path": str(context.target_path),
                    "kind": context.target_kind,
                },
                "params": {
                    "args": list(context.args),
                    "script": {
                        "id": context.script.id,
                        "name": context.script.name,
                        "version": context.script.version,
                        "path": str(context.script_path),
                    },
                },
                "environment": {},
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

    def abort(self, reason: str | None = None) -> ScriptResult | None:
        with self._lock:
            session = self._session
            if session is None:
                return None
            self._session = None

        host = session.host
        try:
            host.shutdown(force=True)
        finally:
            return ScriptResult(
                status=ScriptStatus.FAILED,
                transcript=list(host.transcript),
                results=list(host.results),
                error=reason or "Script cancelled.",
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
                return ScriptInputRequest(
                    id=str(raw_id),
                    prompt=str(payload.get("prompt", "")),
                    default=payload.get("default"),
                    secret=bool(payload.get("secret", False)),
                    mode=mode, # type: ignore
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
