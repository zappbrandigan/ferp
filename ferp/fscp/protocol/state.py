from __future__ import annotations

from enum import Enum, auto

class HostState(Enum):
    CREATED = auto()          # before subprocess spawn
    PROCESS_STARTED = auto()  # pipes attached, init not sent
    INIT_SENT = auto()        # init sent, no stdout yet
    RUNNING = auto()          # normal streaming
    AWAITING_INPUT = auto()   # request_input outstanding
    CANCELLING = auto()       # cancel sent
    EXIT_RECEIVED = auto()    # exit seen, process may still run
    TERMINATED = auto()       # process ended
    ERR_PROTOCOL = auto()
    ERR_TRANSPORT = auto()

                   
