"""Tests for A/B model comparison features.

Covers:
- model_selection.py: Random model assignment from candidate list
- ModelCompletionRecord: Per-item model tracking
- stats.py: Per-model comparison display (_print_model_comparison)
- config.py: candidate_models config parsing
"""

from unittest.mock import patch, MagicMock

import pytest

from pokepoke.model_selection import select_model_for_item
from pokepoke.types import (
    ModelCompletionRecord,
    SessionStats,
    AgentStats,
    CopilotResult,
)
from pokepoke.config import ModelConfig, ProjectConfig, reset_config
from pokepoke.stats import _print_model_comparison, _format_duration


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Clear config cache before and after each test."""
    reset_config()
    yield
    reset_config()


# ─── ModelConfig candidate_models ────────────────────────────────────────────


class TestModelConfigCandidates:
    """Tests for candidate_models on ModelConfig."""

    def test_default_empty_candidates(self):
        config = ModelConfig()
        assert config.candidate_models == []

    def test_custom_candidates(self):
        config = ModelConfig(candidate_models=["gpt-4o", "claude-opus-4.6"])
        assert config.candidate_models == ["gpt-4o", "claude-opus-4.6"]

    def test_from_dict_with_candidates(self):
        data = {
            "models": {
                "default": "claude-opus-4.6",
                "fallback": "claude-sonnet-4.5",
                "candidate_models": ["gpt-4o", "claude-opus-4.6", "claude-sonnet-4.5"],
            }
        }
        config = ProjectConfig.from_dict(data)
        assert config.models.candidate_models == [
            "gpt-4o",
            "claude-opus-4.6",
            "claude-sonnet-4.5",
        ]

    def test_from_dict_without_candidates(self):
        data = {"models": {"default": "gpt-4o"}}
        config = ProjectConfig.from_dict(data)
        assert config.models.candidate_models == []


# ─── select_model_for_item ───────────────────────────────────────────────────


class TestSelectModelForItem:
    """Tests for random model selection from candidates."""

    @patch("pokepoke.model_selection.get_config")
    def test_returns_default_when_no_candidates(self, mock_config):
        mock_config.return_value = ProjectConfig(
            models=ModelConfig(default="claude-opus-4.6", candidate_models=[])
        )
        model = select_model_for_item("item-1")
        assert model == "claude-opus-4.6"

    @patch("pokepoke.model_selection.get_config")
    def test_returns_candidate_when_configured(self, mock_config):
        candidates = ["gpt-4o", "claude-opus-4.6"]
        mock_config.return_value = ProjectConfig(
            models=ModelConfig(candidate_models=candidates)
        )
        model = select_model_for_item("item-2")
        assert model in candidates

    @patch("pokepoke.model_selection.get_config")
    @patch("pokepoke.model_selection.random.choice")
    def test_uses_random_choice(self, mock_choice, mock_config):
        candidates = ["modelA", "modelB", "modelC"]
        mock_config.return_value = ProjectConfig(
            models=ModelConfig(candidate_models=candidates)
        )
        mock_choice.return_value = "modelB"
        model = select_model_for_item("item-3")
        assert model == "modelB"
        mock_choice.assert_called_once_with(candidates)

    @patch("pokepoke.model_selection.get_config")
    def test_single_candidate(self, mock_config):
        mock_config.return_value = ProjectConfig(
            models=ModelConfig(candidate_models=["only-model"])
        )
        model = select_model_for_item("item-4")
        assert model == "only-model"


# ─── ModelCompletionRecord ───────────────────────────────────────────────────


class TestModelCompletionRecord:
    """Tests for the ModelCompletionRecord dataclass."""

    def test_basic_creation(self):
        rec = ModelCompletionRecord(
            item_id="item-1",
            model="gpt-4o",
            duration_seconds=120.0,
        )
        assert rec.item_id == "item-1"
        assert rec.model == "gpt-4o"
        assert rec.duration_seconds == 120.0
        assert rec.gate_passed is None

    def test_with_gate_passed(self):
        rec = ModelCompletionRecord(
            item_id="item-2",
            model="claude-opus-4.6",
            duration_seconds=300.0,
            gate_passed=True,
        )
        assert rec.gate_passed is True

    def test_with_gate_failed(self):
        rec = ModelCompletionRecord(
            item_id="item-3",
            model="claude-sonnet-4.5",
            duration_seconds=180.0,
            gate_passed=False,
        )
        assert rec.gate_passed is False


# ─── SessionStats model_completions ──────────────────────────────────────────


class TestSessionStatsModelCompletions:
    """Tests for model_completions on SessionStats."""

    def test_default_empty(self):
        stats = SessionStats(agent_stats=AgentStats())
        assert stats.model_completions == []

    def test_append_completions(self):
        stats = SessionStats(agent_stats=AgentStats())
        rec = ModelCompletionRecord("id1", "gpt-4o", 60.0, True)
        stats.model_completions.append(rec)
        assert len(stats.model_completions) == 1
        assert stats.model_completions[0].model == "gpt-4o"


# ─── CopilotResult model field ──────────────────────────────────────────────


class TestCopilotResultModel:
    """Tests for model field on CopilotResult."""

    def test_default_model_none(self):
        result = CopilotResult(work_item_id="x", success=True)
        assert result.model is None

    def test_model_set(self):
        result = CopilotResult(work_item_id="x", success=True, model="gpt-4o")
        assert result.model == "gpt-4o"


# ─── _format_duration ────────────────────────────────────────────────────────


class TestFormatDuration:
    """Tests for duration formatting helper."""

    def test_seconds_only(self):
        assert _format_duration(45.0) == "45s"

    def test_minutes_and_seconds(self):
        assert _format_duration(125.0) == "2m 5s"

    def test_zero(self):
        assert _format_duration(0.0) == "0s"

    def test_exact_minute(self):
        assert _format_duration(60.0) == "1m 0s"


# ─── _print_model_comparison ────────────────────────────────────────────────


class TestPrintModelComparison:
    """Tests for the model comparison output."""

    def test_single_model_output(self, capsys):
        records = [
            ModelCompletionRecord("i1", "gpt-4o", 120.0, True),
            ModelCompletionRecord("i2", "gpt-4o", 180.0, True),
            ModelCompletionRecord("i3", "gpt-4o", 90.0, False),
        ]
        _print_model_comparison(records)
        output = capsys.readouterr().out

        assert "gpt-4o" in output
        assert "Items processed:  3" in output
        assert "Gate pass rate:   67%" in output
        assert "(2/3)" in output

    def test_multiple_models(self, capsys):
        records = [
            ModelCompletionRecord("i1", "gpt-4o", 120.0, True),
            ModelCompletionRecord("i2", "claude-opus-4.6", 200.0, True),
            ModelCompletionRecord("i3", "gpt-4o", 60.0, False),
            ModelCompletionRecord("i4", "claude-opus-4.6", 100.0, True),
        ]
        _print_model_comparison(records)
        output = capsys.readouterr().out

        assert "gpt-4o" in output
        assert "claude-opus-4.6" in output
        # gpt-4o: 1 pass, 1 fail = 50%
        assert "50%" in output
        # claude-opus-4.6: 2 pass, 0 fail = 100%
        assert "100%" in output

    def test_no_gate_runs(self, capsys):
        records = [
            ModelCompletionRecord("i1", "gpt-4o", 120.0, gate_passed=None),
        ]
        _print_model_comparison(records)
        output = capsys.readouterr().out

        assert "N/A" in output

    def test_empty_list_no_output(self, capsys):
        _print_model_comparison([])
        output = capsys.readouterr().out
        assert "Model Comparison" not in output

    def test_timing_stats(self, capsys):
        records = [
            ModelCompletionRecord("i1", "modelX", 60.0, True),
            ModelCompletionRecord("i2", "modelX", 120.0, True),
            ModelCompletionRecord("i3", "modelX", 180.0, True),
        ]
        _print_model_comparison(records)
        output = capsys.readouterr().out

        # Avg = 120s = 2m 0s, Min = 60s = 1m 0s, Max = 180s = 3m 0s
        assert "2m 0s" in output  # avg
        assert "1m 0s" in output  # min
        assert "3m 0s" in output  # max

    def test_all_gates_passed(self, capsys):
        records = [
            ModelCompletionRecord("i1", "m1", 100.0, True),
            ModelCompletionRecord("i2", "m1", 100.0, True),
        ]
        _print_model_comparison(records)
        output = capsys.readouterr().out
        assert "100%" in output
        assert "(2/2)" in output

    def test_all_gates_failed(self, capsys):
        records = [
            ModelCompletionRecord("i1", "m1", 100.0, False),
            ModelCompletionRecord("i2", "m1", 100.0, False),
        ]
        _print_model_comparison(records)
        output = capsys.readouterr().out
        assert "0%" in output
        assert "(0/2)" in output

    def test_mixed_gate_and_no_gate(self, capsys):
        records = [
            ModelCompletionRecord("i1", "m1", 100.0, True),
            ModelCompletionRecord("i2", "m1", 100.0, None),  # no gate run
            ModelCompletionRecord("i3", "m1", 100.0, False),
        ]
        _print_model_comparison(records)
        output = capsys.readouterr().out
        # Only 2 gate records (True + False), so 50% (1/2)
        assert "50%" in output
        assert "(1/2)" in output
        assert "Items processed:  3" in output
