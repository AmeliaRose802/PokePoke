"""Tests for DesktopAPI state buffering and retrieval."""

import subprocess
import textwrap
from unittest.mock import Mock

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI
from pokepoke.desktop.desktop_api_ext import _discover_log_roots as _real_discover_log_roots
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


def test_initial_state_defaults() -> None:
    api = DesktopAPI()
    state = api.get_state()
    assert state["work_item"] is None
    assert state["agent_name"] == ""
    assert state["stats"] is None
    assert state["progress"] == {"active": False, "status": ""}
    assert state["log_count"] == 0


def test_historical_agent_logs_not_loaded(tmp_path, monkeypatch) -> None:
    """Historical agent loading is disabled to prevent memory bloat.

    seed_historical_agents is intentionally a no-op.  Past run logs should
    not be eagerly loaded into memory at startup.
    """
    logs_root = tmp_path / "logs"
    run_dir = logs_root / "20260218_120000_abcdef12"
    items_dir = run_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)

    log_content = textwrap.dedent(
        """\
        ================================================================================
        Work Item: PokePoke-9ikr
        Title: Persist and replay agent logs
        ================================================================================
        Agent: pokepoke_pro
        ================================================================================
        Started: 2026-02-18 12:34:56
        ================================================================================

        First historical line
        Second historical line

        ================================================================================
        Summary
        ================================================================================
        Completed: 2026-02-18 13:00:00
        Status: SUCCESS
        Agent requests: 2
        ================================================================================
        """
    )
    log_path = items_dir / "PokePoke-9ikr.log"
    log_path.write_text(log_content, encoding="utf-8")

    # Override the autouse fixture's patch to point to our test logs
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._discover_log_roots",
        lambda: [logs_root],
    )

    api = DesktopAPI()
    agents = api.get_state()["agents"]
    assert agents == [], "Historical agents should NOT be loaded at startup (memory fix)"


def test_push_log_and_incremental_reads() -> None:
    api = DesktopAPI()
    api.push_log("first", "orchestrator", None)
    api.push_log("second", "agent", "red")

    logs = api.get_new_logs()
    assert len(logs) == 2
    assert logs[0]["message"] == "first"
    assert logs[1]["target"] == "agent"

    # Subsequent call returns nothing new
    assert api.get_new_logs() == []


def test_get_all_logs_resets_index() -> None:
    api = DesktopAPI()
    api.push_log("one")
    api.push_log("two")

    _ = api.get_new_logs()
    all_logs = api.get_all_logs()
    assert len(all_logs) == 2

    # After get_all_logs, incremental should be empty
    assert api.get_new_logs() == []


def test_push_state_updates() -> None:
    api = DesktopAPI()
    api.push_work_item("item-1", "Title", "open", ["human-required"])
    api.push_agent_name("agent-1")

    stats = SessionStats(
        agent_stats=AgentStats(input_tokens=10, output_tokens=5),
        items_completed=1,
        completed_items_list=[
            BeadsWorkItem(id="item-1", title="Title", status="closed", priority=1, issue_type="task")
        ],
    )
    api.push_stats(stats, elapsed_time=12.5)
    api.push_progress(True, "Working")

    state = api.get_state()
    assert state["work_item"]["item_id"] == "item-1"
    assert state["work_item"]["labels"] == ["human-required"]
    assert state["agent_name"] == "agent-1"
    assert state["stats"]["elapsed_time"] == 12.5
    assert state["stats"]["agent_stats"]["input_tokens"] == 10
    assert state["stats"]["items_completed"] == 1
    assert state["stats"]["items_created"] == 0
    assert state["stats"]["net_items_delta"] == -1
    assert state["stats"]["lifetime_items_created"] == 0
    assert state["stats"]["lifetime_items_completed"] == 0
    assert state["stats"]["completed_items"][0]["id"] == "item-1"
    assert state["stats"]["created_items"] == []
    assert state["progress"] == {"active": True, "status": "Working"}


def test_add_remove_work_item_label(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PokePoke-1", "Title", "open", ["urgent"])

    mock_run = Mock(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext.subprocess.run", lambda *args, **kwargs: mock_run)

    added = api.add_work_item_label("PokePoke-1", "human-required")
    assert added["labels"] == ["urgent", "human-required"]
    assert added["success"] is True

    removed = api.remove_work_item_label("PokePoke-1", "urgent")
    assert removed["labels"] == ["human-required"]
    assert removed["success"] is True


def test_add_label_returns_error_on_called_process_error(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PokePoke-1", "Title", "open", ["urgent"])

    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=["bd", "update"],
            stderr="network unavailable",
        )

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._run_bd_with_retry", _raise)

    result = api.add_work_item_label("PokePoke-1", "human-required")
    assert result["success"] is False
    assert "network unavailable" in result["error"]
    # UI cache should remain unchanged
    state = api.get_state()
    assert state["work_item"]["labels"] == ["urgent"]


def test_remove_label_returns_error_on_timeout(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PokePoke-1", "Title", "open", ["urgent"])

    def _timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["bd", "update"], timeout=30, stderr="timed out")

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._run_bd_with_retry", _timeout)

    result = api.remove_work_item_label("PokePoke-1", "urgent")
    assert result["success"] is False
    assert "timed out" in result["error"]
    # Cached labels should not have been modified
    state = api.get_state()
    assert state["work_item"]["labels"] == ["urgent"]


def test_clear_logs() -> None:
    api = DesktopAPI()
    api.push_log("test")
    assert api.get_state()["log_count"] == 1
    api.clear_logs()
    assert api.get_state()["log_count"] == 0


def test_set_window() -> None:
    """set_window should store the window reference."""
    api = DesktopAPI()
    api.set_window("fake_window")
    assert api._window == "fake_window"


def test_get_work_item() -> None:
    """get_work_item should return the current work item."""
    api = DesktopAPI()
    assert api.get_work_item() is None
    api.push_work_item("item-1", "Title")
    assert api.get_work_item()["item_id"] == "item-1"


def test_push_log_buffer_trimming() -> None:
    """push_log should trim the buffer when it exceeds max size."""
    api = DesktopAPI()
    api._max_log_buffer = 5

    for i in range(8):
        api.push_log(f"msg-{i}")

    assert len(api._log_buffer) == 5
    assert api._log_buffer[0]["message"] == "msg-3"


def test_push_log_buffer_trim_adjusts_read_index() -> None:
    """Trimming should adjust read index to avoid returning stale entries."""
    api = DesktopAPI()
    api._max_log_buffer = 5

    for i in range(3):
        api.push_log(f"msg-{i}")
    api.get_new_logs()  # read_index = 3

    for i in range(5):
        api.push_log(f"msg-extra-{i}")

    new_logs = api.get_new_logs()
    assert len(new_logs) >= 0


def test_retry_attempt_creates_history_cards() -> None:
    """Each retry iteration should become its own card instead of overwriting."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", iteration=1, status="running")
    api.push_agent_log("agent-1", "first line")
    api.push_agent_status("agent-1", "Worker", iteration=2, status="running")

    agents = api.get_state()["agents"]
    assert len(agents) == 2
    history = next(agent for agent in agents if agent["is_history_entry"])
    current = next(agent for agent in agents if not agent["is_history_entry"])

    assert history["iteration"] == 1
    assert history["card_id"].endswith("::v1")
    assert history["recent_logs"] == ["first line"]
    assert current["iteration"] == 2
    assert current["card_id"].endswith("::v2")
    assert current["recent_logs"] == []


def test_get_agent_detail_handles_history_card_id() -> None:
    """Archived attempts should be fetchable via get_agent_detail(card_id)."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", iteration=1, status="running")
    api.push_agent_log("agent-1", "attempt log")
    api.push_agent_status("agent-1", "Worker", iteration=2, status="running")

    history = next(
        agent for agent in api.get_state()["agents"] if agent["is_history_entry"]
    )
    detail = api.get_agent_detail(history["card_id"])
    assert detail is not None
    assert detail["is_history_entry"] is True
    assert detail["recent_logs"] == ["attempt log"]


def test_gate_parent_card_tracks_retry_iteration() -> None:
    """Gate cards should stay linked to the specific attempt they validated."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", iteration=1, status="running")
    api.push_agent_status(
        "agent-1-gate-1",
        "Gate Agent",
        iteration=1,
        status="failed",
        parent_agent_id="agent-1",
    )
    api.push_agent_status("agent-1", "Worker", iteration=2, status="running")

    agents = api.get_state()["agents"]
    history = next(agent for agent in agents if agent["is_history_entry"])
    gate_card = next(agent for agent in agents if agent["agent_id"].startswith("agent-1-gate"))

    assert gate_card["parent_card_id"] == history["card_id"]


def test_agent_detail_caps_log_history() -> None:
    """Agent detail log_lines should be capped at 500 to prevent memory bloat."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "AgentOne")

    for i in range(3000):
        api.push_agent_log("agent-1", f"line-{i}")

    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert len(detail["recent_logs"]) == api._agent_max_log_lines  # preview still limited
    assert len(detail["log_lines"]) == 500  # capped to prevent memory bloat
    assert detail["log_lines"][0] == "line-2500"  # oldest retained line
    assert detail["log_lines"][-1] == "line-2999"


def test_get_model_leaderboard() -> None:
    """get_model_leaderboard should return model summary."""
    from unittest.mock import patch
    api = DesktopAPI()
    with patch("pokepoke.models.model_stats_store.get_model_summary", return_value={"test": 1}):
        result = api.get_model_leaderboard()
    assert result == {"test": 1}


def test_get_model_history_delegates() -> None:
    """get_model_history should proxy to model_history.load_model_history_entries and normalize keys."""
    from unittest.mock import patch

    api = DesktopAPI()
    # Mock raw data from model_history
    raw_data = [{"work_item_id": "A", "wall_time_seconds": 30.0, "quality_gates_passed": True}]

    with patch("pokepoke.models.model_history.load_model_history_entries", return_value=raw_data) as mock_history:
        history = api.get_model_history(limit=5)

    mock_history.assert_called_once_with(limit=5, repo_name="")

    # Verify normalization happened
    assert len(history) == 1
    assert history[0]["item_id"] == "A"
    assert history[0]["duration_seconds"] == 30.0
    assert history[0]["gate_passed"] is True
    assert "work_item_id" not in history[0]
    assert "wall_time_seconds" not in history[0]
    assert "quality_gates_passed" not in history[0]



def test_get_model_history_empty_for_non_positive_limit() -> None:
    """get_model_history should return [] when limit <= 0."""
    api = DesktopAPI()
    assert api.get_model_history(limit=0) == []


def test_get_state_includes_model_leaderboard() -> None:
    """get_state should include model_leaderboard field."""
    from unittest.mock import patch
    api = DesktopAPI()
    with patch("pokepoke.models.model_stats_store.get_model_summary", return_value={"models": []}):
        state = api.get_state()
    assert "model_leaderboard" in state


def test_push_stats_with_model_completions() -> None:
    """push_stats should serialize model completions via snapshot."""
    from pokepoke.types import ModelCompletionRecord
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats())
    stats_obj.record_model_completion(ModelCompletionRecord(
        item_id="x", model="gpt-5", duration_seconds=10.0
    ))
    api.push_stats(stats_obj, elapsed_time=1.0)
    assert len(api._current_stats["model_completions"]) == 1


# ─── Prompt management tests ─────────────────────────────────────────────


def test_list_prompts_returns_list() -> None:
    """list_prompts should return a non-empty list of prompt templates."""
    from unittest.mock import MagicMock, patch
    api = DesktopAPI()
    mock_service = MagicMock()
    mock_service.list_prompts.return_value = [
        {"name": "work-item", "is_override": False, "has_builtin": True, "source": "builtin"},
    ]
    with patch("pokepoke.prompts.prompts.get_prompt_service", return_value=mock_service):
        result = api.list_prompts()
    assert len(result) == 1
    assert result[0]["name"] == "work-item"


def test_get_prompt_returns_metadata() -> None:
    """get_prompt should return prompt content and metadata."""
    from unittest.mock import MagicMock, patch
    api = DesktopAPI()
    mock_service = MagicMock()
    mock_service.get_prompt_metadata.return_value = {
        "name": "work-item",
        "content": "Hello {{name}}",
        "is_override": False,
        "has_builtin": True,
        "source": "builtin",
        "template_variables": ["name"],
    }
    with patch("pokepoke.prompts.prompts.get_prompt_service", return_value=mock_service):
        result = api.get_prompt("work-item")
    assert result["name"] == "work-item"
    assert "name" in result["template_variables"]


def test_save_prompt_delegates() -> None:
    """save_prompt should delegate to PromptService."""
    from unittest.mock import MagicMock, patch
    api = DesktopAPI()
    mock_service = MagicMock()
    mock_service.save_prompt.return_value = {"path": "/tmp/test.md", "saved": True}
    with patch("pokepoke.prompts.prompts.get_prompt_service", return_value=mock_service):
        result = api.save_prompt("test", "new content")
    assert result["saved"]
    mock_service.save_prompt.assert_called_once_with("test", "new content")


def test_reset_prompt_delegates() -> None:
    """reset_prompt should delegate to PromptService."""
    from unittest.mock import MagicMock, patch
    api = DesktopAPI()
    mock_service = MagicMock()
    mock_service.reset_prompt.return_value = {"reset": True, "had_override": True}
    with patch("pokepoke.prompts.prompts.get_prompt_service", return_value=mock_service):
        result = api.reset_prompt("test")
    assert result["reset"]
    mock_service.reset_prompt.assert_called_once_with("test")


def test_push_agent_status_preserves_parent() -> None:
    """parent_agent_id should be stored and preserved across updates."""
    api = DesktopAPI()
    api.push_agent_status(
        "agent-1",
        "Gate Agent",
        iteration=1,
        status="running",
        parent_agent_id="work-1",
    )

    agents = api.get_agents()
    assert agents[0]["parent_agent_id"] == "work-1"

    api.push_agent_status("agent-1", "Gate Agent", iteration=2, status="success")
    agents = api.get_agents()
    current = next(agent for agent in agents if not agent["is_history_entry"])
    history = next(agent for agent in agents if agent["is_history_entry"])

    assert current["parent_agent_id"] == "work-1"
    assert current["iteration"] == 2
    assert current["status"] == "success"

    assert history["parent_agent_id"] == "work-1"
    assert history["iteration"] == 1
    assert history["is_history_entry"] is True


def test_push_agent_log_appends_lines() -> None:
    """push_agent_log should append lines to the agent's recent logs."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Work Agent")
    api.push_agent_log("agent-1", "Starting tests...")
    api.push_agent_log("agent-1", "Tests passed")

    agents = api.get_agents()
    assert agents[0]["recent_logs"] == ["Starting tests...", "Tests passed"]


def test_push_agent_log_trims_excess() -> None:
    """push_agent_log should trim to max log lines."""
    api = DesktopAPI()
    api._agent_max_log_lines = 3
    api._agent_detail_max_log_lines = 4
    api.push_agent_status("agent-1", "Worker")
    for i in range(5):
        api.push_agent_log("agent-1", f"line-{i}")

    agents = api.get_agents()
    assert agents[0]["recent_logs"] == ["line-2", "line-3", "line-4"]
    # log_lines is only available via get_agent_detail, not in the summary
    assert "log_lines" not in agents[0]
    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert detail["log_lines"] == ["line-1", "line-2", "line-3", "line-4"]


def test_push_agent_log_ignores_unknown_agent(monkeypatch) -> None:
    """push_agent_log should silently ignore unknown agent IDs."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_log("nonexistent", "should not crash")
    assert api.get_agents() == []


def test_push_agent_status_with_modified_files() -> None:
    """push_agent_status should store and return modified_files."""
    api = DesktopAPI()
    files = ["src/main.py", "tests/test_main.py"]
    api.push_agent_status(
        "cleanup-1", "Cleanup Agent", iteration=1, status="running",
        work_item_id="item-42", work_item_title="Fix bug",
        modified_files=files,
    )

    agents = api.get_agents()
    assert len(agents) == 1
    assert agents[0]["work_item_id"] == "item-42"
    assert agents[0]["work_item_title"] == "Fix bug"
    assert agents[0]["modified_files"] == files

    # modified_files should be preserved across status updates
    api.push_agent_status("cleanup-1", "Cleanup Agent", iteration=1, status="success")
    agents = api.get_agents()
    assert agents[0]["modified_files"] == files


def test_get_agent_detail_includes_modified_files() -> None:
    """get_agent_detail should include modified_files."""
    api = DesktopAPI()
    api.push_agent_status(
        "cleanup-1", "Cleanup Agent", iteration=1, status="running",
        modified_files=["file.py"],
    )
    detail = api.get_agent_detail("cleanup-1")
    assert detail is not None
    assert detail["modified_files"] == ["file.py"]


def test_get_agent_detail_includes_full_logs_and_timestamps() -> None:
    """get_agent_detail should return deep copies with trimmed logs and metadata."""
    api = DesktopAPI()
    api._agent_max_log_lines = 2
    api._agent_detail_max_log_lines = 3
    api.push_agent_status("agent-1", "Worker", iteration=1, status="running")
    for line in ("one", "two", "three", "four"):
        api.push_agent_log("agent-1", line)

    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert detail["recent_logs"] == ["three", "four"]
    assert detail["log_lines"] == ["two", "three", "four"]
    assert detail["last_log_at"] is not None
    assert detail["last_updated"] is not None


# ─── desktop_api_ext coverage tests ──────────────────────────────────────


def test_discover_log_roots_with_env_var(tmp_path, monkeypatch) -> None:
    """_discover_log_roots should include POKEPOKE_LOGS_DIR when set."""
    logs_dir = tmp_path / "custom_logs"
    logs_dir.mkdir()
    monkeypatch.setenv("POKEPOKE_LOGS_DIR", str(logs_dir))
    monkeypatch.setattr("pokepoke.config._find_repo_root", lambda: tmp_path)

    roots = _real_discover_log_roots()
    assert logs_dir.resolve() in roots


def test_discover_log_roots_without_env_var(tmp_path, monkeypatch) -> None:
    """_discover_log_roots should fall back to repo-relative paths."""
    monkeypatch.delenv("POKEPOKE_LOGS_DIR", raising=False)
    repo_logs = tmp_path / ".pokepoke" / "logs"
    repo_logs.mkdir(parents=True)
    monkeypatch.setattr("pokepoke.config._find_repo_root", lambda: tmp_path)

    roots = _real_discover_log_roots()
    assert repo_logs.resolve() in roots


def test_discover_log_roots_find_repo_root_fails(tmp_path, monkeypatch) -> None:
    """_discover_log_roots should fall back to cwd when _find_repo_root fails."""
    monkeypatch.delenv("POKEPOKE_LOGS_DIR", raising=False)

    def _fail():
        raise RuntimeError("no repo")

    monkeypatch.setattr("pokepoke.config._find_repo_root", _fail)

    roots = _real_discover_log_roots()
    assert isinstance(roots, list)
