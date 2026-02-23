"""Tests for model pricing and cost calculation."""

import pytest
from pokepoke.model_pricing import calculate_cost, get_model_pricing, MODEL_PRICING


class TestCalculateCost:
    """Tests for the calculate_cost function."""

    def test_claude_opus_cost(self):
        """Test cost calculation for Claude Opus 4.6."""
        cost = calculate_cost("claude-opus-4.6", 10_000, 5_000)
        # 10k input * $15/M + 5k output * $75/M = $0.15 + $0.375 = $0.525
        assert cost == pytest.approx(0.525, abs=0.001)

    def test_claude_sonnet_cost(self):
        """Test cost calculation for Claude Sonnet 4.6."""
        cost = calculate_cost("claude-sonnet-4.6", 100_000, 50_000)
        # 100k input * $3/M + 50k output * $15/M = $0.30 + $0.75 = $1.05
        assert cost == pytest.approx(1.05, abs=0.001)

    def test_claude_haiku_cost(self):
        """Test cost calculation for Claude Haiku 4.5."""
        cost = calculate_cost("claude-haiku-4.5", 1_000_000, 500_000)
        # 1M input * $0.80/M + 500k output * $4/M = $0.80 + $2.00 = $2.80
        assert cost == pytest.approx(2.80, abs=0.001)

    def test_gpt_5_cost(self):
        """Test cost calculation for GPT-5.1."""
        cost = calculate_cost("gpt-5.1", 20_000, 10_000)
        # 20k input * $10/M + 10k output * $30/M = $0.20 + $0.30 = $0.50
        assert cost == pytest.approx(0.50, abs=0.001)

    def test_zero_tokens(self):
        """Test cost calculation with zero tokens."""
        cost = calculate_cost("claude-opus-4.6", 0, 0)
        assert cost == 0.0

    def test_unknown_model(self):
        """Test cost calculation for unknown model returns 0."""
        cost = calculate_cost("unknown-model", 10_000, 5_000)
        assert cost == 0.0

    def test_very_small_usage(self):
        """Test cost calculation for very small token usage."""
        cost = calculate_cost("claude-opus-4.6", 100, 50)
        # 100 input * $15/M + 50 output * $75/M = $0.0015 + $0.00375 = $0.00525
        assert cost == pytest.approx(0.00525, abs=0.00001)


class TestGetModelPricing:
    """Tests for the get_model_pricing function."""

    def test_get_claude_opus_pricing(self):
        """Test retrieving pricing for Claude Opus 4.6."""
        pricing = get_model_pricing("claude-opus-4.6")
        assert pricing is not None
        assert pricing == (15.00, 75.00)

    def test_get_claude_sonnet_pricing(self):
        """Test retrieving pricing for Claude Sonnet 4.6."""
        pricing = get_model_pricing("claude-sonnet-4.6")
        assert pricing is not None
        assert pricing == (3.00, 15.00)

    def test_get_unknown_model_pricing(self):
        """Test retrieving pricing for unknown model returns None."""
        pricing = get_model_pricing("unknown-model")
        assert pricing is None


class TestModelPricingData:
    """Tests for the MODEL_PRICING data structure."""

    def test_all_models_have_two_prices(self):
        """Verify all models have both input and output pricing."""
        for model, pricing in MODEL_PRICING.items():
            assert len(pricing) == 2, f"Model {model} should have 2 prices"
            assert pricing[0] > 0, f"Model {model} input price should be positive"
            assert pricing[1] > 0, f"Model {model} output price should be positive"

    def test_output_price_higher_than_input(self):
        """Verify output tokens are always more expensive than input tokens."""
        for model, (input_price, output_price) in MODEL_PRICING.items():
            assert output_price >= input_price, f"Model {model} output should cost >= input"

    def test_common_models_present(self):
        """Verify common models are in the pricing table."""
        expected_models = [
            "claude-opus-4.6",
            "claude-sonnet-4.6",
            "claude-haiku-4.5",
            "gpt-5.1",
            "gpt-5.2",
        ]
        for model in expected_models:
            assert model in MODEL_PRICING, f"Model {model} should be in pricing table"
