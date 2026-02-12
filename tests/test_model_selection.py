"""Unit tests for model_selection module."""

from unittest.mock import patch, MagicMock

from src.pokepoke.model_selection import select_model_for_item


class TestSelectModelForItem:
    """Test select_model_for_item function."""

    @patch('src.pokepoke.model_selection.get_model_weights')
    @patch('src.pokepoke.model_selection.get_config')
    def test_returns_default_when_no_candidates(
        self, mock_config: MagicMock, mock_weights: MagicMock
    ) -> None:
        """When candidate_models is empty, return the default model."""
        config = MagicMock()
        config.models.candidate_models = []
        config.models.default = "claude-opus-4.6"
        mock_config.return_value = config

        result = select_model_for_item("item-1")

        assert result == "claude-opus-4.6"
        mock_weights.assert_not_called()

    @patch('src.pokepoke.model_selection.random.choices')
    @patch('src.pokepoke.model_selection.get_model_weights')
    @patch('src.pokepoke.model_selection.get_config')
    def test_selects_from_candidates_with_weights(
        self, mock_config: MagicMock, mock_weights: MagicMock,
        mock_choices: MagicMock
    ) -> None:
        """When candidates exist, use weighted random selection."""
        config = MagicMock()
        config.models.candidate_models = ["model-a", "model-b"]
        config.models.default = "default-model"
        mock_config.return_value = config
        mock_weights.return_value = {"model-a": 0.8, "model-b": 0.5}
        mock_choices.return_value = ["model-a"]

        result = select_model_for_item("item-2")

        assert result == "model-a"
        mock_choices.assert_called_once_with(
            ["model-a", "model-b"], weights=[0.8, 0.5], k=1
        )

    @patch('src.pokepoke.model_selection.random.choices')
    @patch('src.pokepoke.model_selection.get_model_weights')
    @patch('src.pokepoke.model_selection.get_config')
    def test_uniform_weights_when_no_history(
        self, mock_config: MagicMock, mock_weights: MagicMock,
        mock_choices: MagicMock
    ) -> None:
        """When no historical data, all weights should be 1.0 (uniform)."""
        config = MagicMock()
        config.models.candidate_models = ["model-a", "model-b"]
        config.models.default = "default-model"
        mock_config.return_value = config
        mock_weights.return_value = {}  # No history
        mock_choices.return_value = ["model-b"]

        result = select_model_for_item("item-3")

        assert result == "model-b"
        mock_choices.assert_called_once_with(
            ["model-a", "model-b"], weights=[1.0, 1.0], k=1
        )

    @patch('src.pokepoke.model_selection.random.choices')
    @patch('src.pokepoke.model_selection.get_model_weights')
    @patch('src.pokepoke.model_selection.get_config')
    def test_weighted_mode_printed(
        self, mock_config: MagicMock, mock_weights: MagicMock,
        mock_choices: MagicMock, capsys
    ) -> None:
        """When weights differ, should print 'weighted' mode."""
        config = MagicMock()
        config.models.candidate_models = ["model-a", "model-b"]
        config.models.default = "default-model"
        mock_config.return_value = config
        mock_weights.return_value = {"model-a": 0.9, "model-b": 0.3}
        mock_choices.return_value = ["model-a"]

        select_model_for_item("item-4")

        captured = capsys.readouterr()
        assert "weighted" in captured.out
        assert "model-a" in captured.out

    @patch('src.pokepoke.model_selection.random.choices')
    @patch('src.pokepoke.model_selection.get_model_weights')
    @patch('src.pokepoke.model_selection.get_config')
    def test_uniform_mode_printed(
        self, mock_config: MagicMock, mock_weights: MagicMock,
        mock_choices: MagicMock, capsys
    ) -> None:
        """When all weights equal, should print 'uniform' mode."""
        config = MagicMock()
        config.models.candidate_models = ["model-a", "model-b"]
        config.models.default = "default-model"
        mock_config.return_value = config
        mock_weights.return_value = {}
        mock_choices.return_value = ["model-a"]

        select_model_for_item("item-5")

        captured = capsys.readouterr()
        assert "uniform" in captured.out
