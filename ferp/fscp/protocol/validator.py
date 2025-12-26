from typing import Set, Dict
from enum import Enum, auto
import json

from importlib.resources import files
from referencing import Registry, Resource
from jsonschema import Draft202012Validator

from ferp.fscp.protocol.messages import Message, MessageType


class ProtocolError(RuntimeError):
    """Raised on FSCP protocol violations."""


class Endpoint(Enum):
    HOST = auto()
    SCRIPT = auto()


class ProtocolValidator:
    """
    Enforces FSCP message directionality and schema validity.
    """

    HOST_TO_SCRIPT: Set[MessageType] = {
        MessageType.INIT,
        MessageType.INPUT_RESPONSE,
        MessageType.CANCEL,
    }

    SCRIPT_TO_HOST: Set[MessageType] = {
        MessageType.LOG,
        MessageType.PROGRESS,
        MessageType.REQUEST_INPUT,
        MessageType.RESULT,
        MessageType.EXIT,
    }

    ALL_MESSAGES: Set[MessageType] = HOST_TO_SCRIPT | SCRIPT_TO_HOST

    def __init__(self) -> None:
        self._registry = self._load_all_schemas()
        self._validators = self._load_validators()

    # ----------------------------
    # Schema loading
    # ----------------------------

    def _load_all_schemas(self) -> Registry:
        base = files("ferp.fscp.protocol.schemas") / "fscp" / "1.0"
        registry = Registry()

        for entry in base.iterdir():
            if not entry.name.endswith(".json"):
                continue

            schema = json.loads(entry.read_text())
            registry = registry.with_resource(
                schema["$id"],
                Resource.from_contents(schema),
            )

        return registry


    def _load_validators(self) -> Dict[MessageType, Draft202012Validator]:
        validators: Dict[MessageType, Draft202012Validator] = {}

        for name in [
            "init",
            "input_response",
            "cancel",
            "log",
            "progress",
            "request_input",
            "result",
            "exit",
        ]:
            schema = json.loads(
                (
                    files("ferp.fscp.protocol.schemas")
                    / "fscp"
                    / "1.0"
                    / f"{name}.json"
                ).read_text()
            )

            validators[MessageType[name.upper()]] = Draft202012Validator(
                schema=schema,
                registry=self._registry,
            )

        return validators

    # ----------------------------
    # Validation
    # ----------------------------

    def validate(self, msg: Message, *, sender: Endpoint) -> None:
        # Directionality
        if sender is Endpoint.HOST:
            if msg.type not in self.HOST_TO_SCRIPT:
                raise ProtocolError(
                    f"Host is not allowed to send '{msg.type.value}'"
                )

        elif sender is Endpoint.SCRIPT:
            if msg.type not in self.SCRIPT_TO_HOST:
                raise ProtocolError(
                    f"Script is not allowed to send '{msg.type.value}'"
                )

        else:
            raise ProtocolError("Unknown sender endpoint")

        # Schema validation
        try:
            validator = self._validators[msg.type]
        except KeyError:
            raise ProtocolError(
                f"No schema registered for '{msg.type.value}'"
            )

        instance = msg.to_dict()

        errors = sorted(validator.iter_errors(instance), key=str)
        if errors:
            err = errors[0]
            raise ProtocolError(
                f"Invalid {msg.type.value} message: {err.message}"
            )
