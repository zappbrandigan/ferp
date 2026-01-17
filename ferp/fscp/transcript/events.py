from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ferp.fscp.protocol.messages import Message, MessageDirection


@dataclass
class TranscriptEvent:
    timestamp: float
    direction: MessageDirection
    message: Optional[Message] = None
    raw: Optional[str] = None
