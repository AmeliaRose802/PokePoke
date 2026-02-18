"""Utilities for loading historical agent logs from disk into the desktop UI."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# Keywords we look for when determining final agent status.
_SUCCESS_KEYWORDS = ("success", "succeeded", "completed", "done", "passed")
_FAILURE_KEYWORDS = ("fail", "failed", "failure", "error", "exception", "aborted", "cancelled", "canceled")


def load_historical_agents(
    log_roots: Iterable[Path],
    preview_limit: int,
    detail_limit: int,
) -> list[dict[str, Any]]:
    """Scan the provided log roots and load per-agent log snippets.

    Args:
        log_roots: Candidate directories that may contain per-run subdirectories.
        preview_limit: Maximum number of recent log lines to expose in agent cards.
        detail_limit: Maximum number of log lines to expose in the detail panel.

    Returns:
        A list of dictionaries compatible with AgentRegistry entries.
    """

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    effective_preview = max(1, preview_limit)
    effective_detail = max(effective_preview, detail_limit if detail_limit > 0 else effective_preview)

    for root in log_roots:
        root_path = Path(root)
        if not root_path.is_dir():
            continue

        run_dirs = _list_directories_sorted(root_path)
        for run_dir in run_dirs:
            run_id = run_dir.name
            for log_path in _iter_log_files(run_dir):
                record = _parse_agent_log(
                    log_path,
                    run_id,
                    preview_limit=effective_preview,
                    detail_limit=effective_detail,
                )
                if record is None:
                    continue
                agent_id = record["agent_id"]
                if agent_id in seen_ids:
                    continue
                seen_ids.add(agent_id)
                records.append(record)

    return records


def _list_directories_sorted(root: Path) -> list[Path]:
    """Return child directories sorted by their last write time."""
    entries: list[tuple[float, Path]] = []
    for candidate in root.iterdir():
        if not candidate.is_dir():
            continue
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        entries.append((mtime, candidate))
    entries.sort(key=lambda item: item[0])
    return [entry[1] for entry in entries]


def _iter_log_files(run_dir: Path) -> Iterable[Path]:
    """Yield *.log files under the run's items/ and maintenance/ subdirectories."""
    for subdir_name in ("items", "maintenance"):
        subdir = run_dir / subdir_name
        if not subdir.is_dir():
            continue
        log_entries: list[tuple[float, Path]] = []
        for path in subdir.glob("*.log"):
            if not path.is_file():
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            log_entries.append((mtime, path))
        log_entries.sort(key=lambda item: item[0])
        for _, path in log_entries:
            yield path


def _parse_agent_log(
    log_path: Path,
    run_id: str,
    preview_limit: int,
    detail_limit: int,
) -> dict[str, Any] | None:
    """Parse a single agent log file into metadata + limited log lines."""
    try:
        stat_info = log_path.stat()
    except OSError:
        return None

    preview_lines: deque[str] = deque(maxlen=preview_limit)
    detail_lines: deque[str] = deque(maxlen=detail_limit)

    work_item_id: str | None = None
    work_item_title: str | None = None
    agent_name: str | None = None
    started_at: float | None = None
    status: str | None = None

    try:
        with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\r\n")
                detail_lines.append(line)
                preview_lines.append(line)

                stripped = line.strip()
                lowered = stripped.lower()

                if work_item_id is None and stripped.startswith("Work Item:"):
                    work_item_id = stripped.split(":", 1)[1].strip() or None
                elif work_item_title is None and stripped.startswith("Title:"):
                    work_item_title = stripped.split(":", 1)[1].strip() or None
                elif agent_name is None and stripped.startswith("Agent:"):
                    agent_name = stripped.split(":", 1)[1].strip() or None
                elif started_at is None and stripped.startswith("Started:"):
                    started_at = _parse_timestamp(stripped.split(":", 1)[1])

                if lowered.startswith("status:"):
                    status_candidate = _status_from_text(stripped.split(":", 1)[1])
                    if status_candidate:
                        status = status_candidate
                elif "result:" in lowered:
                    # Prefer the last result line encountered in the log.
                    result_text = lowered.split("result:", 1)[1]
                    status_candidate = _status_from_text(result_text)
                    if status_candidate:
                        status = status_candidate
    except OSError:
        return None

    # Derive defaults
    final_status = status or "success"
    agent_display_name = agent_name or work_item_title or work_item_id or log_path.stem
    started_at = started_at or stat_info.st_mtime
    last_ts = stat_info.st_mtime

    agent_id = f"history::{run_id}::{log_path.stem}"

    return {
        "agent_id": agent_id,
        "name": agent_display_name,
        "iteration": 1,
        "status": final_status,
        "parent_agent_id": None,
        "model": None,
        "work_item_id": work_item_id,
        "work_item_title": work_item_title,
        "recent_logs": list(preview_lines),
        "log_lines": list(detail_lines),
        "started_at": started_at,
        "last_updated": last_ts,
        "last_log_at": last_ts,
    }


def _parse_timestamp(value: str) -> float | None:
    """Parse a ``YYYY-MM-DD HH:MM:SS`` timestamp string to epoch seconds."""
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return None


def _status_from_text(text: str) -> str | None:
    """Map free-form text to an agent status."""
    lowered = text.strip().lower()
    if not lowered:
        return None
    if any(keyword in lowered for keyword in _FAILURE_KEYWORDS):
        return "failed"
    if any(keyword in lowered for keyword in _SUCCESS_KEYWORDS):
        return "success"
    return None
