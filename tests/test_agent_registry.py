"""Tests for AgentRecord dataclass and AgentRegistry typed internals."""

from __future__ import annotations

import threading

from pokepoke.agent_registry import AgentRecord, AgentRegistry


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
        reg.update_status("a1", "Worker", iteration=1, status="running")
        assert isinstance(reg._agents["a1"], AgentRecord)

    def test_internal_history_uses_agent_records(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "Worker", iteration=1, status="running")
        reg.update_status("a1", "Worker", iteration=2, status="running")
        assert len(reg._agent_history["a1"]) == 1
        assert isinstance(reg._agent_history["a1"][0], AgentRecord)

    def test_serialize_all_returns_dicts(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "Worker", iteration=1, status="running")
        agents = reg.serialize_all()
        assert len(agents) == 1
        assert isinstance(agents[0], dict)

    def test_get_detail_returns_dict(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "Worker", iteration=1, status="running")
        detail = reg.get_detail("a1")
        assert isinstance(detail, dict)
        assert "log_lines" in detail

    def test_attribute_access_replaces_get(self) -> None:
        """Fields are accessed as attributes, not via .get() with string keys."""
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "Worker", iteration=1, status="running", model="gpt-5")
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
        reg.update_status("a1", "W", iteration=1, status="running")
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
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.append_log("a1", "hello")
        agent = reg._agents["a1"]
        assert agent.recent_logs == ["hello"]
        assert agent.log_lines == ["hello"]
        assert agent.last_log_at is not None
        assert agent.last_updated is not None

    def test_trims_preview_log(self) -> None:
        reg = AgentRegistry(threading.RLock(), preview_limit=2)
        reg.update_status("a1", "W", iteration=1, status="running")
        for i in range(5):
            reg.append_log("a1", f"line-{i}")
        assert reg._agents["a1"].recent_logs == ["line-3", "line-4"]

    def test_trims_detail_log(self) -> None:
        reg = AgentRegistry(threading.RLock(), preview_limit=100, detail_limit=3)
        reg.update_status("a1", "W", iteration=1, status="running")
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
        reg.update_status("a1", "W", iteration=1, status="running")
        assert reg.pause("a1") is True

    def test_pause_returns_false_for_unknown(self) -> None:
        reg = AgentRegistry(threading.RLock())
        assert reg.pause("nonexistent") is False

    def test_resume_returns_true_when_paused(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.pause("a1")
        assert reg.resume("a1") is True

    def test_resume_returns_false_when_not_paused(self) -> None:
        reg = AgentRegistry(threading.RLock())
        assert reg.resume("nonexistent") is False

    def test_is_paused_reflects_state(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        assert reg.is_paused("a1") is False
        reg.pause("a1")
        assert reg.is_paused("a1") is True
        reg.resume("a1")
        assert reg.is_paused("a1") is False


class TestRegistryClearRemove:
    def test_clear_removes_everything(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.pause("a1")
        reg.update_status("a1", "W", iteration=2, status="running")
        reg.clear()
        assert reg._agents == {}
        assert reg._agent_history == {}
        assert reg._paused_agents == set()

    def test_remove_deletes_agent_and_paused(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
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
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.append_log("a1", "v1 log")
        reg.update_status("a1", "W", iteration=2, status="running")
        agents = reg.serialize_all()
        assert len(agents) == 2
        history = [a for a in agents if a["is_history_entry"]]
        live = [a for a in agents if not a["is_history_entry"]]
        assert len(history) == 1
        assert len(live) == 1

    def test_sorted_by_started_at_descending(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.update_status("a2", "W", iteration=1, status="running")
        agents = reg.serialize_all()
        assert agents[0]["started_at"] >= agents[1]["started_at"]

    def test_paused_flag_reflected_in_serialization(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.pause("a1")
        agents = reg.serialize_all()
        assert agents[0]["paused"] is True


class TestRegistryGetDetail:
    def test_returns_none_for_unknown(self) -> None:
        reg = AgentRegistry(threading.RLock())
        assert reg.get_detail("nonexistent") is None

    def test_lookup_by_card_id_on_live_agent(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        card_id = reg._agents["a1"].card_id
        detail = reg.get_detail(card_id)
        assert detail is not None
        assert detail["agent_id"] == "a1"

    def test_lookup_by_card_id_on_history(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.update_status("a1", "W", iteration=2, status="running")
        detail = reg.get_detail("a1::v1")
        assert detail is not None
        assert detail["is_history_entry"] is True

    def test_includes_log_lines(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.append_log("a1", "hello")
        detail = reg.get_detail("a1")
        assert "log_lines" in detail
        assert detail["log_lines"] == ["hello"]


class TestRegistryParentResolution:
    def test_parent_card_from_live_agent(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("parent", "P", iteration=1, status="running")
        reg.update_status("child", "C", iteration=1, status="running", parent_agent_id="parent")
        child = reg._agents["child"]
        assert child.parent_card_id == "parent::v1"

    def test_parent_card_from_history(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("parent", "P", iteration=1, status="running")
        reg.remove("parent")
        # Parent is gone from live agents, but history was not archived via iteration.
        # Manually archive to simulate finished parent.
        reg._agent_history["parent"] = [
            AgentRecord(agent_id="parent", base_agent_id="parent", card_id="parent::v1", name="P")
        ]
        reg.update_status("child", "C", iteration=1, status="running", parent_agent_id="parent")
        child = reg._agents["child"]
        assert child.parent_card_id == "parent::v1"


class TestRegistryArchiveAttempt:
    def test_archive_sets_running_to_failed(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="running")
        reg.update_status("a1", "W", iteration=2, status="running")
        history = reg._agent_history["a1"]
        assert len(history) == 1
        assert history[0].status == "failed"
        assert history[0].is_history_entry is True

    def test_archive_preserves_non_running_status(self) -> None:
        reg = AgentRegistry(threading.RLock())
        reg.update_status("a1", "W", iteration=1, status="success")
        reg.update_status("a1", "W", iteration=2, status="running")
        history = reg._agent_history["a1"]
        assert history[0].status == "success"


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
