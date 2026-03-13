"""Unit tests for model_selection module."""

from unittest.mock import Mock, patch

from pokepoke.model_selection import select_model_for_item, select_gate_model, _matches_rule, get_assignment_for_item
from pokepoke.config import ProjectConfig, ModelConfig, AssignmentConfig, AssignmentRule, AssignmentRuleMatch
from pokepoke.types import BeadsWorkItem


def _make_item(item_id: str, **kwargs) -> BeadsWorkItem:
    """Create a minimal BeadsWorkItem for testing."""
    defaults = dict(title="test", status="open", priority=2, issue_type="task")
    defaults.update(kwargs)
    return BeadsWorkItem(id=item_id, **defaults)


class TestSelectGateModel:
    """Test select_gate_model function."""

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_selects_different_model_from_candidates(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """Test that gate agent selects a different model from available candidates."""
        # Setup config with multiple candidates
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="claude-opus-4.6",
            fallback="claude-sonnet-4.5",
            candidate_models=["claude-opus-4.6", "gpt-5.1-codex", "gpt-5"]
        )
        mock_get_config.return_value = mock_config

        # Mock uniform weights
        mock_get_weights.return_value = {
            "claude-opus-4.6": 1.0,
            "gpt-5.1-codex": 1.0,
            "gpt-5": 1.0
        }

        # Select gate model when work model is claude-opus-4.6
        gate_model = select_gate_model("claude-opus-4.6", "test-123")

        # Gate model should be different from work model
        assert gate_model != "claude-opus-4.6"
        assert gate_model in ["gpt-5.1-codex", "gpt-5"]

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_uses_fallback_when_only_one_candidate(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """Test fallback model is used when only one candidate exists."""
        # Setup config with single candidate
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="claude-opus-4.6",
            fallback="claude-sonnet-4.5",
            candidate_models=["gpt-5.1-codex"]
        )
        mock_get_config.return_value = mock_config
        mock_get_weights.return_value = {}

        # Select gate model when work model is the only candidate
        gate_model = select_gate_model("gpt-5.1-codex", "test-123")

        # Should use fallback since work model is the only candidate
        assert gate_model == "claude-sonnet-4.5"

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_uses_default_when_fallback_matches_work(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """Test default model is used when fallback also matches work model."""
        # Setup config where fallback matches work model
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="gpt-5",
            fallback="claude-sonnet-4.5",
            candidate_models=["claude-sonnet-4.5"]
        )
        mock_get_config.return_value = mock_config
        mock_get_weights.return_value = {}

        # Select gate model when work model matches fallback
        gate_model = select_gate_model("claude-sonnet-4.5", "test-123")

        # Should use default since fallback matches work model
        assert gate_model == "gpt-5"

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_handles_no_candidates(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """Test behavior when no candidate models are configured."""
        # Setup config with empty candidates
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="claude-opus-4.6",
            fallback="claude-sonnet-4.5",
            candidate_models=[]
        )
        mock_get_config.return_value = mock_config
        mock_get_weights.return_value = {}

        # Select gate model
        gate_model = select_gate_model("claude-opus-4.6", "test-123")

        # Should use fallback since no candidates
        assert gate_model == "claude-sonnet-4.5"

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_warns_when_all_models_same(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """Covers lines 133-134: warning when default, fallback, and work model are all the same."""
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="same-model",
            fallback="same-model",
            candidate_models=["same-model"]
        )
        mock_get_config.return_value = mock_config
        mock_get_weights.return_value = {}

        gate_model = select_gate_model("same-model", "test-123")
        # Should still return the model (better than failing)
        assert gate_model == "same-model"

    @patch('pokepoke.model_selection.random.choices')
    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_respects_model_weights(
        self, mock_get_config: Mock, mock_get_weights: Mock, mock_choices: Mock
    ) -> None:
        """Test that model selection respects historical performance weights."""
        # Setup config with multiple candidates
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="claude-opus-4.6",
            fallback="claude-sonnet-4.5",
            candidate_models=["claude-opus-4.6", "gpt-5.1-codex", "gpt-5"]
        )
        mock_get_config.return_value = mock_config

        # Mock weights (gpt-5.1-codex has better performance)
        mock_get_weights.return_value = {
            "claude-opus-4.6": 0.8,
            "gpt-5.1-codex": 1.5,
            "gpt-5": 0.9
        }
        mock_choices.return_value = ["gpt-5.1-codex"]

        # Select gate model when work model is claude-opus-4.6
        gate_model = select_gate_model("claude-opus-4.6", "test-123")

        # Verify random.choices was called with correct weights (excluding work model)
        call_args = mock_choices.call_args
        candidates_arg = call_args[0][0]
        _weights_arg = call_args[1]['weights']

        assert "claude-opus-4.6" not in candidates_arg
        assert "gpt-5.1-codex" in candidates_arg
        assert "gpt-5" in candidates_arg
        assert gate_model == "gpt-5.1-codex"


class TestSelectModelForItem:
    """Test select_model_for_item function (existing functionality)."""

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_synthesizes_candidates_when_none_configured(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """When candidate_models is empty, synthesize from default + fallback."""
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="claude-opus-4.6",
            fallback="claude-sonnet-4.5",
            candidate_models=[]
        )
        mock_get_config.return_value = mock_config
        mock_get_weights.return_value = {}

        model = select_model_for_item(_make_item("test-123"))

        assert model in ["claude-opus-4.6", "claude-sonnet-4.5"]
        mock_get_weights.assert_called_once()

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_synthesized_candidates_deduped_when_default_equals_fallback(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """When default == fallback, synthesized list has one entry."""
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="claude-opus-4.6",
            fallback="claude-opus-4.6",
            candidate_models=[]
        )
        mock_get_config.return_value = mock_config
        mock_get_weights.return_value = {}

        model = select_model_for_item(_make_item("test-123"))

        assert model == "claude-opus-4.6"
        mock_get_weights.assert_called_once()

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_selects_from_candidates(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """Test selection from candidate models."""
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="claude-opus-4.6",
            candidate_models=["gpt-5.1-codex", "claude-sonnet-4.5"]
        )
        mock_get_config.return_value = mock_config
        mock_get_weights.return_value = {
            "gpt-5.1-codex": 1.0,
            "claude-sonnet-4.5": 1.0
        }

        model = select_model_for_item(_make_item("test-123"))

        assert model in ["gpt-5.1-codex", "claude-sonnet-4.5"]


class TestMatchesRule:
    """Test _matches_rule helper for assignment rule matching."""

    def test_empty_rule_matches_everything(self) -> None:
        """A rule with no criteria matches any item."""
        rule = AssignmentRule()
        item = _make_item("x", issue_type="bug", priority=0)
        assert _matches_rule(rule, item) is True

    def test_issue_type_match(self) -> None:
        rule = AssignmentRule(match=AssignmentRuleMatch(issue_type="bug"))
        assert _matches_rule(rule, _make_item("x", issue_type="bug")) is True
        assert _matches_rule(rule, _make_item("x", issue_type="feature")) is False

    def test_priority_max_match(self) -> None:
        rule = AssignmentRule(match=AssignmentRuleMatch(priority_max=1))
        assert _matches_rule(rule, _make_item("x", priority=0)) is True
        assert _matches_rule(rule, _make_item("x", priority=1)) is True
        assert _matches_rule(rule, _make_item("x", priority=2)) is False

    def test_labels_match(self) -> None:
        rule = AssignmentRule(match=AssignmentRuleMatch(labels=["refactoring"]))
        assert _matches_rule(rule, _make_item("x", labels=["refactoring", "cleanup"])) is True
        assert _matches_rule(rule, _make_item("x", labels=["bug"])) is False
        assert _matches_rule(rule, _make_item("x", labels=None)) is False

    def test_combined_criteria_and_logic(self) -> None:
        """All specified criteria must match (AND logic)."""
        rule = AssignmentRule(
            match=AssignmentRuleMatch(issue_type="feature", priority_max=1)
        )
        # Both match
        assert _matches_rule(rule, _make_item("x", issue_type="feature", priority=1)) is True
        # Type matches but priority too low
        assert _matches_rule(rule, _make_item("x", issue_type="feature", priority=3)) is False
        # Priority matches but type doesn't
        assert _matches_rule(rule, _make_item("x", issue_type="bug", priority=0)) is False


class TestGetAssignmentForItem:
    """Test get_assignment_for_item returns the first matching rule."""

    @patch('pokepoke.model_selection.get_config')
    def test_returns_none_when_no_rules(self, mock_config: Mock) -> None:
        mock_config.return_value = ProjectConfig()
        model, prompt = get_assignment_for_item(_make_item("x"))
        assert model is None
        assert prompt is None

    @patch('pokepoke.model_selection.get_config')
    def test_returns_first_matching_rule(self, mock_config: Mock) -> None:
        cfg = ProjectConfig()
        cfg.assignment = AssignmentConfig(rules=[
            AssignmentRule(
                match=AssignmentRuleMatch(issue_type="bug"),
                model="claude-sonnet-4.5",
            ),
            AssignmentRule(
                match=AssignmentRuleMatch(issue_type="bug"),
                model="gpt-5",
            ),
        ])
        mock_config.return_value = cfg
        model, prompt = get_assignment_for_item(_make_item("x", issue_type="bug"))
        assert model == "claude-sonnet-4.5"

    @patch('pokepoke.model_selection.get_config')
    def test_returns_prompt_template(self, mock_config: Mock) -> None:
        cfg = ProjectConfig()
        cfg.assignment = AssignmentConfig(rules=[
            AssignmentRule(
                match=AssignmentRuleMatch(issue_type="feature"),
                model="claude-opus-4.6",
                prompt_template="feature-item",
            ),
        ])
        mock_config.return_value = cfg
        model, prompt = get_assignment_for_item(
            _make_item("x", issue_type="feature")
        )
        assert model == "claude-opus-4.6"
        assert prompt == "feature-item"


class TestSelectModelWithAssignmentRules:
    """Test select_model_for_item when assignment rules are configured."""

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_rule_takes_priority_over_ab(
        self, mock_config: Mock, mock_weights: Mock
    ) -> None:
        """When a rule matches, its model is used instead of A/B selection."""
        cfg = ProjectConfig()
        cfg.models = ModelConfig(candidate_models=["modelA", "modelB"])
        cfg.assignment = AssignmentConfig(rules=[
            AssignmentRule(
                match=AssignmentRuleMatch(issue_type="bug"),
                model="bug-model",
            ),
        ])
        mock_config.return_value = cfg
        mock_weights.return_value = {}

        model = select_model_for_item(_make_item("x", issue_type="bug"))
        assert model == "bug-model"
        # get_model_weights should not be called when rule matches
        mock_weights.assert_not_called()

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_fallback_to_ab_when_no_rule_matches(
        self, mock_config: Mock, mock_weights: Mock
    ) -> None:
        """When no rule matches and fallback is 'weighted', use A/B selection."""
        cfg = ProjectConfig()
        cfg.models = ModelConfig(candidate_models=["modelA", "modelB"])
        cfg.assignment = AssignmentConfig(
            rules=[
                AssignmentRule(
                    match=AssignmentRuleMatch(issue_type="epic"),
                    model="epic-model",
                ),
            ],
            fallback="weighted",
        )
        mock_config.return_value = cfg
        mock_weights.return_value = {"modelA": 1.0, "modelB": 1.0}

        model = select_model_for_item(_make_item("x", issue_type="task"))
        assert model in ["modelA", "modelB"]

    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_fallback_to_specific_model(
        self, mock_config: Mock, mock_weights: Mock
    ) -> None:
        """When fallback is a specific model name, use it directly."""
        cfg = ProjectConfig()
        cfg.models = ModelConfig(candidate_models=["modelA"])
        cfg.assignment = AssignmentConfig(fallback="my-fallback-model")
        mock_config.return_value = cfg
        mock_weights.return_value = {}

        model = select_model_for_item(_make_item("x"))
        assert model == "my-fallback-model"
        mock_weights.assert_not_called()
