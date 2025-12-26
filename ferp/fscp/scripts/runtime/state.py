from enum import Enum, auto


class ScriptState(Enum):
    """
    Authoritative FSCP script-side state machine.
    """

    S0_BOOT = auto()          # Process started, nothing received
    S1_READY = auto()         # Valid init received
    S2_WORKING = auto()       # Performing work, emitting messages
    S3_WAITING_INPUT = auto() # request_input sent, awaiting input_response
    S4_CANCELLING = auto()    # cancel received, cleaning up
    S5_EXITING = auto()       # exit emitted, shutting down

    S_ERR_PROTOCOL = auto()   # Host violated protocol
    S_ERR_FATAL = auto()      # Unhandled exception
