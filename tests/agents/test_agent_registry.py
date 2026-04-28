"""Tests for AgentRecord dataclass and AgentRegistry typed internals."""

from __future__ import annotations

import threading

from pokepoke.agents.agent_config import AgentStatusConfig
from pokepoke.agents.agent_registry import AgentRecord, AgentRegistry


def _update_status(reg: AgentRegistry, agent_id: str, name: str, iteration: int = 1, status: str = "running", **kwargs) -> None:
    """Helper to update_status using the new config API for test convenience."""
    config = AgentStatusConfig(
        agent_id=agent_id, name=name, iteration=iteration, status=status, **kwargs
    )
    reg.update_status(config)


class TestAgentRecordConstruction:
    """AgentRecord should have sensible defaults for all optional fields."""

    def test_minimal_construction(self) -> None:
        rec = AgentRecord(agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W")
        assert rec.agent_id == "a1"
        assert rec.iteration == 1
        assert rec.status == "running"
        assert rec.model is None
        assert rec.modified_files == []
        assert rec.recent_logs == []
        assert rec.log_lines == []
        assert rec.input_tokens == 0
        assert rec.output_tokens == 0
        assert rec.paused is False
        assert rec.is_history_entry is False

    def test_full_construction(self) -> None:
        rec = AgentRecord(
            agent_id="a1",
            base_agent_id="a1",
            card_id="a1::v2",
            name="Worker",
            iteration=2,
            status="success",
            model="gpt-5",
            parent_agent_id="parent",
            parent_card_id="parent::v1",
            work_item_id="item-1",
            work_item_title="Fix bug",
            agent_prompt="do stuff",
            session_id="sess-1",
            agent_type="gate",
            modified_files=["a.py"],
            recent_logs=["log1"],
            log_lines=["log1", "log2"],
            started_at=100.0,
            last_updated=200.0,
            last_log_at=150.0,
            input_tokens=500,
            output_tokens=300,
            paused=True,
            is_history_entry=True,
        )
        assert rec.iteration == 2
        assert rec.status == "success"
        assert rec.model == "gpt-5"
        assert rec.work_item_id == "item-1"
        assert rec.modified_files == ["a.py"]
        assert rec.input_tokens == 500


class TestAgentRecordToDict:
    """to_dict should produce a plain dict matching the old serialization format."""

    def test_to_dict_excludes_log_lines_by_default(self) -> None:
        rec = AgentRecord(
            agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W",
            log_lines=["line1", "line2"],
        )
        d = rec.to_dict()
        assert "log_lines" not in d
        assert d["agent_id"] == "a1"
        assert d["recent_logs"] == []

    def test_to_dict_includes_log_lines_when_requested(self) -> None:
        rec = AgentRecord(
            agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W",
            log_lines=["line1"],
        )
        d = rec.to_dict(include_log_lines=True)
        assert d["log_lines"] == ["line1"]

    def test_to_dict_returns_list_copies(self) -> None:
        """Mutating the dict's lists must not affect the AgentRecord."""
        rec = AgentRecord(
            agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W",
            modified_files=["f.py"], recent_logs=["log"],
        )
        d = rec.to_dict()
        d["modified_files"].append("extra.py")
        d["recent_logs"].append("extra")
        assert rec.modified_files == ["f.py"]
        assert rec.recent_logs == ["log"]

    def test_to_dict_all_keys_present(self) -> None:
        rec = AgentRecord(agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W")
        d = rec.to_dict(include_log_lines=True)
        expected_keys = {
            "agent_id", "base_agent_id", "card_id", "parent_card_id",
            "name", "iteration", "status", "model", "parent_agent_id",
            "work_item_id", "work_item_title", "agent_prompt", "session_id",
            "agent_type", "modified_files", "recent_logs", "started_at",
            "last_updated", "last_log_at", "paused", "input_tokens",
            "output_tokens", "is_history_entry", "log_lines",
        }
        assert set(d.keys()) == expected_keys


class TestAgentRecordCopy:
    """copy() should produce an independent clone with optional overrides."""

    def test_copy_is_independent(self) -> None:
        rec = AgentRecord(
            agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W",
            modified_files=["f.py"], recent_logs=["log"],
        )
        clone = rec.copy()
        clone.modified_files.append("extra.py")
        clone.recent_logs.append("extra")
        assert rec.modified_files == ["f.py"]
        assert rec.recent_logs == ["log"]

    def test_copy_overrides_paused(self) -> None:
        rec = AgentRecord(agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W")
        clone = rec.copy(paused=True)
        assert clone.paused is True
        assert rec.paused is False

    def test_copy_overrides_is_history(self) -> None:
        rec = AgentRecord(agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W")
        clone = rec.copy(is_history=True)
        assert clone.is_history_entry is True
        assert rec.is_history_entry is False

    def test_copy_omits_log_lines_when_not_included(self) -> None:
        rec = AgentRecord(
            agent_id="a1", base_agent_id="a1", card_id="a1::v1", name="W",
            log_lines=["line1", "line2"],
        )
        clone = rec.copy(include_log_lines=False)
        assert clone.log_lines == []
        assert rec.log_lines == ["line1", "line2"]


class TestRegistryUsesAgentRecord:
    """Verify the registry's internal storage uses AgentRecord."""

    def test_internal_agents_are_agent_records(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "Worker", iteration=1, status="running")
        assert isinstance(reg._agents["a1"], AgentRecord)

    def test_internal_history_uses_agent_records(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "Worker", iteration=1, status="running")
        _update_status(reg, "a1", "Worker", iteration=2, status="running")
        assert len(reg._agent_history["a1"]) == 1
        assert isinstance(reg._agent_history["a1"][0], AgentRecord)

    def test_serialize_all_returns_dicts(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "Worker", iteration=1, status="running")
        agents = reg.serialize_all()
        assert len(agents) == 1
        assert isinstance(agents[0], dict)

    def test_get_detail_returns_dict(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "Worker", iteration=1, status="running")
        detail = reg.get_detail("a1")
        assert isinstance(detail, dict)
        assert "log_lines" in detail

    def test_attribute_access_replaces_get(self) -> None:
        """Fields are accessed as attributes, not via .get() with string keys."""
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "Worker", iteration=1, status="running", model="gpt-5")
        agent = reg._agents["a1"]
        assert agent.model == "gpt-5"
        assert agent.iteration == 1
        assert agent.status == "running"


class TestRegistrySetLimits:
    def test_set_limits_updates_preview_and_detail(self) -> None:
        reg = AgentRegistry(threading.RLock(), preview_limit=10, detail_limit=50)
        reg.set_limits(5, 25)
        assert reg._preview_limit == 5
        assert reg._detail_limit == 25


class TestRegistryUpdateTokenUsage:
    def test_updates_token_counts(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.update_token_usage("a1", 1000, 500)
        assert reg._agents["a1"].input_tokens == 1000
        assert reg._agents["a1"].output_tokens == 500

    def test_ignores_unknown_agent(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_token_usage("nonexistent", 100, 50)
        assert reg._agents == {}


class TestRegistryAppendLog:
    def test_appends_to_both_log_buffers(self) -> None:
        reg = AgentRegistry(threading.RLock(), preview_limit=5, detail_limit=10)
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.append_log("a1", "hello")
        agent = reg._agents["a1"]
        assert agent.recent_logs == ["hello"]
        assert agent.log_lines == ["hello"]
        assert agent.last_log_at is not None
        assert agent.last_updated is not None

    def test_trims_preview_log(self) -> None:
        reg = AgentRegistry(threading.RLock(), preview_limit=2)
        _update_status(reg, "a1", "W", iteration=1, status="running")
        for i in range(5):
            reg.append_log("a1", f"line-{i}")
        assert reg._agents["a1"].recent_logs == ["line-3", "line-4"]

    def test_trims_detail_log(self) -> None:
        reg = AgentRegistry(threading.RLock(), preview_limit=100, detail_limit=3)
        _update_status(reg, "a1", "W", iteration=1, status="running")
        for i in range(5):
            reg.append_log("a1", f"line-{i}")
        assert reg._agents["a1"].log_lines == ["line-2", "line-3", "line-4"]

    def test_ignores_unknown_agent(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.append_log("nonexistent", "line")
        assert reg._agents == {}


class TestRegistryPauseResume:
    def test_pause_returns_true_for_existing(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        assert reg.pause("a1") is True

    def test_pause_returns_false_for_unknown(self) -> None:
        reg = AgentRegistry(threading.RLock())
        assert reg.pause("nonexistent") is False

    def test_resume_returns_true_when_paused(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.pause("a1")
        assert reg.resume("a1") is True

    def test_resume_returns_false_when_not_paused(self) -> None:
        reg = AgentRegistry(threading.RLock())
        assert reg.resume("nonexistent") is False

    def test_is_paused_reflects_state(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        assert reg.is_paused("a1") is False
        reg.pause("a1")
        assert reg.is_paused("a1") is True
        reg.resume("a1")
        assert reg.is_paused("a1") is False


class TestRegistryClearRemove:
    def test_clear_removes_everything(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.pause("a1")
        _update_status(reg, "a1", "W", iteration=2, status="running")
        reg.clear()
        assert reg._agents == {}
        assert reg._agent_history == {}
        assert reg._paused_agents == set()

    def test_remove_deletes_agent_and_paused(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.pause("a1")
        reg.remove("a1")
        assert "a1" not in reg._agents
        assert reg.is_paused("a1") is False

    def test_remove_ignores_unknown(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.remove("nonexistent")  # should not raise


class TestRegistrySerializeAll:
    def test_includes_history_and_live(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.append_log("a1", "v1 log")
        _update_status(reg, "a1", "W", iteration=2, status="running")
        agents = reg.serialize_all()
        assert len(agents) == 2
        history = [a for a in agents if a["is_history_entry"]]
        live = [a for a in agents if not a["is_history_entry"]]
        assert len(history) == 1
        assert len(live) == 1

    def test_sorted_by_started_at_descending(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        _update_status(reg, "a2", "W", iteration=1, status="running")
        agents = reg.serialize_all()
        assert agents[0]["started_at"] >= agents[1]["started_at"]

    def test_paused_flag_reflected_in_serialization(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.pause("a1")
        agents = reg.serialize_all()
        assert agents[0]["paused"] is True


class TestRegistryGetDetail:
    def test_returns_none_for_unknown(self) -> None:
        reg = AgentRegistry(threading.RLock())
        assert reg.get_detail("nonexistent") is None

    def test_lookup_by_card_id_on_live_agent(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        card_id = reg._agents["a1"].card_id
        detail = reg.get_detail(card_id)
        assert detail is not None
        assert detail["agent_id"] == "a1"

    def test_lookup_by_card_id_on_history(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        _update_status(reg, "a1", "W", iteration=2, status="running")
        detail = reg.get_detail("a1::v1")
        assert detail is not None
        assert detail["is_history_entry"] is True

    def test_includes_log_lines(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.append_log("a1", "hello")
        detail = reg.get_detail("a1")
        assert "log_lines" in detail
        assert detail["log_lines"] == ["hello"]


class TestRegistryParentResolution:
    def test_parent_card_from_live_agent(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "P", iteration=1, status="running")
        _update_status(reg, "child", "C", iteration=1, status="running", parent_agent_id="parent")
        child = reg._agents["child"]
        assert child.parent_card_id == "parent::v1"

    def test_parent_card_from_history(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "P", iteration=1, status="running")
        reg.remove("parent")
        # Parent is gone from live agents, but history was not archived via iteration.
        # Manually archive to simulate finished parent.
        reg._agent_history["parent"] = [
            AgentRecord(agent_id="parent", base_agent_id="parent", card_id="parent::v1", name="P")
        ]
        _update_status(reg, "child", "C", iteration=1, status="running", parent_agent_id="parent")
        child = reg._agents["child"]
        assert child.parent_card_id == "parent::v1"


class TestRegistryArchiveAttempt:
    def test_archive_sets_running_to_failed(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        _update_status(reg, "a1", "W", iteration=2, status="running")
        history = reg._agent_history["a1"]
        assert len(history) == 1
        assert history[0].status == "failed"
        assert history[0].is_history_entry is True

    def test_archive_preserves_non_running_status(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="success")
        _update_status(reg, "a1", "W", iteration=2, status="running")
        history = reg._agent_history["a1"]
        assert history[0].status == "success"


class TestRegistryResumeInPlace:
    """resume_in_place=True should keep logs, card_id, and started_at."""

    def test_preserves_logs_on_resume(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.append_log("a1", "line-1")
        reg.append_log("a1", "line-2")
        _update_status(reg, "a1", "W", iteration=2, status="running", resume_in_place=True)
        agent = reg._agents["a1"]
        assert "line-1" in agent.recent_logs
        assert "line-2" in agent.recent_logs
        assert "line-1" in agent.log_lines
        assert "line-2" in agent.log_lines

    def test_preserves_card_id_on_resume(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        original_card_id = reg._agents["a1"].card_id
        _update_status(reg, "a1", "W", iteration=2, status="running", resume_in_place=True)
        assert reg._agents["a1"].card_id == original_card_id

    def test_preserves_started_at_on_resume(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        original_started = reg._agents["a1"].started_at
        _update_status(reg, "a1", "W", iteration=2, status="running", resume_in_place=True)
        assert reg._agents["a1"].started_at == original_started

    def test_does_not_archive_on_resume(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        _update_status(reg, "a1", "W", iteration=2, status="running", resume_in_place=True)
        assert "a1" not in reg._agent_history

    def test_updates_iteration_on_resume(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        _update_status(reg, "a1", "W", iteration=2, status="running", resume_in_place=True)
        assert reg._agents["a1"].iteration == 2

    def test_standard_retry_still_archives(self) -> None:
        """Without resume_in_place, normal retry behavior is preserved."""
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.append_log("a1", "old-log")
        _update_status(reg, "a1", "W", iteration=2, status="running")
        assert "a1" in reg._agent_history
        assert len(reg._agent_history["a1"]) == 1
        # Logs are cleared for standard retry
        assert reg._agents["a1"].recent_logs == []
        assert reg._agents["a1"].log_lines == []

    def test_preserves_parent_card_id_on_resume(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        # Agent has no parent, so parent_card_id should stay None
        _update_status(reg, "a1", "W", iteration=2, status="running", resume_in_place=True)
        assert reg._agents["a1"].parent_card_id is None

    def test_preserves_last_log_at_on_resume(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.append_log("a1", "log-line")
        original_log_at = reg._agents["a1"].last_log_at
        assert original_log_at is not None
        _update_status(reg, "a1", "W", iteration=2, status="running", resume_in_place=True)
        assert reg._agents["a1"].last_log_at == original_log_at

    def test_serialize_shows_single_card_after_resume(self) -> None:
        """In-place resume should produce one card, not a history entry + live entry."""
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "a1", "W", iteration=1, status="running")
        reg.append_log("a1", "log-line")
        _update_status(reg, "a1", "W", iteration=2, status="running", resume_in_place=True)
        agents = reg.serialize_all()
        assert len(agents) == 1
        assert agents[0]["iteration"] == 2
        assert agents[0]["is_history_entry"] is False


class TestRegistryNormalizeAgentType:
    def test_normalizes_mixed_case_and_spaces(self) -> None:
        assert AgentRegistry._normalize_agent_type("Gate Agent") == "gate_agent"

    def test_returns_none_for_empty(self) -> None:
        assert AgentRegistry._normalize_agent_type("") is None
        assert AgentRegistry._normalize_agent_type(None) is None

    def test_strips_special_characters(self) -> None:
        assert AgentRegistry._normalize_agent_type("--hello--world--") == "hello_world"


class TestRegistryBuildCardId:
    def test_normal_iteration(self) -> None:
        assert AgentRegistry._build_card_id("a1", 3) == "a1::v3"

    def test_zero_iteration_defaults_to_one(self) -> None:
        assert AgentRegistry._build_card_id("a1", 0) == "a1::v1"

    def test_negative_iteration_defaults_to_one(self) -> None:
        assert AgentRegistry._build_card_id("a1", -5) == "a1::v1"


class TestRegistryChildAgentTracking:
    """Tests for parent-child agent relationship tracking."""

    def test_has_active_children_false_when_no_children(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        assert reg.has_active_children("parent") is False

    def test_has_active_children_true_when_child_running(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child", "Child", iteration=1, status="running", parent_agent_id="parent")
        assert reg.has_active_children("parent") is True

    def test_has_active_children_false_when_child_completed(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child", "Child", iteration=1, status="success", parent_agent_id="parent")
        assert reg.has_active_children("parent") is False

    def test_has_active_children_counts_pending_as_active(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child", "Child", iteration=1, status="pending", parent_agent_id="parent")
        assert reg.has_active_children("parent") is True

    def test_get_active_children_returns_running_children(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child1", "Child1", iteration=1, status="running", parent_agent_id="parent")
        _update_status(reg, "child2", "Child2", iteration=1, status="pending", parent_agent_id="parent")
        _update_status(reg, "child3", "Child3", iteration=1, status="success", parent_agent_id="parent")

        active = reg.get_active_children("parent")
        assert set(active) == {"child1", "child2"}

    def test_get_active_children_empty_when_no_children(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        assert reg.get_active_children("parent") == []

    def test_get_most_recent_child_activity_returns_none_when_no_children(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        assert reg.get_most_recent_child_activity("parent") is None

    def test_get_most_recent_child_activity_returns_child_log_time(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child", "Child", iteration=1, status="running", parent_agent_id="parent")
        reg.append_log("child", "child log")

        # Get the child's last_log_at timestamp
        child = reg._agents["child"]
        expected_time = child.last_log_at

        assert reg.get_most_recent_child_activity("parent") == expected_time

    def test_get_most_recent_child_activity_picks_most_recent(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child1", "Child1", iteration=1, status="running", parent_agent_id="parent")
        _update_status(reg, "child2", "Child2", iteration=1, status="running", parent_agent_id="parent")

        # Log to child1
        reg.append_log("child1", "log")
        time1 = reg._agents["child1"].last_log_at

        # Sleep a tiny bit and log to child2 (should be more recent)
        import time as time_module
        time_module.sleep(0.01)
        reg.append_log("child2", "log")
        time2 = reg._agents["child2"].last_log_at

        most_recent = reg.get_most_recent_child_activity("parent")
        assert most_recent == time2
        assert most_recent != time1

    def test_get_most_recent_child_activity_ignores_completed_children(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child1", "Child1", iteration=1, status="success", parent_agent_id="parent")
        _update_status(reg, "child2", "Child2", iteration=1, status="running", parent_agent_id="parent")

        reg.append_log("child1", "completed child log")
        reg.append_log("child2", "running child log")

        # Should only consider child2 (running)
        most_recent = reg.get_most_recent_child_activity("parent")
        assert most_recent == reg._agents["child2"].last_log_at

    def test_remove_cleans_up_parent_child_tracking(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child", "Child", iteration=1, status="running", parent_agent_id="parent")

        assert reg.has_active_children("parent") is True

        # Remove child
        reg.remove("child")

        assert reg.has_active_children("parent") is False
        assert "parent" not in reg._child_tracker._parent_to_children

    def test_remove_parent_cleans_up_children_mapping(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child", "Child", iteration=1, status="running", parent_agent_id="parent")

        # Remove parent
        reg.remove("parent")

        # Parent should be removed from the tracking dict
        assert "parent" not in reg._child_tracker._parent_to_children

    def test_clear_removes_parent_child_tracking(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child", "Child", iteration=1, status="running", parent_agent_id="parent")

        assert len(reg._child_tracker._parent_to_children) > 0

        reg.clear()

        assert reg._child_tracker._parent_to_children == {}

    def test_multiple_children_tracked_correctly(self) -> None:
        reg = AgentRegistry(threading.RLock())
        _update_status(reg, "parent", "Parent", iteration=1, status="running")
        _update_status(reg, "child1", "Child1", iteration=1, status="running", parent_agent_id="parent")
        _update_status(reg, "child2", "Child2", iteration=1, status="running", parent_agent_id="parent")
        _update_status(reg, "child3", "Child3", iteration=1, status="running", parent_agent_id="parent")

        active = reg.get_active_children("parent")
        assert len(active) == 3
        assert set(active) == {"child1", "child2", "child3"}
