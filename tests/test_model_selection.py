"""Unit tests for model_selection module."""

from unittest.mock import Mock, patch
import pytest

from pokepoke.model_selection import select_model_for_item, select_gate_model
from pokepoke.config import ProjectConfig, ModelConfig


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
        weights_arg = call_args[1]['weights']
        
        assert "claude-opus-4.6" not in candidates_arg
        assert "gpt-5.1-codex" in candidates_arg
        assert "gpt-5" in candidates_arg
        assert gate_model == "gpt-5.1-codex"


class TestSelectModelForItem:
    """Test select_model_for_item function (existing functionality)."""
    
    @patch('pokepoke.model_selection.get_model_weights')
    @patch('pokepoke.model_selection.get_config')
    def test_returns_default_when_no_candidates(
        self, mock_get_config: Mock, mock_get_weights: Mock
    ) -> None:
        """Test that default model is returned when no candidates configured."""
        mock_config = ProjectConfig()
        mock_config.models = ModelConfig(
            default="claude-opus-4.6",
            candidate_models=[]
        )
        mock_get_config.return_value = mock_config
        mock_get_weights.return_value = {}
        
        model = select_model_for_item("test-123")
        
        assert model == "claude-opus-4.6"
    
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
        
        model = select_model_for_item("test-123")
        
        assert model in ["gpt-5.1-codex", "claude-sonnet-4.5"]
