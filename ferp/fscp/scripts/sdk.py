from __future__ import annotations

import itertools
import json
import os
import traceback
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Literal,
    Mapping,
    Sequence,
    TypedDict,
    TypeVar,
    cast,
    overload,
)

from ferp.fscp.protocol.messages import Message, MessageType
from ferp.fscp.protocol.validator import Endpoint, ProtocolValidator
from ferp.fscp.scripts.runtime.errors import FatalScriptError, ProtocolViolation
from ferp.fscp.scripts.runtime.io import read_message, try_read_message, write_message


class ScriptCancelled(FatalScriptError):
    """Raised when the host requests cancellation."""


@dataclass(frozen=True)
class ScriptContext:
    """Normalized data supplied by the host at script startup."""

    target_path: Path
    target_kind: Literal["file", "directory"]
    params: Dict[str, Any]
    environment: "ScriptEnvironment"


class ScriptEnvironmentApp(TypedDict):
    name: str
    version: str
    build: str


class ScriptEnvironmentHost(TypedDict):
    platform: str
    os: str
    os_version: str
    arch: str
    python: str


class ScriptEnvironmentPaths(TypedDict):
    app_root: str
    cwd: str
    cache_root: str
    cache_dir: str
    settings_file: str


class ScriptEnvironment(TypedDict):
    app: ScriptEnvironmentApp
    host: ScriptEnvironmentHost
    paths: ScriptEnvironmentPaths


class BoolField(TypedDict):
    id: str
    type: Literal["bool"]
    label: str
    default: bool


class MultiSelectField(TypedDict):
    id: str
    type: Literal["multi_select"]
    label: str
    options: Sequence[str]
    default: Sequence[str]


class SelectField(TypedDict):
    id: str
    type: Literal["select"]
    label: str
    options: Sequence[str]
    default: str


_InputPayloadT = TypeVar("_InputPayloadT", bound=Mapping[str, object])


class ScriptAPI:
    """High-level helpers for authoring FSCP scripts."""

    def __init__(self, transport: "_Transport") -> None:
        self._transport = transport
        self._request_counter = itertools.count(1)
        self._exited = False
        self._log_level = _normalize_log_level(
            os.environ.get("FERP_SCRIPT_LOG_LEVEL", "info")
        )
        self._cleanup_hooks: list[Callable[[], None]] = []
        self._cleanup_ran = False

    @property
    def exited(self) -> bool:
        return self._exited

    def log(self, level: str, message: str) -> None:
        self._ensure_running()
        if not _should_emit_log(level, self._log_level):
            return
        payload = {"level": level, "message": message}
        self._transport.send(MessageType.LOG, payload)

    def progress(
        self,
        *,
        current: float,
        total: float | None = None,
        unit: str | None = None,
        message: str | None = None,
        every: int | None = None,
    ) -> None:
        self._ensure_running()
        if every is not None:
            if every <= 0:
                every = 1
            if not (
                current == 1
                or (total is not None and current == total)
                or current % every == 0
            ):
                return
        payload: Dict[str, Any] = {"current": current}
        if total is not None:
            payload["total"] = total
        if unit is not None:
            payload["unit"] = unit
        if message is not None:
            payload["message"] = message
        self._transport.send(MessageType.PROGRESS, payload)

    def emit_result(self, payload: Mapping[str, Any]) -> None:
        self._ensure_running()
        self._transport.send(MessageType.RESULT, dict(payload))

    def register_cleanup(self, func: Callable[[], None]) -> None:
        """Register a cleanup callback to run on cancellation or exit."""
        if not callable(func):
            raise ValueError("Cleanup hook must be callable.")
        self._cleanup_hooks.append(func)

    def check_cancel(self) -> None:
        """Raise ScriptCancelled if the host has requested cancellation."""
        self._transport.poll_cancel()
        if self._transport.is_cancelled():
            raise ScriptCancelled("Host cancelled script.")

    def is_cancelled(self) -> bool:
        """Return True if a cancellation request has been received."""
        return self._transport.is_cancelled()

    def request_input(
        self,
        prompt: str,
        *,
        default: str | None = None,
        secret: bool = False,
        id: str | None = None,
        mode: Literal["input", "confirm"] = "input",
        fields: Sequence[Mapping[str, Any]] | None = None,
        suggestions: Sequence[str] | None = None,
        show_text_input: bool | None = None,
        text_input_style: Literal["single_line", "multiline"] | None = None,
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
        if suggestions:
            request["suggestions"] = list(suggestions)
        if show_text_input is not None:
            request["show_text_input"] = show_text_input
        if text_input_style is not None:
            request["text_input_style"] = text_input_style

        self._transport.send(MessageType.REQUEST_INPUT, request)
        return self._transport.wait_for_input(request_id)

    @overload
    def request_input_json(
        self,
        prompt: str,
        *,
        default: str | None = None,
        secret: bool = False,
        id: str | None = None,
        fields: Sequence[BoolField | MultiSelectField | SelectField] | None = None,
        suggestions: Sequence[str] | None = None,
        show_text_input: bool | None = None,
        text_input_style: Literal["single_line", "multiline"] | None = None,
    ) -> Dict[str, str | bool | list[str]]: ...

    @overload
    def request_input_json(
        self,
        prompt: str,
        *,
        default: str | None = None,
        secret: bool = False,
        id: str | None = None,
        fields: Sequence[BoolField | MultiSelectField | SelectField] | None = None,
        suggestions: Sequence[str] | None = None,
        show_text_input: bool | None = None,
        text_input_style: Literal["single_line", "multiline"] | None = None,
        payload_type: type[_InputPayloadT],
    ) -> _InputPayloadT: ...

    def request_input_json(
        self,
        prompt: str,
        *,
        default: str | None = None,
        secret: bool = False,
        id: str | None = None,
        fields: Sequence[BoolField | MultiSelectField | SelectField] | None = None,
        suggestions: Sequence[str] | None = None,
        show_text_input: bool | None = None,
        text_input_style: Literal["single_line", "multiline"] | None = None,
        payload_type: type[_InputPayloadT] | None = None,
    ) -> Dict[str, str | bool | list[str]] | _InputPayloadT:
        if fields:
            self._validate_fields(fields)
        raw = self.request_input(
            prompt,
            default=default,
            secret=secret,
            id=id,
            mode="input",
            fields=fields,
            suggestions=suggestions,
            show_text_input=show_text_input,
            text_input_style=text_input_style,
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Expected JSON object for request_input_json response.")
        if fields:
            self._validate_payload_fields(payload, fields)
        if payload_type is not None:
            return cast(_InputPayloadT, payload)
        return payload

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

    def _validate_fields(
        self,
        fields: Sequence[BoolField | MultiSelectField | SelectField],
    ) -> None:
        for field in fields:
            field_id = field.get("id")
            label = field.get("label")
            field_type = field.get("type")
            if not isinstance(field_id, str) or not field_id:
                raise ValueError("Fields must define a non-empty 'id'.")
            if not isinstance(label, str) or not label:
                raise ValueError(
                    f"Field '{field_id}' must define a non-empty 'label'."
                )
            if field_type == "bool":
                default = field.get("default")
                if not isinstance(default, bool):
                    raise ValueError(
                        f"Boolean field '{field_id}' must define a boolean 'default'."
                    )
                continue
            if field_type == "multi_select":
                options = field.get("options")
                default = field.get("default", [])
                if not isinstance(options, Sequence) or not options:
                    raise ValueError(
                        f"Multi-select field '{field_id}' must define non-empty 'options'."
                    )
                if any(not isinstance(item, str) or not item for item in options):
                    raise ValueError(
                        f"Multi-select field '{field_id}' options must be strings."
                    )
                if not isinstance(default, Sequence):
                    raise ValueError(
                        f"Multi-select field '{field_id}' must define a list 'default'."
                    )
                if any(not isinstance(item, str) for item in default):
                    raise ValueError(
                        f"Multi-select field '{field_id}' default values must be strings."
                    )
                continue
            if field_type == "select":
                options = field.get("options")
                default = field.get("default")
                if not isinstance(options, Sequence) or not options:
                    raise ValueError(
                        f"Select field '{field_id}' must define non-empty 'options'."
                    )
                if any(not isinstance(item, str) or not item for item in options):
                    raise ValueError(
                        f"Select field '{field_id}' options must be strings."
                    )
                if default is not None and not isinstance(default, str):
                    raise ValueError(
                        f"Select field '{field_id}' default must be a string."
                    )
                continue
            raise ValueError(
                "request_input_json only supports bool, multi_select, or select fields; "
                f"received {field_type!r}."
            )

    def _validate_payload_fields(
        self,
        payload: Dict[str, Any],
        fields: Sequence[BoolField | MultiSelectField | SelectField],
    ) -> None:
        value = payload.get("value")
        if not isinstance(value, str):
            raise ValueError("request_input_json payload must include string 'value'.")
        for field in fields:
            field_id = field["id"]
            if field_id not in payload:
                raise ValueError(
                    f"request_input_json payload missing field '{field_id}'."
                )
            field_type = field.get("type")
            if field_type == "bool":
                if not isinstance(payload[field_id], bool):
                    raise ValueError(
                        f"request_input_json field '{field_id}' must be a boolean."
                    )
                continue
            if field_type == "multi_select":
                values = payload[field_id]
                if not isinstance(values, list):
                    raise ValueError(
                        f"request_input_json field '{field_id}' must be a list."
                    )
                if any(not isinstance(item, str) for item in values):
                    raise ValueError(
                        f"request_input_json field '{field_id}' must contain strings."
                    )
                continue
            if field_type == "select":
                value = payload[field_id]
                if not isinstance(value, str):
                    raise ValueError(
                        f"request_input_json field '{field_id}' must be a string."
                    )
                continue
            raise ValueError(
                f"request_input_json field '{field_id}' has unknown type '{field_type}'."
            )

    def exit(self, *, code: int = 0) -> None:
        if self._exited:
            return
        self._transport.send(MessageType.EXIT, {"code": code})
        self._exited = True

    def _ensure_running(self) -> None:
        if self._exited:
            raise RuntimeError("Cannot interact with host after exit has been sent.")

    def _run_cleanup_hooks(self) -> None:
        if self._cleanup_ran:
            return
        self._cleanup_ran = True
        for hook in self._cleanup_hooks:
            try:
                hook()
            except Exception as exc:
                if not self._exited:
                    self.log("error", f"Cleanup hook failed: {exc}")


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
        self._cancelled = False

    def is_cancelled(self) -> bool:
        return self._cancelled

    def send(self, msg_type: MessageType, payload: Mapping[str, Any]) -> None:
        msg = Message(type=msg_type, payload=dict(payload))
        self._validator.validate(msg, sender=Endpoint.SCRIPT)
        write_message(msg.to_dict())

    def poll_cancel(self) -> None:
        if self._cancelled:
            return
        msg = self._try_receive()
        if msg is None:
            return
        if msg.type is MessageType.CANCEL:
            self._cancelled = True
            return
        # Ignore unexpected non-cancel messages in polling mode.

    def expect(self, expected: MessageType) -> Message:
        msg = self.receive()
        if msg.type is expected:
            return msg
        if msg.type is MessageType.CANCEL:
            self._cancelled = True
            raise ScriptCancelled("Host cancelled script before it started.")
        raise ProtocolViolation(
            f"Expected '{expected.value}', received '{msg.type.value}'."
        )

    def receive(self) -> Message:
        raw = read_message()
        msg = Message.from_dict(raw)
        self._validator.validate(msg, sender=Endpoint.HOST)
        if msg.type is MessageType.CANCEL:
            self._cancelled = True
        return msg

    def _try_receive(self) -> Message | None:
        raw = try_read_message()
        if raw is None:
            return None
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
                self._cancelled = True
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
            api._run_cleanup_hooks()
            api.exit(code=1)
            return
        except Exception:
            tb = traceback.format_exc().rstrip()
            api.log("error", tb)
            api._run_cleanup_hooks()
            api.exit(code=1)
            return

        api._run_cleanup_hooks()
        api.exit(code=0)


def _build_context(init_msg: Message) -> ScriptContext:
    payload = init_msg.payload or {}
    target = payload.get("target") or {}
    path = Path(str(target.get("path", ".")))
    kind = str(target.get("kind", "file"))
    if kind not in {"file", "directory"}:
        kind = "file"

    params = dict(payload.get("params") or {})
    environment = cast(ScriptEnvironment, payload.get("environment") or {})

    return ScriptContext(
        target_path=path,
        target_kind=cast(Literal["file", "directory"], kind),
        params=params,
        environment=environment,
    )


_LOG_LEVELS: dict[str, int] = {
    "debug": 10,
    "info": 20,
    "warn": 30,
    "error": 40,
}


def _normalize_log_level(level: str | None) -> int:
    if not level:
        return _LOG_LEVELS["info"]
    return _LOG_LEVELS.get(str(level).strip().lower(), _LOG_LEVELS["info"])


def _should_emit_log(level: str, minimum: int) -> bool:
    return _normalize_log_level(level) >= minimum


__all__ = [
    "BoolField",
    "MultiSelectField",
    "ScriptEnvironment",
    "ScriptEnvironmentApp",
    "ScriptEnvironmentHost",
    "ScriptEnvironmentPaths",
    "ScriptAPI",
    "ScriptCallable",
    "ScriptCancelled",
    "ScriptContext",
    "run",
    "script",
]
