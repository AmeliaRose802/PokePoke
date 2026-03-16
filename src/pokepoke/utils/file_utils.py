"""Shared file-system utilities for atomic writes on Windows."""

from __future__ import annotations

import os
import time
from pathlib import Path


def replace_with_retry(src: Path, dst: Path, retries: int = 5, delay: float = 0.05) -> None:
    """Replace *dst* with *src*, retrying on PermissionError (Windows)."""
    for attempt in range(retries):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(delay * (2 ** attempt))
