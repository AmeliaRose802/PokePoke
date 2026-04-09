"""Shared helpers for SDK event handler processing."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sdk_event_handler import SdkSessionStats

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
