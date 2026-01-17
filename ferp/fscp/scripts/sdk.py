from __future__ import annotations

import itertools
import traceback
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Literal, Mapping, cast

from ferp.fscp.protocol.messages import Message, MessageType
from ferp.fscp.protocol.validator import Endpoint, ProtocolValidator
from ferp.fscp.scripts.runtime.errors import FatalScriptError, ProtocolViolation
from ferp.fscp.scripts.runtime.io import read_message, write_message


class ScriptCancelled(FatalScriptError):
    """Raised when the host requests cancellation."""


@dataclass(frozen=True)
class ScriptContext:
    """Normalized data supplied by the host at script startup."""

    target_path: Path
    target_kind: Literal["file", "directory"]
    params: Dict[str, Any]
    environment: Dict[str, Any]

    @property
    def args(self) -> list[str]:
        raw = self.params.get("args")
        if isinstance(raw, list):
            return [str(item) for item in raw]
        return []


class ScriptAPI:
    """High-level helpers for authoring FSCP scripts."""

    def __init__(self, transport: "_Transport") -> None:
        self._transport = transport
        self._request_counter = itertools.count(1)
        self._exited = False

    @property
    def exited(self) -> bool:
        return self._exited

    def log(self, level: str, message: str) -> None:
        self._ensure_running()
        payload = {"level": level, "message": message}
        self._transport.send(MessageType.LOG, payload)

    def progress(
        self,
        *,
        current: float,
        total: float | None = None,
        unit: str | None = None,
    ) -> None:
        self._ensure_running()
        payload: Dict[str, Any] = {"current": current}
        if total is not None:
            payload["total"] = total
        if unit is not None:
            payload["unit"] = unit
        self._transport.send(MessageType.PROGRESS, payload)

    def emit_result(self, payload: Mapping[str, Any]) -> None:
        self._ensure_running()
        self._transport.send(MessageType.RESULT, dict(payload))

    def request_input(
        self,
        prompt: str,
        *,
        default: str | None = None,
        secret: bool = False,
        id: str | None = None,
        mode: Literal["input", "confirm"] = "input",
        fields: list[dict[str, Any]] | None = None,
        show_text_input: bool | None = None,
    ) -> str:
        self._ensure_running()
        request_id = id or f"input-{next(self._request_counter)}"
        request: Dict[str, Any] = {
            "id": request_id,
            "prompt": prompt,
            "mode": mode,
        }
        if default is not None:
            request["default"] = default
        if secret:
            request["secret"] = True
        if fields:
            request["fields"] = fields
        if show_text_input is not None:
            request["show_text_input"] = show_text_input

        self._transport.send(MessageType.REQUEST_INPUT, request)
        return self._transport.wait_for_input(request_id)

    def confirm(
        self,
        prompt: str,
        *,
        default: bool = False,
        id: str | None = None,
    ) -> bool:
        raw = self.request_input(
            prompt,
            default="true" if default else "false",
            id=id,
            mode="confirm",
        )
        return raw.strip().lower() in {"true", "1", "yes", "y"}

    def exit(self, *, code: int = 0) -> None:
        if self._exited:
            return
        self._transport.send(MessageType.EXIT, {"code": code})
        self._exited = True

    def _ensure_running(self) -> None:
        if self._exited:
            raise RuntimeError("Cannot interact with host after exit has been sent.")


ScriptCallable = Callable[[ScriptContext, ScriptAPI], None]


def run(script_fn: ScriptCallable) -> None:
    """Entrypoint for running an FSCP script function."""
    session = _ScriptSession(script_fn)
    session.run()


def script(func: ScriptCallable) -> Callable[[], None]:
    """Decorator that converts a (ctx, api) callable into an executable script."""

    @wraps(func)
    def wrapper() -> None:
        run(func)

    return wrapper


class _Transport:
    def __init__(self) -> None:
        self._validator = ProtocolValidator()

    def send(self, msg_type: MessageType, payload: Mapping[str, Any]) -> None:
        msg = Message(type=msg_type, payload=dict(payload))
        self._validator.validate(msg, sender=Endpoint.SCRIPT)
        write_message(msg.to_dict())

    def expect(self, expected: MessageType) -> Message:
        msg = self.receive()
        if msg.type is expected:
            return msg
        if msg.type is MessageType.CANCEL:
            raise ScriptCancelled("Host cancelled script before it started.")
        raise ProtocolViolation(
            f"Expected '{expected.value}', received '{msg.type.value}'."
        )

    def receive(self) -> Message:
        raw = read_message()
        msg = Message.from_dict(raw)
        self._validator.validate(msg, sender=Endpoint.HOST)
        return msg

    def wait_for_input(self, request_id: str) -> str:
        while True:
            msg = self.receive()
            if msg.type is MessageType.INPUT_RESPONSE:
                payload = msg.payload or {}
                if str(payload.get("id")) != request_id:
                    raise ProtocolViolation("Received mismatched input response.")
                value = payload.get("value")
                if not isinstance(value, str):
                    raise ProtocolViolation("Input response value must be a string.")
                return value

            if msg.type is MessageType.CANCEL:
                raise ScriptCancelled("Host cancelled script while awaiting input.")

            raise ProtocolViolation(
                f"Unexpected message '{msg.type.value}' while awaiting input."
            )


class _ScriptSession:
    def __init__(self, script_fn: ScriptCallable) -> None:
        self._script_fn = script_fn
        self._transport = _Transport()

    def run(self) -> None:
        api = ScriptAPI(self._transport)

        try:
            init_msg = self._transport.expect(MessageType.INIT)
        except EOFError:
            return
        except ScriptCancelled:
            api.exit(code=1)
            return

        context = _build_context(init_msg)

        try:
            self._script_fn(context, api)
        except ScriptCancelled as exc:
            api.log("warn", str(exc))
            api.exit(code=1)
            return
        except Exception:
            tb = traceback.format_exc().rstrip()
            api.log("error", tb)
            api.exit(code=1)
            return

        api.exit(code=0)


def _build_context(init_msg: Message) -> ScriptContext:
    payload = init_msg.payload or {}
    target = payload.get("target") or {}
    path = Path(str(target.get("path", ".")))
    kind = str(target.get("kind", "file"))
    if kind not in {"file", "directory"}:
        kind = "file"

    params = dict(payload.get("params") or {})
    environment = dict(payload.get("environment") or {})

    return ScriptContext(
        target_path=path,
        target_kind=cast(Literal["file", "directory"], kind),
        params=params,
        environment=environment,
    )


__all__ = [
    "ScriptAPI",
    "ScriptCallable",
    "ScriptCancelled",
    "ScriptContext",
    "run",
    "script",
]
