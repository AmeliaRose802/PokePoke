"""Runtime tracking for parallel agent limits.

This is kept separate from parallel.py to keep file size under the repo limit.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_cap: int | None = None
_cli_override: bool = False
_baseline: int | None = None


def set_runtime_parallel_limits(effective_parallel: int, cli_override: bool, baseline: int | None) -> None:
    global _cap, _cli_override, _baseline
    with _lock:
        _cap = max(1, int(effective_parallel))
        _cli_override = bool(cli_override)
        _baseline = baseline


def clear_runtime_parallel_limits() -> None:
    global _cap, _cli_override, _baseline
    with _lock:
        _cap = None
        _cli_override = False
        _baseline = None


def compute_effective_max_agents(dynamic_max: int) -> int:
    with _lock:
        cap = _cap
        cli_override = _cli_override
        baseline = _baseline

    if cap is None or not cli_override:
        return dynamic_max

    if baseline is not None and dynamic_max == baseline:
        return cap

    return max(1, min(cap, dynamic_max))
