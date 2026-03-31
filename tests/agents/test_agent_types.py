"""Tests for agent type registry - definitions, resolution, and iteration."""

import pytest

from pokepoke.agents.agent_types import (
    AGENT_TYPES,
    AgentTypeDefinition,
    _empty_agent_run_counts,
    _normalize_agent_key,
    iter_agent_types,
    resolve_agent_type,
)

# ---------------------------------------------------------------------------
# AgentTypeDefinition
# ---------------------------------------------------------------------------

class TestAgentTypeDefinition:
    """Tests for AgentTypeDefinition dataclass."""

    def test_auto_run_attr(self):
        """run_attr defaults to {key}_agent_runs when not provided."""
        defn = AgentTypeDefinition(key="work", display_name="Work", emoji="📋")
        assert defn.run_attr == "work_agent_runs"

    def test_explicit_run_attr(self):
        defn = AgentTypeDefinition(key="work", display_name="Work", emoji="📋", run_attr="custom_runs")
        assert defn.run_attr == "custom_runs"

    def test_frozen(self):
        defn = AgentTypeDefinition(key="work", display_name="Work", emoji="📋")
        with pytest.raises(AttributeError):
            defn.key = "other"


# ---------------------------------------------------------------------------
# _normalize_agent_key
# ---------------------------------------------------------------------------

class TestNormalizeAgentKey:
    """Tests for _normalize_agent_key helper."""

    def test_lowercase(self):
        assert _normalize_agent_key("Work") == "work"

    def test_spaces_to_underscores(self):
        assert _normalize_agent_key("Tech Debt") == "tech_debt"

    def test_strips_whitespace(self):
        assert _normalize_agent_key("  gate  ") == "gate"

    def test_mixed(self):
        assert _normalize_agent_key("  Beta Tester  ") == "beta_tester"


# ---------------------------------------------------------------------------
# AGENT_TYPES registry
# ---------------------------------------------------------------------------

class TestAgentTypesRegistry:
    """Tests for the global AGENT_TYPES dictionary."""

    def test_contains_expected_types(self):
        expected = {"work", "gate", "cleanup", "tech_debt", "janitor", "decomposition"}
        assert expected.issubset(set(AGENT_TYPES.keys()))

    def test_all_values_are_definitions(self):
        for v in AGENT_TYPES.values():
            assert isinstance(v, AgentTypeDefinition)

    def test_work_always_show(self):
        assert AGENT_TYPES["work"].always_show is True

    def test_gate_not_always_show(self):
        assert AGENT_TYPES["gate"].always_show is False


# ---------------------------------------------------------------------------
# resolve_agent_type
# ---------------------------------------------------------------------------

class TestResolveAgentType:
    """Tests for resolve_agent_type."""

    def test_resolve_by_key(self):
        defn = resolve_agent_type("work")
        assert defn.key == "work"

    def test_resolve_by_display_name(self):
        defn = resolve_agent_type("Tech Debt")
        assert defn.key == "tech_debt"

    def test_resolve_case_insensitive(self):
        defn = resolve_agent_type("GATE")
        assert defn.key == "gate"

    def test_raises_on_unknown(self):
        with pytest.raises(ValueError, match="Unknown agent type"):
            resolve_agent_type("nonexistent_agent")


# ---------------------------------------------------------------------------
# iter_agent_types
# ---------------------------------------------------------------------------

class TestIterAgentTypes:
    """Tests for iter_agent_types."""

    def test_returns_iterable(self):
        types = list(iter_agent_types())
        assert len(types) > 0
        assert all(isinstance(t, AgentTypeDefinition) for t in types)

    def test_matches_registry_values(self):
        types = list(iter_agent_types())
        assert types == list(AGENT_TYPES.values())


# ---------------------------------------------------------------------------
# _empty_agent_run_counts
# ---------------------------------------------------------------------------

class TestEmptyAgentRunCounts:
    """Tests for _empty_agent_run_counts."""

    def test_all_keys_present(self):
        counts = _empty_agent_run_counts()
        assert set(counts.keys()) == set(AGENT_TYPES.keys())

    def test_all_values_zero(self):
        counts = _empty_agent_run_counts()
        assert all(v == 0 for v in counts.values())

    def test_returns_new_dict_each_call(self):
        a = _empty_agent_run_counts()
        b = _empty_agent_run_counts()
        assert a is not b
        a["work"] = 5
        assert b["work"] == 0
