from typing import Optional

from ferp.fscp.protocol.messages import Message, MessageType
from ferp.fscp.protocol.validator import ProtocolValidator, Endpoint
from ferp.fscp.scripts.runtime.state import ScriptState
from ferp.fscp.scripts.runtime.io import read_message, write_message
from ferp.fscp.scripts.runtime.errors import (
    ProtocolViolation,
    InvalidStateTransition,
)


class ScriptRuntime:
    """
    Reference ferp.fscp script runtime.
    """

    def __init__(self) -> None:
        self.state: ScriptState = ScriptState.S0_BOOT
        self.validator = ProtocolValidator()
        self.pending_input_id: Optional[str] = None

    def run(self) -> None:
        """
        Main blocking event loop.
        """
        try:
            while self.state is not ScriptState.S5_EXITING:
                raw = read_message()
                msg = Message.from_dict(raw)

                # Validate schema-level correctness
                self.validator.validate(msg, sender=Endpoint.HOST)

                self._handle_message(msg)

        except EOFError:
            # Host disappeared — nothing more to do
            self.state = ScriptState.S_ERR_FATAL

        except Exception as exc:
            self.state = ScriptState.S_ERR_FATAL
            self._emit_fatal_error(exc)

        finally:
            self._emit_exit(code=1 if self.state.name.startswith("S_ERR") else 0)

    # -------------------------
    # Message handlers
    # -------------------------

    def _handle_message(self, msg: Message) -> None:
        if msg.type == MessageType.INIT:
            self._handle_init(msg)
        elif msg.type == MessageType.INPUT_RESPONSE:
            self._handle_input_response(msg)
        elif msg.type == MessageType.CANCEL:
            self._handle_cancel(msg)
        else:
            raise ProtocolViolation(f"Unhandled message type: {msg.type}")

    def _handle_init(self, msg: Message) -> None:
        if self.state is not ScriptState.S0_BOOT:
            raise InvalidStateTransition("init received outside BOOT")

        self.state = ScriptState.S1_READY

        # Example log
        self._emit_log("info", "Script initialized")

        # Transition into work
        self.state = ScriptState.S2_WORKING
        self._do_work()

    def _handle_input_response(self, msg: Message) -> None:
        if self.state is not ScriptState.S3_WAITING_INPUT:
            raise InvalidStateTransition("input_response while not waiting")

        payload = msg.payload or {}
        if payload.get("id") != self.pending_input_id:
            raise ProtocolViolation("input_response id mismatch")

        value = payload.get("value")
        self.pending_input_id = None

        self.state = ScriptState.S2_WORKING
        self._emit_result({"input": value})

    def _handle_cancel(self, msg: Message) -> None:
        if self.state in {ScriptState.S5_EXITING, ScriptState.S_ERR_FATAL}:
            return

        self.state = ScriptState.S4_CANCELLING
        self._emit_log("warn", "Cancellation requested")

        self.state = ScriptState.S5_EXITING

    # -------------------------
    # Script logic (example)
    # -------------------------

    def _do_work(self) -> None:
        """
        Example workload.
        """
        # Potentially use FatalScriptError here
        self.pending_input_id = "example"
        self.state = ScriptState.S3_WAITING_INPUT

        self._emit_request_input(
            id="example",
            prompt="Enter a value",
        )

    # -------------------------
    # Emit helpers
    # -------------------------

    def _emit_log(self, level: str, message: str) -> None:
        msg = Message(
            type=MessageType.LOG,
            payload={"level": level, "message": message},
        )
        write_message(msg.to_dict())


    def _emit_request_input(self, *, id: str, prompt: str) -> None:
        msg = Message(
            type=MessageType.REQUEST_INPUT,
            payload={"id": id, "prompt": prompt},
        )
        write_message(msg.to_dict())

    def _emit_result(self, payload: dict) -> None:
        msg = Message(
            type=MessageType.RESULT,
            payload=payload,
        )
        write_message(msg.to_dict())
        self.state = ScriptState.S5_EXITING

    def _emit_exit(self, *, code: int) -> None:
        msg = Message(
            type=MessageType.EXIT,
            payload={"code": code},
        )
        write_message(msg.to_dict())


    def _emit_fatal_error(self, exc: Exception) -> None:
        self._emit_log("error", str(exc))
