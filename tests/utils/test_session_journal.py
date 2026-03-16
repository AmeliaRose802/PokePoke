"""Tests for pokepoke.stats.session_journal."""

import json
import os
from pathlib import Path

import pytest

from pokepoke.stats.session_journal import (
    SessionJournal,
    SessionPhase,
    delete_journal,
    list_abandoned_journals,
    load_journal,
    write_journal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_phases() -> list[SessionPhase]:
    return list(SessionPhase)


# ---------------------------------------------------------------------------
# SessionPhase enum
# ---------------------------------------------------------------------------


class TestSessionPhase:
    def test_all_phases_present(self) -> None:
        names = {p.name for p in SessionPhase}
        expected = {
            "PENDING",
            "ASSIGNING",
            "BRANCHING",
            "CREATING_WT",
            "ACTIVE",
            "MERGING",
            "CLEANING",
            "CLOSED",
            "UNWINDING",
            "ABANDONED",
        }
        assert names == expected

    def test_phase_values_are_strings(self) -> None:
        for phase in SessionPhase:
            assert isinstance(phase.value, str)

    def test_phase_is_str_enum(self) -> None:
        # SessionPhase inherits str so it serialises cleanly as a string
        assert isinstance(SessionPhase.ACTIVE, str)
        assert SessionPhase.ACTIVE == "ACTIVE"


# ---------------------------------------------------------------------------
# write_journal
# ---------------------------------------------------------------------------


class TestWriteJournal:
    def test_creates_file(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-test1",
            branch="task-test1",
            worktree_path="/tmp/wt/test1",
            agent_name="agent-alpha",
            phase=SessionPhase.PENDING,
            pid=12345,
            started_at="2026-01-01T00:00:00+00:00",
            sessions_dir=sessions_dir,
        )
        assert (sessions_dir / "PokePoke-test1.json").exists()

    def test_json_content(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-abc",
            branch="task-abc",
            worktree_path="/worktrees/task-abc",
            agent_name="test-agent",
            phase=SessionPhase.ACTIVE,
            pid=9999,
            started_at="2026-02-01T12:00:00+00:00",
            sessions_dir=sessions_dir,
        )
        data = json.loads((sessions_dir / "PokePoke-abc.json").read_text())
        assert data["item_id"] == "PokePoke-abc"
        assert data["branch"] == "task-abc"
        assert data["worktree_path"] == "/worktrees/task-abc"
        assert data["agent_name"] == "test-agent"
        assert data["phase"] == "ACTIVE"
        assert data["pid"] == 9999
        assert data["started_at"] == "2026-02-01T12:00:00+00:00"

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        kw = dict(
            item_id="PokePoke-x",
            branch="task-x",
            worktree_path="/wt/x",
            agent_name="ag",
            sessions_dir=sessions_dir,
        )
        write_journal(**kw, phase=SessionPhase.ASSIGNING)
        write_journal(**kw, phase=SessionPhase.ACTIVE)
        data = json.loads((sessions_dir / "PokePoke-x.json").read_text())
        assert data["phase"] == "ACTIVE"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "deep" / "nested" / "sessions"
        write_journal(
            item_id="PokePoke-deep",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.PENDING,
            sessions_dir=sessions_dir,
        )
        assert (sessions_dir / "PokePoke-deep.json").exists()

    def test_returns_path(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        result = write_journal(
            item_id="PokePoke-ret",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.PENDING,
            sessions_dir=sessions_dir,
        )
        assert isinstance(result, Path)
        assert result.exists()

    def test_default_pid_is_current_process(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-pid",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.PENDING,
            sessions_dir=sessions_dir,
        )
        data = json.loads((sessions_dir / "PokePoke-pid.json").read_text())
        assert data["pid"] == os.getpid()

    def test_default_started_at_is_set(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-ts",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.PENDING,
            sessions_dir=sessions_dir,
        )
        data = json.loads((sessions_dir / "PokePoke-ts.json").read_text())
        assert data["started_at"]  # non-empty

    @pytest.mark.parametrize("phase", _all_phases())
    def test_all_phases_can_be_written(self, tmp_path: Path, phase: SessionPhase) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id=f"PokePoke-{phase.value}",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=phase,
            sessions_dir=sessions_dir,
        )
        data = json.loads((sessions_dir / f"PokePoke-{phase.value}.json").read_text())
        assert data["phase"] == phase.value


# ---------------------------------------------------------------------------
# delete_journal
# ---------------------------------------------------------------------------


class TestDeleteJournal:
    def test_deletes_existing(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-del",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.CLOSED,
            sessions_dir=sessions_dir,
        )
        result = delete_journal("PokePoke-del", sessions_dir=sessions_dir)
        assert result is True
        assert not (sessions_dir / "PokePoke-del.json").exists()

    def test_returns_false_when_missing(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        result = delete_journal("PokePoke-missing", sessions_dir=sessions_dir)
        assert result is False

    def test_idempotent(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-idem",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.CLOSED,
            sessions_dir=sessions_dir,
        )
        delete_journal("PokePoke-idem", sessions_dir=sessions_dir)
        # Second delete should not raise
        result = delete_journal("PokePoke-idem", sessions_dir=sessions_dir)
        assert result is False


# ---------------------------------------------------------------------------
# load_journal
# ---------------------------------------------------------------------------


class TestLoadJournal:
    def test_loads_existing(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-load",
            branch="task-load",
            worktree_path="/wt/load",
            agent_name="loader-agent",
            phase=SessionPhase.MERGING,
            pid=42,
            started_at="2026-03-01T00:00:00+00:00",
            sessions_dir=sessions_dir,
        )
        journal = load_journal("PokePoke-load", sessions_dir=sessions_dir)
        assert journal is not None
        assert journal.item_id == "PokePoke-load"
        assert journal.branch == "task-load"
        assert journal.worktree_path == "/wt/load"
        assert journal.agent_name == "loader-agent"
        assert journal.pid == 42
        assert journal.started_at == "2026-03-01T00:00:00+00:00"
        assert journal.phase == "MERGING"

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        assert load_journal("PokePoke-none", sessions_dir=sessions_dir) is None

    def test_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "PokePoke-bad.json").write_text("not-json", encoding="utf-8")
        assert load_journal("PokePoke-bad", sessions_dir=sessions_dir) is None

    def test_returns_none_for_missing_fields(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "PokePoke-incomplete.json").write_text(
            json.dumps({"item_id": "PokePoke-incomplete"}), encoding="utf-8"
        )
        assert load_journal("PokePoke-incomplete", sessions_dir=sessions_dir) is None

    def test_round_trip(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-rt",
            branch="rt-branch",
            worktree_path="/wt/rt",
            agent_name="rt-agent",
            phase=SessionPhase.ABANDONED,
            pid=1,
            started_at="2026-04-01T00:00:00+00:00",
            sessions_dir=sessions_dir,
        )
        journal = load_journal("PokePoke-rt", sessions_dir=sessions_dir)
        assert journal == SessionJournal(
            item_id="PokePoke-rt",
            branch="rt-branch",
            worktree_path="/wt/rt",
            agent_name="rt-agent",
            pid=1,
            started_at="2026-04-01T00:00:00+00:00",
            phase="ABANDONED",
        )


# ---------------------------------------------------------------------------
# list_abandoned_journals
# ---------------------------------------------------------------------------


class TestListAbandonedJournals:
    def test_empty_when_no_directory(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "does_not_exist"
        result = list_abandoned_journals(sessions_dir=sessions_dir)
        assert result == []

    def test_empty_when_directory_empty(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        result = list_abandoned_journals(sessions_dir=sessions_dir)
        assert result == []

    def test_returns_all_valid_journals(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        items = ["PokePoke-a1", "PokePoke-b2", "PokePoke-c3"]
        for item_id in items:
            write_journal(
                item_id=item_id,
                branch=f"branch-{item_id}",
                worktree_path=f"/wt/{item_id}",
                agent_name="ag",
                phase=SessionPhase.ACTIVE,
                sessions_dir=sessions_dir,
            )
        journals = list_abandoned_journals(sessions_dir=sessions_dir)
        assert len(journals) == 3
        found_ids = {j.item_id for j in journals}
        assert found_ids == set(items)

    def test_skips_invalid_files(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True)
        # One good journal
        write_journal(
            item_id="PokePoke-good",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.ACTIVE,
            sessions_dir=sessions_dir,
        )
        # One corrupted file
        (sessions_dir / "PokePoke-bad.json").write_text("{{invalid", encoding="utf-8")
        journals = list_abandoned_journals(sessions_dir=sessions_dir)
        assert len(journals) == 1
        assert journals[0].item_id == "PokePoke-good"

    def test_returns_journals_for_all_phases(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        for phase in SessionPhase:
            write_journal(
                item_id=f"PokePoke-{phase.value}",
                branch="b",
                worktree_path="/wt",
                agent_name="ag",
                phase=phase,
                sessions_dir=sessions_dir,
            )
        journals = list_abandoned_journals(sessions_dir=sessions_dir)
        assert len(journals) == len(SessionPhase)

    def test_ignores_non_json_files(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "README.txt").write_text("ignored", encoding="utf-8")
        write_journal(
            item_id="PokePoke-only",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.PENDING,
            sessions_dir=sessions_dir,
        )
        journals = list_abandoned_journals(sessions_dir=sessions_dir)
        assert len(journals) == 1

    def test_deleted_journal_not_listed(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        write_journal(
            item_id="PokePoke-del",
            branch="b",
            worktree_path="/wt",
            agent_name="ag",
            phase=SessionPhase.CLOSED,
            sessions_dir=sessions_dir,
        )
        delete_journal("PokePoke-del", sessions_dir=sessions_dir)
        assert list_abandoned_journals(sessions_dir=sessions_dir) == []
