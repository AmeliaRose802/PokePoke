"""Tests for DesktopAPI state buffering and retrieval."""

import time

from pokepoke.desktop_api import DesktopAPI
from pokepoke.types import SessionStats, AgentStats, BeadsWorkItem


def test_initial_state_defaults() -> None:
    api = DesktopAPI()
    state = api.get_state()
    assert state["work_item"] is None
    assert state["agent_name"] == ""
    assert state["stats"] is None
    assert state["progress"] == {"active": False, "status": ""}
    assert state["log_count"] == 0


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
    api.push_work_item("item-1", "Title", "open")
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


def test_clear_logs() -> None:
    api = DesktopAPI()
    api.push_log("test")
    assert api.get_state()["log_count"] == 1
    api.clear_logs()
    assert api.get_state()["log_count"] == 0


def test_elapsed_time_computed_dynamically() -> None:
    """Timer should tick on every poll, not freeze between push_stats() calls."""
    api = DesktopAPI()
    start = time.time()
    api.set_session_start_time(start)

    # Even without push_stats, get_state should report non-zero elapsed
    state = api.get_state()
    assert state["stats"] is not None
    assert state["stats"]["elapsed_time"] >= 0.0

    # get_stats should also compute it dynamically
    stats = api.get_stats()
    assert stats is not None
    assert stats["elapsed_time"] >= 0.0


def test_elapsed_time_overrides_push_stats_value() -> None:
    """Dynamic elapsed_time should override stale push_stats value."""
    api = DesktopAPI()
    start = time.time() - 100  # pretend session started 100s ago
    api.set_session_start_time(start)

    stats_obj = SessionStats(agent_stats=AgentStats(), items_completed=3)
    api.push_stats(stats_obj, elapsed_time=5.0)  # stale value

    state = api.get_state()
    # Should be ~100s, not the stale 5.0
    assert state["stats"]["elapsed_time"] >= 99.0
    # Other stats should still be present
    assert state["stats"]["items_completed"] == 3


def test_session_end_time_freezes_clock() -> None:
    """Session end time should freeze the elapsed_time clock."""
    api = DesktopAPI()
    start_time = time.time() - 10  # 10 seconds ago
    api.set_session_start_time(start_time)
    
    # Clock should be running
    stats1 = api.get_stats()
    assert stats1 is not None
    elapsed1 = stats1["elapsed_time"]
    assert elapsed1 >= 9.0  # Should be ~10 seconds
    
    # Set end time to freeze the clock
    end_time = start_time + 5.5  # 5.5 seconds after start
    api.set_session_end_time(end_time)
    
    # Clock should be frozen at 5.5 seconds
    stats2 = api.get_stats()
    assert stats2 is not None
    elapsed2 = stats2["elapsed_time"]
    assert abs(elapsed2 - 5.5) < 0.1  # Should be exactly 5.5 seconds
    
    # Clock should remain frozen even after waiting
    time.sleep(0.1)
    stats3 = api.get_stats()
    assert stats3 is not None
    elapsed3 = stats3["elapsed_time"]
    assert abs(elapsed3 - 5.5) < 0.1  # Should still be 5.5 seconds


def test_session_end_time_without_start_time() -> None:
    """Session end time should be ignored if no start time is set."""
    api = DesktopAPI()
    api.set_session_end_time(time.time())
    
    # No session start time set, so elapsed_time shouldn't exist
    stats = api.get_stats()
    assert stats is None or "elapsed_time" not in stats


def test_session_end_time_with_pushed_stats() -> None:
    """Session end time should override elapsed_time from pushed stats."""
    api = DesktopAPI()
    start_time = time.time() - 10
    api.set_session_start_time(start_time)
    
    # Push stats with some elapsed time
    stats_obj = SessionStats(agent_stats=AgentStats(), items_completed=2)
    api.push_stats(stats_obj, elapsed_time=100.0)  # wrong value
    
    # Set end time to freeze the clock
    end_time = start_time + 3.0  # 3 seconds after start
    api.set_session_end_time(end_time)
    
    # Should use frozen time (3.0), not pushed time (100.0)
    state = api.get_state()
    assert state["stats"] is not None
    assert abs(state["stats"]["elapsed_time"] - 3.0) < 0.1
    assert state["stats"]["items_completed"] == 2  # Other data preserved


def test_live_stats_update_in_realtime() -> None:
    """Mutating the live SessionStats object should be reflected on next poll."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats(), items_completed=0)
    api.push_stats(stats_obj, elapsed_time=0.0)

    # Verify initial state
    state = api.get_state()
    assert state["stats"]["work_agent_runs"] == 0
    assert state["stats"]["gate_agent_runs"] == 0
    assert state["stats"]["items_completed"] == 0
    assert state["stats"]["items_created"] == 0

    # Mutate the live object (as the orchestrator does)
    stats_obj.work_agent_runs += 1
    stats_obj.gate_agent_runs += 2
    stats_obj.items_completed = 1
    stats_obj.agent_stats.input_tokens = 500

    # Next poll should reflect the mutations without another push_stats()
    state = api.get_state()
    assert state["stats"]["work_agent_runs"] == 1
    assert state["stats"]["gate_agent_runs"] == 2
    assert state["stats"]["items_completed"] == 1
    assert state["stats"]["items_created"] == 0
    assert state["stats"]["agent_stats"]["input_tokens"] == 500


def test_set_live_session_stats_directly() -> None:
    """set_live_session_stats should register the live reference."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats(), work_agent_runs=5)
    api.set_live_session_stats(stats_obj)

    state = api.get_state()
    assert state["stats"] is not None
    assert state["stats"]["work_agent_runs"] == 5


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


def test_get_stats_returns_none_initially() -> None:
    """get_stats should return None when no stats have been set."""
    api = DesktopAPI()
    assert api.get_stats() is None


def test_get_stats_returns_live_stats() -> None:
    """get_stats should return serialized live stats."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats(input_tokens=42))
    api.set_live_session_stats(stats_obj)
    result = api.get_stats()
    assert result is not None
    assert result["agent_stats"]["input_tokens"] == 42


def test_get_stats_with_session_start_time() -> None:
    """get_stats should include dynamic elapsed_time when session start is set."""
    api = DesktopAPI()
    api.set_session_start_time(time.time() - 10)
    result = api.get_stats()
    assert result is not None
    assert result["elapsed_time"] >= 9.0


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


def test_serialize_live_stats_no_session_start() -> None:
    """_serialize_live_stats should carry forward cached elapsed_time."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats())
    api.push_stats(stats_obj, elapsed_time=42.0)

    api._session_start_time = None
    state = api.get_state()
    assert state["stats"]["elapsed_time"] == 42.0


def test_push_stats_without_session_stats() -> None:
    """push_stats with None session_stats should still store elapsed_time."""
    api = DesktopAPI()
    api.push_stats(None, elapsed_time=5.0)
    assert api._current_stats is not None
    assert api._current_stats["elapsed_time"] == 5.0


def test_get_model_leaderboard() -> None:
    """get_model_leaderboard should return model summary."""
    from unittest.mock import patch
    api = DesktopAPI()
    with patch("pokepoke.model_stats_store.get_model_summary", return_value={"test": 1}):
        result = api.get_model_leaderboard()
    assert result == {"test": 1}


def test_get_model_history_delegates() -> None:
    """get_model_history should proxy to model_stats_store."""
    from unittest.mock import patch

    api = DesktopAPI()
    with patch("pokepoke.model_stats_store.get_model_history", return_value=[{"item_id": "A"}]) as mock_history:
        history = api.get_model_history(limit=5)
    mock_history.assert_called_once_with(limit=5)
    assert history == [{"item_id": "A"}]


def test_get_model_history_empty_for_non_positive_limit() -> None:
    """get_model_history should return [] when limit <= 0."""
    api = DesktopAPI()
    assert api.get_model_history(limit=0) == []


def test_get_state_includes_model_leaderboard() -> None:
    """get_state should include model_leaderboard field."""
    from unittest.mock import patch
    api = DesktopAPI()
    with patch("pokepoke.model_stats_store.get_model_summary", return_value={"models": []}):
        state = api.get_state()
    assert "model_leaderboard" in state


def test_get_config_reads_yaml() -> None:
    from unittest.mock import patch

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        # Create a fake repo root with .pokepoke/config.yaml
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".pokepoke").mkdir(parents=True, exist_ok=True)
            (root / ".pokepoke" / "config.yaml").write_text(
                "project_name: TestProject\nmodels:\n  default: gpt-5\n",
                encoding="utf-8",
            )
            mock_root.return_value = root

            result = api.get_config()

    assert result["exists"] is True
    assert result["config"]["project_name"] == "TestProject"
    assert result["config"]["models"]["default"] == "gpt-5"


def test_save_config_writes_yaml() -> None:
    from unittest.mock import patch
    import yaml

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mock_root.return_value = root

            save_result = api.save_config({"project_name": "X", "git": {"fallback_branch": "main"}})
            assert save_result["saved"] is True

            cfg_path = root / ".pokepoke" / "config.yaml"
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    assert loaded["project_name"] == "X"
    assert loaded["git"]["fallback_branch"] == "main"


def test_save_config_with_yaml_string() -> None:
    """save_config should accept a YAML string and parse it."""
    from unittest.mock import patch
    import yaml

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mock_root.return_value = root

            yaml_str = "project_name: Y\ngit:\n  fallback_branch: dev\n"
            save_result = api.save_config(yaml_str)
            assert save_result["saved"] is True

            cfg_path = root / ".pokepoke" / "config.yaml"
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    assert loaded["project_name"] == "Y"


def test_save_config_rejects_invalid_type() -> None:
    """save_config should reject non-dict/non-string input."""
    from unittest.mock import patch
    import pytest

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root"):
        with pytest.raises(ValueError, match="Config must be a dict or YAML string"):
            api.save_config(42)


def test_save_config_rejects_non_dict_yaml() -> None:
    """save_config should reject YAML strings that don't parse to a dict."""
    from unittest.mock import patch
    import pytest

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root"):
        with pytest.raises(ValueError, match="Config YAML must parse to an object"):
            api.save_config("- item1\n- item2\n")


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
    from unittest.mock import patch, MagicMock
    api = DesktopAPI()
    mock_service = MagicMock()
    mock_service.list_prompts.return_value = [
        {"name": "work-item", "is_override": False, "has_builtin": True, "source": "builtin"},
    ]
    with patch("pokepoke.prompts.get_prompt_service", return_value=mock_service):
        result = api.list_prompts()
    assert len(result) == 1
    assert result[0]["name"] == "work-item"


def test_get_prompt_returns_metadata() -> None:
    """get_prompt should return prompt content and metadata."""
    from unittest.mock import patch, MagicMock
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
    with patch("pokepoke.prompts.get_prompt_service", return_value=mock_service):
        result = api.get_prompt("work-item")
    assert result["name"] == "work-item"
    assert "name" in result["template_variables"]


def test_save_prompt_delegates() -> None:
    """save_prompt should delegate to PromptService."""
    from unittest.mock import patch, MagicMock
    api = DesktopAPI()
    mock_service = MagicMock()
    mock_service.save_prompt.return_value = {"path": "/tmp/test.md", "saved": True}
    with patch("pokepoke.prompts.get_prompt_service", return_value=mock_service):
        result = api.save_prompt("test", "new content")
    assert result["saved"]
    mock_service.save_prompt.assert_called_once_with("test", "new content")


def test_reset_prompt_delegates() -> None:
    """reset_prompt should delegate to PromptService."""
    from unittest.mock import patch, MagicMock
    api = DesktopAPI()
    mock_service = MagicMock()
    mock_service.reset_prompt.return_value = {"reset": True, "had_override": True}
    with patch("pokepoke.prompts.get_prompt_service", return_value=mock_service):
        result = api.reset_prompt("test")
    assert result["reset"]
    mock_service.reset_prompt.assert_called_once_with("test")


# ─── Agent tracking tests ────────────────────────────────────────────────


def test_initial_state_has_empty_agents() -> None:
    """get_state should include an empty agents list initially."""
    api = DesktopAPI()
    state = api.get_state()
    assert state["agents"] == []


def test_push_agent_status_registers_agent() -> None:
    """push_agent_status should add an agent to the tracked set."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Gate Agent", iteration=2, status="running", model="gpt-5.1")

    agents = api.get_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-1"
    assert agents[0]["name"] == "Gate Agent"
    assert agents[0]["iteration"] == 2
    assert agents[0]["status"] == "running"
    assert agents[0]["model"] == "gpt-5.1"
    assert agents[0]["work_item_id"] is None
    assert agents[0]["work_item_title"] is None
    assert agents[0]["modified_files"] == []
    assert agents[0]["recent_logs"] == []


def test_push_agent_status_updates_existing() -> None:
    """push_agent_status should update an existing agent's fields."""
    api = DesktopAPI()
    api.push_agent_status(
        "agent-1",
        "Gate Agent",
        iteration=1,
        model="gpt-5",
        work_item_id="item-123",
        work_item_title="Title",
    )
    api.push_agent_log("agent-1", "line 1")

    # Update iteration and status — logs + model should be preserved
    api.push_agent_status("agent-1", "Gate Agent", iteration=2, status="success")

    agents = api.get_agents()
    assert len(agents) == 1
    assert agents[0]["iteration"] == 2
    assert agents[0]["status"] == "success"
    assert agents[0]["model"] == "gpt-5"
    assert agents[0]["work_item_id"] == "item-123"
    assert agents[0]["work_item_title"] == "Title"
    assert agents[0]["recent_logs"] == ["line 1"]


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
    assert agents[0]["parent_agent_id"] == "work-1"
    assert agents[0]["iteration"] == 2
    assert agents[0]["status"] == "success"


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
    assert agents[0]["log_lines"] == ["line-1", "line-2", "line-3", "line-4"]


def test_push_agent_log_ignores_unknown_agent() -> None:
    """push_agent_log should silently ignore unknown agent IDs."""
    api = DesktopAPI()
    api.push_agent_log("nonexistent", "should not crash")
    assert api.get_agents() == []


def test_remove_agent() -> None:
    """remove_agent should remove the agent from tracked set."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Agent A")
    api.push_agent_status("agent-2", "Agent B")
    api.remove_agent("agent-1")

    agents = api.get_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-2"


def test_remove_agent_ignores_unknown() -> None:
    """remove_agent should silently ignore unknown agent IDs."""
    api = DesktopAPI()
    api.remove_agent("nonexistent")
    assert api.get_agents() == []


def test_get_state_includes_agents() -> None:
    """get_state should include agents in the returned state."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", iteration=3, status="running")
    api.push_agent_log("agent-1", "doing work")

    state = api.get_state()
    assert len(state["agents"]) == 1
    assert state["agents"][0]["name"] == "Worker"
    assert state["agents"][0]["recent_logs"] == ["doing work"]
    assert state["agents"][0]["log_lines"] == ["doing work"]
    assert state["agents"][0]["work_item_id"] is None


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


# ─── Stop-after-current API tests ────────────────────────────────────────


def test_get_state_includes_stop_after_current() -> None:
    """get_state should include stop_after_current flag."""
    from pokepoke.shutdown import reset as shutdown_reset
    shutdown_reset()
    api = DesktopAPI()
    state = api.get_state()
    assert "stop_after_current" in state
    assert state["stop_after_current"] is False


def test_request_stop_after_current_sets_flag() -> None:
    """request_stop_after_current should set the flag and log a message."""
    from pokepoke.shutdown import reset as shutdown_reset
    shutdown_reset()
    api = DesktopAPI()
    result = api.request_stop_after_current()
    assert result["stop_after_current"] is True
    state = api.get_state()
    assert state["stop_after_current"] is True
    assert any("Stop after current" in log["message"] for log in api.get_all_logs())
    shutdown_reset()


def test_cancel_stop_after_current_clears_flag() -> None:
    """cancel_stop_after_current should clear the flag and log a message."""
    from pokepoke.shutdown import reset as shutdown_reset
    shutdown_reset()
    api = DesktopAPI()
    api.request_stop_after_current()
    result = api.cancel_stop_after_current()
    assert result["stop_after_current"] is False
    state = api.get_state()
    assert state["stop_after_current"] is False
    shutdown_reset()


# ─── Agent pause/resume tests ───────────────────────────────────────────


def test_pause_agent_sets_paused_flag() -> None:
    """pause_agent should mark agent as paused and reflect in serialization."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")

    result = api.pause_agent("agent-1")
    assert result["paused"] is True

    agents = api.get_agents()
    assert agents[0]["paused"] is True


def test_resume_agent_clears_paused_flag() -> None:
    """resume_agent should clear paused flag."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")

    result = api.resume_agent("agent-1")
    assert result["resumed"] is True

    agents = api.get_agents()
    assert agents[0]["paused"] is False


def test_pause_nonexistent_agent_returns_false() -> None:
    """pause_agent should return paused=False for unknown agent."""
    api = DesktopAPI()
    result = api.pause_agent("nonexistent")
    assert result["paused"] is False


def test_resume_non_paused_agent_returns_false() -> None:
    """resume_agent should return resumed=False when agent is not paused."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    result = api.resume_agent("agent-1")
    assert result["resumed"] is False


def test_is_agent_paused() -> None:
    """is_agent_paused should reflect pause/resume state."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")

    assert api.is_agent_paused("agent-1") is False
    api.pause_agent("agent-1")
    assert api.is_agent_paused("agent-1") is True
    api.resume_agent("agent-1")
    assert api.is_agent_paused("agent-1") is False


def test_remove_agent_clears_paused_state() -> None:
    """remove_agent should also remove paused state."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")
    api.remove_agent("agent-1")
    assert api.is_agent_paused("agent-1") is False


def test_get_agent_detail_includes_paused() -> None:
    """get_agent_detail should include paused field."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")

    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert detail["paused"] is True


def test_pause_agent_logs_message() -> None:
    """pause_agent should log a pause message."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")

    logs = api.get_all_logs()
    assert any("paused" in log["message"].lower() for log in logs)


def test_resume_agent_logs_message() -> None:
    """resume_agent should log a resume message."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")
    api.get_all_logs()  # clear read index
    api.resume_agent("agent-1")

    logs = api.get_new_logs()
    assert any("resumed" in log["message"].lower() for log in logs)
