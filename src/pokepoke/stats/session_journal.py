"""Write-ahead journal for WorkItemSession RAII pattern.

Provides crash-safe persistence by recording session state BEFORE each action.
Journals survive crashes and can be scanned by SessionReconciler for recovery.

Journal file location: .pokepoke/sessions/{item_id}.json
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

logger = logging.getLogger(__name__)

# Journal directory relative to the project root
_SESSIONS_DIR = Path(".pokepoke") / "sessions"


class SessionPhase(StrEnum):
    """Phase of a WorkItemSession lifecycle.

    Phases are recorded in the write-ahead journal so that SessionReconciler
    can determine what cleanup is needed after a crash.
    """

    PENDING = "PENDING"
    ASSIGNING = "ASSIGNING"
    BRANCHING = "BRANCHING"
    CREATING_WT = "CREATING_WT"
    ACTIVE = "ACTIVE"
    MERGING = "MERGING"
    CLEANING = "CLEANING"
    CLOSED = "CLOSED"
    UNWINDING = "UNWINDING"
    ABANDONED = "ABANDONED"


@dataclass
class SessionJournal:
    """Persisted record of an in-progress WorkItemSession.

    Fields match those written to .pokepoke/sessions/{item_id}.json.
    """

    item_id: str
    branch: str
    worktree_path: str
    agent_name: str
    pid: int
    started_at: str  # ISO-8601 UTC
    phase: str  # SessionPhase value


def _journal_path(item_id: str, sessions_dir: Path | None = None) -> Path:
    """Return the path for a journal file."""
    base = sessions_dir if sessions_dir is not None else _SESSIONS_DIR
    return base / f"{item_id}.json"


def write_journal(  # noqa: PLR0913
    item_id: str,
    branch: str,
    worktree_path: str,
    agent_name: str,
    phase: SessionPhase,
    pid: int | None = None,
    started_at: str | None = None,
    sessions_dir: Path | None = None,
) -> Path:
    """Write (or overwrite) the journal file for a session.

    Must be called BEFORE taking the action described by *phase* to satisfy
    the write-ahead guarantee.

    Args:
        item_id: Beads item ID being processed.
        branch: Git branch name for this session.
        worktree_path: Absolute path to the worktree directory.
        agent_name: Name of the agent handling this session.
        phase: Current phase that is about to begin.
        pid: Process ID; defaults to the current process.
        started_at: ISO-8601 timestamp; defaults to now (UTC).
        sessions_dir: Override for the sessions directory (used in tests).

    Returns:
        Path to the written journal file.
    """
    journal = SessionJournal(
        item_id=item_id,
        branch=branch,
        worktree_path=str(worktree_path),
        agent_name=agent_name,
        pid=pid if pid is not None else os.getpid(),
        started_at=started_at if started_at is not None else _utcnow_iso(),
        phase=phase.value,
    )

    path = _journal_path(item_id, sessions_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write atomically via a temp file, then rename.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(journal), indent=2), encoding="utf-8")
    tmp.replace(path)

    logger.debug("Journal written: %s phase=%s", path, phase.value)
    return path


def delete_journal(item_id: str, sessions_dir: Path | None = None) -> bool:
    """Delete the journal file for a session.

    Should only be called after ALL cleanup steps in __exit__ complete
    successfully (write-ahead guarantee: journal survives until clean close).

    Args:
        item_id: Beads item ID whose journal should be deleted.
        sessions_dir: Override for the sessions directory (used in tests).

    Returns:
        True if the file was deleted, False if it did not exist.
    """
    path = _journal_path(item_id, sessions_dir)
    try:
        path.unlink()
        logger.debug("Journal deleted: %s", path)
        return True
    except FileNotFoundError:
        return False


def load_journal(item_id: str, sessions_dir: Path | None = None) -> SessionJournal | None:
    """Load a journal file for a given item_id.

    Args:
        item_id: Beads item ID to look up.
        sessions_dir: Override for the sessions directory (used in tests).

    Returns:
        SessionJournal if the file exists and is valid, otherwise None.
    """
    path = _journal_path(item_id, sessions_dir)
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SessionJournal(
            item_id=data["item_id"],
            branch=data["branch"],
            worktree_path=data["worktree_path"],
            agent_name=data["agent_name"],
            pid=int(data["pid"]),
            started_at=data["started_at"],
            phase=data["phase"],
        )
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to parse journal %s: %s", path, exc)
        return None


def list_abandoned_journals(sessions_dir: Path | None = None) -> list[SessionJournal]:
    """Return all valid journal files for SessionReconciler consumption.

    Includes journals in any phase (reconciler decides which to act on).
    Skips any files that cannot be parsed (logs a warning).

    Args:
        sessions_dir: Override for the sessions directory (used in tests).

    Returns:
        List of SessionJournal objects, one per parseable journal file.
    """
    base = sessions_dir if sessions_dir is not None else _SESSIONS_DIR
    if not base.exists():
        return []

    journals: list[SessionJournal] = []
    for path in sorted(base.glob("*.json")):
        item_id = path.stem
        journal = load_journal(item_id, sessions_dir)
        if journal is not None:
            journals.append(journal)

    return journals


def _utcnow_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()  # noqa: UP017
