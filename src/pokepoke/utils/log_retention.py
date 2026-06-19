"""Helpers for bounding PokePoke run-log directory growth."""

import re
import shutil
from pathlib import Path

# Matches run-id directory names (``YYYYMMDD_HHMMSS_<short-uuid>``) so pruning
# only ever touches directories the run logger created.
RUN_ID_PATTERN = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}$")


def prune_old_run_dirs(base_dir: Path, max_runs: int, keep_name: str) -> None:
    """Delete old run directories, keeping the most recent ``max_runs``.

    Only directories whose names match the run-id format are considered, so
    unrelated files/folders under ``base_dir`` are never touched. ``keep_name``
    (the current run) is always preserved. Deletion failures (e.g. Windows file
    locks) are ignored so logging never aborts a run. A non-positive
    ``max_runs`` disables pruning entirely.
    """
    if max_runs <= 0:
        return
    try:
        run_dirs = [
            entry
            for entry in base_dir.iterdir()
            if entry.is_dir() and RUN_ID_PATTERN.match(entry.name)
        ]
    except OSError:
        return
    if len(run_dirs) <= max_runs:
        return
    # Run ids are timestamp-prefixed, so lexicographic order is chronological.
    run_dirs.sort(key=lambda p: p.name)
    for stale in run_dirs[: len(run_dirs) - max_runs]:
        if stale.name == keep_name:
            continue
        shutil.rmtree(stale, ignore_errors=True)
