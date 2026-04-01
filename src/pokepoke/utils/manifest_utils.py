"""Generic JSON-manifest helpers (load / save / get-path).

Several modules persist small JSON "manifest" files inside the .pokepoke
directory (e.g. uncleaned worktrees, failed unassigns).  This module
eliminates the copy-paste duplication by providing a single implementation
with consistent error handling and atomic writes.
"""

import contextlib
import json
import logging
from pathlib import Path
from typing import cast

from pokepoke.types import RetryConfig
from pokepoke.utils.constants import DEFAULT_ENCODING, POKEPOKE_DIR
from pokepoke.utils.retry_utils import sleep_with_backoff

logger = logging.getLogger(__name__)

# Type alias for the manifest data structure used throughout PokePoke.
ManifestData = dict[str, dict[str, str]]


def get_manifest_path(filename: str) -> Path:
    """Return the path to a manifest file inside the .pokepoke directory."""
    return POKEPOKE_DIR / filename


def load_manifest_from_path(manifest_path: Path) -> ManifestData:
    """Load a JSON manifest file from *manifest_path*, returning ``{}`` on any error."""
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding=DEFAULT_ENCODING) as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return cast(ManifestData, raw)
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_manifest_to_path(
    manifest_path: Path,
    manifest: ManifestData,
    *,
    warn_context: str = "",
) -> None:
    """Atomically save a JSON manifest file via write-then-rename.

    Parameters
    ----------
    manifest_path:
        Full path to the manifest file.
    manifest:
        Data to persist.
    warn_context:
        Optional human-readable context appended to the warning log
        when the write fails (e.g. worktree paths that may become orphaned).
    """
    max_retries = 5
    retry_delay = 0.05
    try:
        manifest_path.parent.mkdir(exist_ok=True)
    except OSError as e:
        logger.warning("Failed to save manifest %s: %s", manifest_path, e)
        if warn_context:
            logger.warning("%s", warn_context)
        return
    tmp = manifest_path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding=DEFAULT_ENCODING,
        )
    except OSError as e:
        logger.warning("Failed to save manifest %s: %s", manifest_path, e)
        if warn_context:
            logger.warning("%s", warn_context)
        return
    # Retry the rename; on Windows the target can be briefly locked by
    # antivirus / indexer even when our own file lock is held.
    retry_config = RetryConfig(
        max_retries=max_retries,
        initial_delay=retry_delay,
        backoff_factor=1.0,  # Linear backoff (delay * (attempt + 1))
        jitter=True,
    )
    for attempt in range(max_retries):
        try:
            tmp.replace(manifest_path)
            return
        except OSError:
            if attempt < max_retries - 1:
                # Use linear backoff for manifest: delay * (attempt + 1)
                sleep_with_backoff(attempt, retry_config, f'manifest save {manifest_path.name}')
    # All retries exhausted – clean up and warn
    with contextlib.suppress(OSError):
        tmp.unlink(missing_ok=True)
    logger.warning("Failed to save manifest %s after %d retries", manifest_path, max_retries)
    if warn_context:
        logger.warning("%s", warn_context)
