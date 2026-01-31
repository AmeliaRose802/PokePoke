"""Message types for thread-safe UI communication."""

from __future__ import annotations

from enum import Enum, auto
from dataclasses import dataclass
from typing import Any


class MessageType(Enum):
    """Types of messages that can be sent to the UI."""

    LOG = auto()
    WORK_ITEM = auto()
    STATS = auto()
    AGENT_NAME = auto()
    PROGRESS = auto()


@dataclass(frozen=True)
class UIMessage:
    """Immutable message for thread-safe UI updates."""

    msg_type: MessageType
    args: tuple[Any, ...]
