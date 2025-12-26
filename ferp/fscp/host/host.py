from __future__ import annotations

from typing import Optional
import time
import json

from ferp.fscp.host.managed_process import ManagedProcess, WorkerFn
from ferp.fscp.protocol.state import HostState
from ferp.fscp.protocol.messages import Message, MessageType, MessageDirection
from ferp.fscp.protocol.validator import ProtocolValidator, Endpoint
from ferp.fscp.transcript.events import TranscriptEvent


class Host:
    """
    Authoritative ferp.fscp host.
    """

    def __init__(
        self,
        worker: WorkerFn,
        timeout_ms: Optional[int] = None,
        validator: Optional[ProtocolValidator] = None,
    ) -> None:
        self.state: HostState = HostState.CREATED
        self.process = ManagedProcess(worker=worker)

        self.timeout_ms = timeout_ms
        self.validator = validator or ProtocolValidator()

        self.transcript: list[TranscriptEvent] = []
        self.results: list[dict] = []

        self._start_time: Optional[float] = None
        self._exit_seen = False
        self._progress_updates: list[dict] = []

        self._record_system("Host created")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self.state is not HostState.CREATED:
            raise RuntimeError("Host can only be started from CREATED")

        self.process.start()
        self._start_time = time.time()

        self._transition(HostState.PROCESS_STARTED)

    def poll(self) -> None:
        if self.state in {
            HostState.TERMINATED,
            HostState.ERR_PROTOCOL,
            HostState.ERR_TRANSPORT,
        }:
            return

        self._check_timeout()

        conn = self.process.connection
        if conn is not None:
            # -------------------------
            # Drain messages from the pipe
            # -------------------------
            while True:
                try:
                    has_data = conn.poll(0)
                except (OSError, ValueError) as exc:
                    if self._exit_seen:
                        self._cleanup_connection()
                        break
                    self._record_system(f"Connection poll failed: {exc}")
                    self._transition(HostState.ERR_TRANSPORT)
                    return

                if not has_data:
                    break

                try:
                    payload = conn.recv()
                except EOFError:
                    if self._exit_seen:
                        self._cleanup_connection()
                        break
                    self._record_system("Script connection closed unexpectedly")
                    self._transition(HostState.ERR_TRANSPORT)
                    return
                except Exception as exc:
                    self._record_system(f"Pipe read error: {exc}")
                    self._transition(HostState.ERR_TRANSPORT)
                    return

                if not isinstance(payload, dict):
                    self._record_incoming(raw=str(payload), msg=None)
                    self._record_system("Invalid payload received from script")
                    self._transition(HostState.ERR_PROTOCOL)
                    return

                raw = json.dumps(payload)
                try:
                    msg = Message.from_dict(payload)
                except Exception as exc:
                    self._record_incoming(raw=raw, msg=None)
                    self._record_system(f"Invalid ferp.fscp message: {exc}")
                    self._transition(HostState.ERR_PROTOCOL)
                    return

                self.receive(msg, raw=raw)


        # -------------------------
        # Process exit detection
        # -------------------------
        exit_code = self.process.poll_exit()
        if exit_code is None:
            return

        self._cleanup_connection()

        if not self._exit_seen:
            self._record_system("Process exited without exit message (abnormal)")

        self._transition(HostState.TERMINATED)

    def shutdown(self, *, force: bool = False) -> None:
        if self.state in {
            HostState.TERMINATED,
            HostState.ERR_PROTOCOL,
            HostState.ERR_TRANSPORT,
        }:
            return

        self._record_system("Shutdown initiated")
        self._transition(HostState.CANCELLING)

        if force:
            self.process.kill()
        else:
            self.process.terminate()

    # ------------------------------------------------------------------
    # Protocol IO
    # ------------------------------------------------------------------

    def send(self, msg: Message) -> None:
        self.validator.validate(msg, sender=Endpoint.HOST)

        if msg.type is MessageType.INIT:
            self._transition(HostState.INIT_SENT)

        self._dispatch(msg)
        self._record_outgoing(msg)

    def receive(self, msg: Message, *, raw: Optional[str] = None) -> None:
        self.validator.validate(msg, sender=Endpoint.SCRIPT)
        self._handle_incoming(msg)
        self._record_incoming(raw, msg)

    def provide_input(self, payload: dict) -> None:
        if self.state is not HostState.AWAITING_INPUT:
            raise RuntimeError("No input is currently awaited")

        msg = Message(type=MessageType.INPUT_RESPONSE, payload=payload)
        self._transition(HostState.RUNNING)
        self.send(msg)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch(self, msg: Message) -> None:
        conn = self.process.connection
        if conn is None:
            raise RuntimeError("Process connection unavailable")

        payload = msg.to_dict()
        try:
            conn.send(payload)
        except Exception as exc:
            self._record_system(f"Pipe send failed: {exc}")
            self._transition(HostState.ERR_TRANSPORT)
            raise

    def _cleanup_connection(self) -> None:
        conn = self.process.connection
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass
        finally:
            self.process.connection = None

    def _handle_incoming(self, msg: Message) -> None:
        if self.state in {
            HostState.TERMINATED,
            HostState.ERR_PROTOCOL,
            HostState.ERR_TRANSPORT,
        }:
            self._protocol_violation("Message received after termination")
            return

        if self.state is HostState.INIT_SENT:
            self._transition(HostState.RUNNING)

        match msg.type:
            case MessageType.LOG:
                return

            case MessageType.PROGRESS:
                payload = dict(msg.payload) if msg.payload else {}
                self._progress_updates.append(payload)
                return

            case MessageType.RESULT:
                if self._exit_seen:
                    self._protocol_violation("Result after exit")
                    return

                self.results.append(dict(msg.payload))
                return

            case MessageType.REQUEST_INPUT:
                if self.state is HostState.AWAITING_INPUT:
                    self._protocol_violation("Multiple outstanding input requests")
                    return
                
                if self.state is not HostState.RUNNING:
                    self._protocol_violation(f"'request_input' not allowed in state {self.state.name}")
                    return

                self._transition(HostState.AWAITING_INPUT)
                return

            case MessageType.EXIT:
                if self._exit_seen:
                    self._protocol_violation("Duplicate exit")
                    return
                self._exit_seen = True
                self._record_system(f"Exit received: {msg.payload}")
                self._transition(HostState.EXIT_RECEIVED)
                return

            case _:
                self._protocol_violation(f"Unhandled message: {msg.type.value}")
                return

    def _protocol_violation(self, reason: str) -> None:
        self._record_system(f"Protocol violation: {reason}")
        self._transition(HostState.ERR_PROTOCOL)
        try:
            self.process.kill()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # State + timeout
    # ------------------------------------------------------------------

    def _transition(self, new_state: HostState) -> None:
        self._record_system(f"State {self.state.name} → {new_state.name}")
        self.state = new_state

    def _check_timeout(self) -> None:
        if self.timeout_ms is None or self._start_time is None:
            return

        elapsed_ms = (time.time() - self._start_time) * 1000
        if elapsed_ms > self.timeout_ms:
            self._record_system("Execution timeout")
            self.shutdown(force=True)

    # ------------------------------------------------------------------
    # Transcript
    # ------------------------------------------------------------------

    def _record_incoming(
        self,
        raw: Optional[str],
        msg: Optional[Message],
    ) -> None:
        self.transcript.append(
            TranscriptEvent(
                timestamp=time.time(),
                direction=MessageDirection.RECV,
                raw=raw,
                message=msg,
            )
        )

    def _record_outgoing(self, msg: Message) -> None:
        self.transcript.append(
            TranscriptEvent(
                timestamp=time.time(),
                direction=MessageDirection.SEND,
                message=msg,
            )
        )

    def _record_system(self, note: str) -> None:
        self.transcript.append(
            TranscriptEvent(
                timestamp=time.time(),
                direction=MessageDirection.INTERNAL,
                raw=note,
            )
        )

    def drain_progress_updates(self) -> list[dict]:
        updates = self._progress_updates
        self._progress_updates = []
        return updates
