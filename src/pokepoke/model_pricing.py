"""Model pricing and cost calculation utilities.

Provides pricing information for various LLM models and calculates
costs based on token usage.
"""

from __future__ import annotations


# Pricing per million tokens (input, output) in USD
# Based on public pricing as of 2026-02
MODEL_PRICING = {
    # Claude models (Anthropic)
    "claude-opus-4.6": (15.00, 75.00),
    "claude-opus-4.5": (15.00, 75.00),
    "claude-sonnet-4.6": (3.00, 15.00),
    "claude-sonnet-4.5": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-4.5": (0.80, 4.00),

    # GPT models (OpenAI)
    "gpt-5.3-codex": (10.00, 30.00),
    "gpt-5.2-codex": (10.00, 30.00),
    "gpt-5.2": (10.00, 30.00),
    "gpt-5.1-codex-max": (10.00, 30.00),
    "gpt-5.1-codex": (10.00, 30.00),
    "gpt-5.1": (10.00, 30.00),
    "gpt-5.1-codex-mini": (2.00, 10.00),
    "gpt-5-mini": (2.00, 10.00),
    "gpt-5-codex": (10.00, 30.00),
    "gpt-4.1": (2.00, 10.00),

    # Gemini models (Google)
    "gemini-3-pro-preview": (1.25, 5.00),
    "gemini-3-pro": (1.25, 5.00),
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate the cost of an LLM request based on token usage.

    Args:
        model: The model name (e.g., "claude-opus-4.6")
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens generated

    Returns:
        Total cost in USD (float)

    Example:
        >>> calculate_cost("claude-opus-4.6", 10000, 5000)
        0.525  # $0.525 for 10k input + 5k output tokens
    """
    if model not in MODEL_PRICING:
        # Unknown model - return 0 cost rather than erroring
        return 0.0

    input_price_per_million, output_price_per_million = MODEL_PRICING[model]

    input_cost = (input_tokens / 1_000_000) * input_price_per_million
    output_cost = (output_tokens / 1_000_000) * output_price_per_million

    return input_cost + output_cost


# Context window sizes (total tokens) per model
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # Claude models
    "claude-opus-4.6": 200_000,
    "claude-opus-4.5": 200_000,
    "claude-sonnet-4.6": 200_000,
    "claude-sonnet-4.5": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4.5": 200_000,

    # GPT models
    "gpt-5.3-codex": 256_000,
    "gpt-5.2-codex": 256_000,
    "gpt-5.2": 128_000,
    "gpt-5.1-codex-max": 256_000,
    "gpt-5.1-codex": 256_000,
    "gpt-5.1": 128_000,
    "gpt-5.1-codex-mini": 128_000,
    "gpt-5-mini": 128_000,
    "gpt-5-codex": 256_000,
    "gpt-4.1": 128_000,

    # Gemini models
    "gemini-3-pro-preview": 1_000_000,
    "gemini-3-pro": 1_000_000,
}

DEFAULT_CONTEXT_WINDOW = 128_000


def get_context_window(model: str) -> int:
    """Get the context window size for a model.

    Returns:
        Context window size in tokens (defaults to 128K for unknown models)
    """
    return MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)


def get_model_pricing(model: str) -> tuple[float, float] | None:
    """Get the pricing for a specific model.

    Args:
        model: The model name

    Returns:
        Tuple of (input_price_per_million, output_price_per_million) in USD,
        or None if model pricing is unknown
    """
    return MODEL_PRICING.get(model)
