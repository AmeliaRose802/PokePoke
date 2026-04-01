"""Centralized retry utilities with jitter support."""
import logging
import random
import time

from pokepoke.types import RetryConfig

logger = logging.getLogger(__name__)


def calculate_backoff_delay(
    attempt: int,
    config: RetryConfig,
) -> float:
    """
    Calculate backoff delay with optional jitter.

    Supports two modes controlled by ``config.backoff_mode``:
    - ``"exponential"``: ``initial_delay * backoff_factor ** attempt``
    - ``"linear"``: ``initial_delay * (attempt + 1)``

    Args:
        attempt: Current attempt number (0-indexed)
        config: Retry configuration with jitter, backoff_factor, initial_delay, max_delay

    Returns:
        Delay in seconds with jitter applied if config.jitter is True

    The jitter range is [0.5, 1.5] of the base delay, preventing synchronized
    retry storms when multiple agents encounter the same transient error.
    """
    if config.backoff_mode == "linear":
        base_delay = config.initial_delay * (attempt + 1)
    else:
        # Exponential backoff (default)
        base_delay = config.initial_delay * (config.backoff_factor ** attempt)

    # Cap at max_delay
    base_delay = min(base_delay, config.max_delay)

    # Apply jitter if enabled
    if config.jitter:
        # Random multiplier in range [0.5, 1.5] to desynchronize retries
        jitter_factor = random.uniform(0.5, 1.5)
        return base_delay * jitter_factor

    return base_delay


def sleep_with_backoff(
    attempt: int,
    config: RetryConfig,
    context: str | None = None,
) -> float:
    """
    Sleep for calculated backoff delay with optional jitter.

    Args:
        attempt: Current attempt number (0-indexed)
        config: Retry configuration
        context: Optional context string for logging

    Returns:
        Actual delay used (for testing/logging)
    """
    delay = calculate_backoff_delay(attempt, config)

    if context:
        logger.debug(f"Sleeping {delay:.2f}s (attempt {attempt + 1}, jitter={config.jitter}): {context}")

    time.sleep(delay)
    return delay
