class ScriptError(Exception):
    """Base class for all script runtime errors."""


class ProtocolViolation(ScriptError):
    """Host sent an invalid or illegal protocol message."""


class InvalidStateTransition(ScriptError):
    """Message not allowed in current script state."""


class FatalScriptError(ScriptError):
    """Unhandled internal error."""
