from enum import Enum
from dataclasses import dataclass
from typing import Any, Mapping

class MessageDirection(Enum):
    SEND = "send"
    RECV = "recv"
    INTERNAL = "interal"


class MessageType(Enum):
    # Host -> Script
    INIT = "init"
    INPUT_RESPONSE = "input_response"
    CANCEL = "cancel"

    # Script -> Host
    LOG = "log"
    PROGRESS = "progress"
    REQUEST_INPUT = "request_input"
    RESULT = "result"
    EXIT = "exit"

PROTOCOL = "ferp/1.0"

@dataclass(frozen=True, slots=True)
class Message:
    type: MessageType
    payload: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol": PROTOCOL,
            "type": self.type.value,
            "payload": dict(self.payload),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Message":
        if data.get("protocol") != PROTOCOL:
            raise ValueError(f"Unsupported protocol: {data.get('protocol')}")

        try:
            msg_type = MessageType(data["type"])
        except ValueError as exc:
            raise ValueError(f"Unknown message type: {data.get('type')}") from exc

        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")

        return Message(type=msg_type, payload=payload)
