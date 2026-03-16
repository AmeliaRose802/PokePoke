"""Tests for pokepoke.utils.constants module."""

from pathlib import Path

from pokepoke.utils.constants import (
    POKEPOKE_DIR,
    WORKTREE_DIR,
    BEADS_DIR,
    BRANCH_PREFIX,
    WORKTREE_TASK_PREFIX,
    STATUS_IN_PROGRESS,
    COMPLETED_STATUSES,
    HUMAN_IDENTIFIERS,
    DEFAULT_GIT_TIMEOUT,
    DEFAULT_ENCODING,
    DEFAULT_ENCODING_ERRORS,
    DEFAULT_AGENT_TIMEOUT,
)


def test_pokepoke_dir_is_path() -> None:
    assert isinstance(POKEPOKE_DIR, Path)
    assert str(POKEPOKE_DIR) == ".pokepoke"


def test_worktree_dir() -> None:
    assert WORKTREE_DIR == "worktrees"


def test_beads_dir() -> None:
    assert BEADS_DIR == ".beads"


def test_branch_prefix() -> None:
    assert BRANCH_PREFIX == "task/"


def test_worktree_task_prefix() -> None:
    assert WORKTREE_TASK_PREFIX == "task-"


def test_status_in_progress() -> None:
    assert STATUS_IN_PROGRESS == "in_progress"


def test_completed_statuses() -> None:
    assert isinstance(COMPLETED_STATUSES, tuple)
    assert "done" in COMPLETED_STATUSES
    assert "closed" in COMPLETED_STATUSES
    assert "resolved" in COMPLETED_STATUSES


def test_human_identifiers() -> None:
    assert isinstance(HUMAN_IDENTIFIERS, tuple)
    assert len(HUMAN_IDENTIFIERS) > 0
    assert all(isinstance(h, str) for h in HUMAN_IDENTIFIERS)


def test_default_git_timeout_is_int() -> None:
    assert isinstance(DEFAULT_GIT_TIMEOUT, int)
    assert DEFAULT_GIT_TIMEOUT > 0


def test_default_encoding() -> None:
    assert DEFAULT_ENCODING == "utf-8"


def test_default_encoding_errors() -> None:
    assert DEFAULT_ENCODING_ERRORS == "replace"


def test_default_agent_timeout() -> None:
    assert isinstance(DEFAULT_AGENT_TIMEOUT, float)
    assert DEFAULT_AGENT_TIMEOUT == 7200.0
