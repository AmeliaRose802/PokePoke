"""Shared file-system utilities for atomic writes on Windows."""

import os
from pathlib import Path

from pokepoke.types import RetryConfig
from pokepoke.utils.retry_utils import sleep_with_backoff


def replace_with_retry(src: Path, dst: Path, retries: int = 5, delay: float = 0.05) -> None:
    """Replace *dst* with *src*, retrying on PermissionError/FileNotFoundError (Windows)."""
    retry_config = RetryConfig(
        max_retries=retries,
        initial_delay=delay,
        backoff_factor=2.0,
        jitter=True,
    )
    for attempt in range(retries):
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(src), str(dst))
            return
        except (PermissionError, FileNotFoundError):
            if attempt == retries - 1:
                raise
            sleep_with_backoff(attempt, retry_config, f'file replace {dst.name}')
