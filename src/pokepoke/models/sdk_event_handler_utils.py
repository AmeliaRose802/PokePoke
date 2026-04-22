"""Shared helpers for SDK event handler processing."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sdk_event_handler import SdkSessionStats


class LineBuffer:
    """Accumulates streaming chunks and emits complete lines.

    Subprocess tool output arrives in arbitrary-sized chunks that may split
    mid-word.  This buffer reassembles them into complete lines (terminated
    by ``\\n``) so that display and logging output is human-readable.
    """

    __slots__ = ("_partial",)

    def __init__(self) -> None:
        self._partial: str = ""

    def add(self, text: str) -> list[str]:
        """Add a chunk and return any complete lines ready for output.

        Each returned string ends with ``\\n``.  Partial content is held
        until the next chunk completes the line or :meth:`flush` is called.
        """
        self._partial += text
        lines: list[str] = []
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            lines.append(line + "\n")
        return lines

    def flush(self) -> str | None:
        """Return any remaining partial content, or *None* if empty."""
        if self._partial:
            remaining = self._partial
            self._partial = ""
            return remaining
        return None


_STREAMING_ATTRS = (
    "stdout",
    "stderr",
    "output",
    "chunk",
    "delta",
    "delta_content",
    "content",
    "message",
    "text",
)


def iter_streaming_chunks(event_obj: Any) -> list[tuple[str, str]]:
    """Extract text chunks from tool streaming/progress events."""
    data = getattr(event_obj, "data", None)
    if data is None:
        return []
    chunks: list[tuple[str, str]] = []
    for attr in _STREAMING_ATTRS:
        val = getattr(data, attr, None)
        if isinstance(val, str) and val:
            chunks.append((attr, val))
    return chunks


def record_tool_output(stats: SdkSessionStats | dict[str, Any], text: str) -> None:
    """Record the latest tool output in session stats."""
    if not text or not text.strip():
        return
    now = time.monotonic()
    trimmed = text.strip()
    if len(trimmed) > 400:
        trimmed = "..." + trimmed[-400:]
    stats["last_tool_output_time"] = now
    stats["last_tool_output"] = trimmed
    stats["last_tool_activity_time"] = now
