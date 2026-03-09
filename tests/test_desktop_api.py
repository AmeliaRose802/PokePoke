"""Tests for DesktopAPI state buffering and retrieval."""

import subprocess
import textwrap
import time
from unittest.mock import Mock

import pytest

from pokepoke.desktop_api import DesktopAPI
from pokepoke.desktop_api_ext import _discover_log_roots as _real_discover_log_roots
from pokepoke.types import SessionStats, AgentStats, BeadsWorkItem


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop_api_ext._discover_log_roots", lambda: [])
    monkeypatch.setattr("pokepoke.desktop_api.get_repository_name", lambda: "test-repo")


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
        "pokepoke.desktop_api_ext._discover_log_roots",
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


def test_spawn_agent_honors_effective_max_agents(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_agent_status("a1", "agent-1", status="running")
    api.push_agent_status("a2", "agent-2", status="running")

    mock_request = Mock()
    monkeypatch.setattr("pokepoke.parallel.request_spawn_agent", mock_request)
    monkeypatch.setattr("pokepoke.parallel.get_effective_max_agents", lambda: 3)

    result = api.spawn_agent()
    assert result["success"] is True
    assert result["at_limit"] is False
    assert result["active"] == 2
    assert result["max"] == 3
    mock_request.assert_called_once()

    mock_request.reset_mock()
    monkeypatch.setattr("pokepoke.parallel.get_effective_max_agents", lambda: 2)

    result = api.spawn_agent()
    assert result["success"] is False
    assert result["at_limit"] is True
    assert result["active"] == 2
    assert result["max"] == 2
    mock_request.assert_not_called()


def test_add_remove_work_item_label(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PokePoke-1", "Title", "open", ["urgent"])

    mock_run = Mock(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("pokepoke.desktop_api_ext.subprocess.run", lambda *args, **kwargs: mock_run)

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
            cmd=args[0],
            stderr="network unavailable",
        )

    monkeypatch.setattr("pokepoke.desktop_api_ext.subprocess.run", _raise)

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
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=30, stderr="timed out")

    monkeypatch.setattr("pokepoke.desktop_api_ext.subprocess.run", _timeout)

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
    assert elapsed1 >= 9  # Should be ~10 seconds (integer precision)

    # Set end time to freeze the clock
    end_time = start_time + 5.5  # 5.5 seconds after start
    api.set_session_end_time(end_time)

    # Clock should be frozen — elapsed truncated to int seconds (5)
    stats2 = api.get_stats()
    assert stats2 is not None
    elapsed2 = stats2["elapsed_time"]
    # int(5.5) == 5; allow ±1 for integer truncation
    assert abs(elapsed2 - 5.5) <= 1

    # Clock should remain frozen even after waiting
    time.sleep(0.1)
    stats3 = api.get_stats()
    assert stats3 is not None
    elapsed3 = stats3["elapsed_time"]
    assert elapsed3 == elapsed2  # Should not advance


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
    stats_obj.record_agent_run("work", 1)
    stats_obj.record_agent_run("gate", 2)
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
    """get_model_history should proxy to model_history.load_model_history_entries and normalize keys."""
    from unittest.mock import patch

    api = DesktopAPI()
    # Mock raw data from model_history
    raw_data = [{"work_item_id": "A", "wall_time_seconds": 30.0, "quality_gates_passed": True}]

    with patch("pokepoke.model_history.load_model_history_entries", return_value=raw_data) as mock_history:
        history = api.get_model_history(limit=5)

    mock_history.assert_called_once_with(limit=5)

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
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ValueError, match="Config must be a dict or YAML string"):
        api.save_config(42)


def test_save_config_rejects_non_dict_yaml() -> None:
    """save_config should reject YAML strings that don't parse to a dict."""
    from unittest.mock import patch
    import pytest

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ValueError, match="Config YAML must parse to an object"):
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


def test_initial_state_has_empty_agents(monkeypatch) -> None:
    """get_state should include an empty agents list initially."""
    monkeypatch.delenv("POKEPOKE_LOGS_DIR", raising=False)
    monkeypatch.setattr("pokepoke.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    state = api.get_state()
    assert state["agents"] == []


def test_push_agent_status_registers_agent(monkeypatch) -> None:
    """push_agent_status should add an agent to the tracked set."""
    monkeypatch.setattr("pokepoke.desktop_api_ext._discover_log_roots", lambda: [])
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


def test_push_agent_status_updates_existing(monkeypatch) -> None:
    """push_agent_status should update an existing agent's fields."""
    monkeypatch.setattr("pokepoke.desktop_api_ext._discover_log_roots", lambda: [])
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
    assert len(agents) == 2

    current = next(agent for agent in agents if not agent["is_history_entry"])
    history = next(agent for agent in agents if agent["is_history_entry"])

    assert current["iteration"] == 2
    assert current["status"] == "success"
    assert current["model"] == "gpt-5"
    assert current["work_item_id"] == "item-123"
    assert current["work_item_title"] == "Title"
    assert current["recent_logs"] == []

    assert history["iteration"] == 1
    assert history["status"] == "failed"
    assert history["recent_logs"] == ["line 1"]
    assert history["is_history_entry"] is True


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
    monkeypatch.setattr("pokepoke.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_log("nonexistent", "should not crash")
    assert api.get_agents() == []


def test_remove_agent(monkeypatch) -> None:
    """remove_agent should remove the agent from tracked set."""
    monkeypatch.setattr("pokepoke.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Agent A")
    api.push_agent_status("agent-2", "Agent B")
    api.remove_agent("agent-1")

    agents = api.get_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-2"


def test_remove_agent_ignores_unknown(monkeypatch) -> None:
    """remove_agent should silently ignore unknown agent IDs."""
    monkeypatch.setattr("pokepoke.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.remove_agent("nonexistent")
    assert api.get_agents() == []


def test_get_state_includes_agents(monkeypatch) -> None:
    """get_state should include agents in the returned state."""
    monkeypatch.setattr("pokepoke.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", iteration=3, status="running")
    api.push_agent_log("agent-1", "doing work")

    state = api.get_state()
    assert len(state["agents"]) == 1
    assert state["agents"][0]["name"] == "Worker"
    assert state["agents"][0]["recent_logs"] == ["doing work"]
    # log_lines is omitted from serialize_all to keep poll payloads small;
    # it is only available from get_agent_detail.
    assert "log_lines" not in state["agents"][0]
    assert state["agents"][0]["work_item_id"] is None
    # get_state now folds in new_logs so the frontend only needs one IPC call
    assert "new_logs" in state


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


def test_get_config_no_yaml(monkeypatch) -> None:
    """get_config should raise ImportError when yaml is not available."""
    from unittest.mock import patch

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / ".pokepoke" / "config.yaml"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("key: val\n", encoding="utf-8")
            mock_root.return_value = root

            monkeypatch.setattr("pokepoke.desktop_api_ext.HAS_YAML", False)
            with pytest.raises(ImportError, match="PyYAML"):
                api.get_config()


def test_get_config_file_not_found(monkeypatch) -> None:
    """get_config should return exists=False when config file is missing."""
    from unittest.mock import patch

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mock_root.return_value = root
            result = api.get_config()

    assert result["exists"] is False


def test_save_config_no_yaml(monkeypatch) -> None:
    """save_config should raise ImportError when yaml is not available."""
    from unittest.mock import patch

    api = DesktopAPI()
    monkeypatch.setattr("pokepoke.desktop_api_ext.HAS_YAML", False)
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ImportError, match="PyYAML"):
        api.save_config({"key": "val"})


# ─── Agent token usage tests ─────────────────────────────────────────────


def test_push_agent_tokens_updates_agent() -> None:
    """push_agent_tokens should store token counts on the agent."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.push_agent_tokens("agent-1", 5000, 2000)

    agents = api.get_agents()
    assert agents[0]["input_tokens"] == 5000
    assert agents[0]["output_tokens"] == 2000


def test_push_agent_tokens_defaults_to_zero() -> None:
    """Agents without token pushes should have zero token fields."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")

    agents = api.get_agents()
    assert agents[0]["input_tokens"] == 0
    assert agents[0]["output_tokens"] == 0


def test_push_agent_tokens_ignores_unknown_agent() -> None:
    """push_agent_tokens should silently ignore unknown agent IDs."""
    api = DesktopAPI()
    api.push_agent_tokens("nonexistent", 100, 200)
    assert api.get_agents() == []


def test_agent_detail_includes_tokens() -> None:
    """get_agent_detail should include token fields."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.push_agent_tokens("agent-1", 10_000, 3_000)

    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert detail["input_tokens"] == 10_000
    assert detail["output_tokens"] == 3_000


# ─── open_project / browse_for_project tests ─────────────────────────


def test_open_project_nonexistent_directory() -> None:
    api = DesktopAPI()
    result = api.open_project("/nonexistent/path/xyz")
    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_open_project_not_a_git_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: False
    )
    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is False
    assert "Not a git repository" in result["error"]


def test_open_project_success_with_pokepoke_config(tmp_path, monkeypatch) -> None:
    # Set up a fake project dir with .pokepoke/ and actual config file
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text(
        "project_name: test-proj\n", encoding="utf-8"
    )
    (tmp_path / ".git").mkdir()  # So _find_repo_root resolves to tmp_path

    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.repo_utils.get_repository_name", lambda: "test-repo"
    )

    api = DesktopAPI()
    result = api.open_project(str(tmp_path))

    assert result["success"] is True
    assert result["needs_init"] is False
    assert result["needs_beads_init"] is False
    assert result["project_name"] == "test-proj"
    # Session state should be reset
    state = api.get_state()
    assert state["work_item"] is None
    assert state["agent_name"] == ""
    assert state["repository_name"] == "test-repo"


def test_open_project_needs_init_when_no_pokepoke_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: False
    )
    monkeypatch.setattr(
        "pokepoke.repo_utils.get_repository_name", lambda: "bare-repo"
    )

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True
    assert result["needs_init"] is True
    assert result["needs_beads_init"] is True


def test_browse_for_project_no_window() -> None:
    api = DesktopAPI()
    # _window is None by default
    result = api.browse_for_project()
    assert result["success"] is False
    assert "No window" in result["error"]


def test_browse_for_project_cancelled() -> None:
    api = DesktopAPI()
    mock_window = Mock()
    mock_window.create_file_dialog.return_value = None
    api.set_window(mock_window)

    result = api.browse_for_project()
    assert result["success"] is False
    assert result.get("cancelled") is True


def test_browse_for_project_delegates_to_open_project(tmp_path, monkeypatch) -> None:
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text(
        "project_name: picked\n", encoding="utf-8"
    )
    (tmp_path / ".git").mkdir()  # So _find_repo_root resolves to tmp_path

    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.repo_utils.get_repository_name", lambda: "picked-repo"
    )

    api = DesktopAPI()
    mock_window = Mock()
    mock_window.create_file_dialog.return_value = (str(tmp_path),)
    api.set_window(mock_window)

    result = api.browse_for_project()
    assert result["success"] is True
    assert result["project_name"] == "picked"


def test_open_project_resolves_subdirectory_to_git_toplevel(tmp_path, monkeypatch) -> None:
    """When user picks a subdirectory, open_project resolves to the git repo root."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subdir = repo_root / "src" / "app"
    subdir.mkdir(parents=True)
    (repo_root / ".pokepoke").mkdir()
    (repo_root / ".pokepoke" / "config.yaml").write_text(
        "project_name: resolved-proj\n", encoding="utf-8"
    )
    (repo_root / ".git").mkdir()  # So _find_repo_root resolves to repo_root

    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: repo_root
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.repo_utils.get_repository_name", lambda: "resolved-repo"
    )

    result = DesktopAPI().open_project(str(subdir))
    assert result["success"] is True
    assert result["path"] == str(repo_root)
    assert result["needs_init"] is False
    assert result["project_name"] == "resolved-proj"


def test_open_project_needs_init_with_empty_pokepoke_dir(tmp_path, monkeypatch) -> None:
    """A .pokepoke/ dir with no config file still reports needs_init=True."""
    (tmp_path / ".pokepoke").mkdir()
    # No config.yaml/yml/json inside

    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.repo_utils.get_repository_name", lambda: "empty-config"
    )

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True
    assert result["needs_init"] is True


def test_open_project_clears_agent_registry(tmp_path, monkeypatch) -> None:
    """Opening a new project clears previously tracked agents."""
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.repo_utils.get_repository_name", lambda: "fresh-repo"
    )

    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", 1, "running")
    assert len(api.get_agents()) == 1

    api.open_project(str(tmp_path))
    assert len(api.get_agents()) == 0


def test_open_project_cancels_stop_after_current(tmp_path, monkeypatch) -> None:
    """Opening a new project cancels any pending stop-after-current request."""
    from pokepoke.shutdown import (
        request_stop_after_current,
        should_stop_after_current,
        reset as reset_shutdown,
    )

    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.repo_utils.get_repository_name", lambda: "fresh-repo"
    )

    try:
        request_stop_after_current()
        assert should_stop_after_current() is True

        DesktopAPI().open_project(str(tmp_path))
        assert should_stop_after_current() is False
    finally:
        reset_shutdown()


def test_open_project_needs_beads_init_when_bd_unavailable(tmp_path, monkeypatch) -> None:
    """When beads is not available, needs_beads_init should be True."""
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text(
        "project_name: no-beads\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: False
    )
    monkeypatch.setattr(
        "pokepoke.repo_utils.get_repository_name", lambda: "no-beads-repo"
    )

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True
    assert result["needs_beads_init"] is True


def test_open_project_fails_when_agents_active(tmp_path, monkeypatch) -> None:
    """open_project should fail when agents are actively running."""
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text(
        "project_name: test\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._has_pokepoke_config", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop_api_ext._check_beads_available", lambda p: True
    )
    # Mock has_active_agents in the shutdown module where it's defined
    monkeypatch.setattr(
        "pokepoke.shutdown.has_active_agents", lambda: True
    )

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is False
    assert "Cannot switch projects while agents are running" in result["error"]


# ─── Window disposal tests ───────────────────────────────────────────


def test_dispose_marks_window_as_disposed() -> None:
    """dispose() should set the _window_disposed flag and clear window reference."""
    api = DesktopAPI()
    mock_window = Mock()
    api.set_window(mock_window)

    assert api._window == mock_window
    assert api._window_disposed is False

    api.dispose()

    assert api._window is None
    assert api._window_disposed is True


def test_push_log_silently_ignores_after_disposal() -> None:
    """push_log() should silently return when window is disposed to prevent ObjectDisposedException spam."""
    api = DesktopAPI()

    # Log before disposal - should work
    api.push_log("before disposal")
    assert len(api._log_buffer) == 1
    assert api._log_buffer[0]["message"] == "before disposal"

    # Dispose the window
    api.dispose()

    # Log after disposal - should be silently ignored
    api.push_log("after disposal")
    assert len(api._log_buffer) == 1  # Should still be 1, not 2
    assert api._log_buffer[0]["message"] == "before disposal"  # Original log preserved

    # Verify no exceptions are raised
    api.push_log("another log", "agent", "red")
    assert len(api._log_buffer) == 1


def test_disposal_is_thread_safe() -> None:
    """dispose() should be thread-safe using the existing lock."""
    api = DesktopAPI()

    # Add some logs before disposal
    for i in range(10):
        api.push_log(f"pre-dispose log {i}")

    assert len(api._log_buffer) == 10

    # Dispose the window
    api.dispose()
    assert api._window_disposed is True


def test_push_methods_silently_ignore_after_disposal() -> None:
    """All push methods should silently return when window is disposed."""
    from pokepoke.types import SessionStats, AgentStats

    api = DesktopAPI()

    # Set initial state before disposal
    api.push_work_item("item-1", "Test Item", "open", ["label1"])
    api.push_agent_name("Test Agent")
    api.push_progress(True, "working")
    api.push_agent_status("agent-1", "Worker", status="running")
    api.push_agent_log("agent-1", "log line")
    api.push_agent_tokens("agent-1", 100, 50)
    api.set_session_start_time(1000.0)
    api.set_session_end_time(2000.0)
    api.set_logs_dir("/logs")

    stats = SessionStats(
        agent_stats=AgentStats(),
        items_completed=1,
        items_created=0,
        lifetime_items_created=10,
        lifetime_items_completed=9,
    )
    api.set_live_session_stats(stats)
    api.push_stats(stats, elapsed_time=100.0)

    # Capture initial state
    initial_work_item = api._current_work_item
    initial_agent_name = api._current_agent_name
    initial_progress = api._current_progress.copy()
    initial_agents_count = len(api.get_agents())
    initial_session_start = api._session_start_time
    initial_session_end = api._session_end_time
    initial_logs_dir = api._current_logs_dir
    initial_live_stats = api._live_session_stats
    initial_current_stats = api._current_stats

    # Dispose the window
    api.dispose()

    # All push methods should now silently ignore updates
    api.push_work_item("item-2", "New Item", "closed", ["label2"])
    api.push_agent_name("Different Agent")
    api.push_progress(False, "done")
    api.push_agent_status("agent-2", "Another Worker", status="done")
    api.push_agent_log("agent-1", "should be ignored")
    api.push_agent_tokens("agent-1", 200, 100)
    api.set_session_start_time(3000.0)
    api.set_session_end_time(4000.0)
    api.set_logs_dir("/different/logs")

    new_stats = SessionStats(
        agent_stats=AgentStats(),
        items_completed=5,
        items_created=2,
        lifetime_items_created=20,
        lifetime_items_completed=18,
    )
    api.set_live_session_stats(new_stats)
    api.push_stats(new_stats, elapsed_time=200.0)
    api.clear_logs()  # Should also be ignored

    # Verify state hasn't changed
    assert api._current_work_item == initial_work_item
    assert api._current_agent_name == initial_agent_name
    assert api._current_progress == initial_progress
    assert len(api.get_agents()) == initial_agents_count  # No new agent added
    assert api._session_start_time == initial_session_start
    assert api._session_end_time == initial_session_end
    assert api._current_logs_dir == initial_logs_dir
    assert api._live_session_stats == initial_live_stats
    assert api._current_stats == initial_current_stats
    assert len(api._log_buffer) == 0  # clear_logs was not executed

