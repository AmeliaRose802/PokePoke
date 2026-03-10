"""Performance timing infrastructure for PokePoke operations.

Provides a centralized, thread-safe timing registry with a decorator and
context manager for recording wall-clock durations of operations.

Usage::

    from pokepoke.perf_timing import timed_operation, timed_block, get_registry

    @timed_operation("worktree.create")
    def create_worktree(...):
        ...

    with timed_block("merge_queue.rebase"):
        do_rebase()

    registry = get_registry()
    print(registry.percentile("worktree.create", 95))
"""

from __future__ import annotations

import functools
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any, TypeVar, overload
from collections.abc import Callable

_F = TypeVar("_F", bound=Callable[..., Any])


class OperationTimingRegistry:
    """Thread-safe registry of operation timings (name → list of durations).

    Each call to :meth:`record` appends a wall-clock duration (in seconds) to
    the list associated with *name*.  Percentile queries over the stored
    durations are supported via :meth:`percentile`.
    """

    def __init__(self, max_samples: int = 10_000) -> None:
        self._lock = threading.Lock()
        self._timings: dict[str, list[float]] = defaultdict(list)
        self._max_samples = max_samples

    def record(self, name: str, duration: float) -> None:
        """Record a single duration (seconds) for *name*."""
        with self._lock:
            samples = self._timings[name]
            if len(samples) >= self._max_samples:
                # Evict oldest half to bound memory usage
                del samples[: len(samples) // 2]
            samples.append(duration)

    def percentile(self, name: str, p: float) -> float | None:
        """Return the *p*-th percentile (0–100) for *name*, or ``None`` if no data."""
        with self._lock:
            samples = self._timings.get(name)
            if not samples:
                return None
            return _percentile(samples, p)

    def p50(self, name: str) -> float | None:
        """Shorthand for the 50th percentile (median)."""
        return self.percentile(name, 50)

    def p95(self, name: str) -> float | None:
        """Shorthand for the 95th percentile."""
        return self.percentile(name, 95)

    def p99(self, name: str) -> float | None:
        """Shorthand for the 99th percentile."""
        return self.percentile(name, 99)

    def count(self, name: str) -> int:
        """Return the number of recorded samples for *name*."""
        with self._lock:
            return len(self._timings.get(name, []))

    def mean(self, name: str) -> float | None:
        """Return the arithmetic mean for *name*, or ``None`` if no data."""
        with self._lock:
            samples = self._timings.get(name)
            if not samples:
                return None
            return sum(samples) / len(samples)

    def total(self, name: str) -> float:
        """Return the total accumulated duration for *name*."""
        with self._lock:
            return sum(self._timings.get(name, []))

    def names(self) -> list[str]:
        """Return a sorted list of all recorded operation names."""
        with self._lock:
            return sorted(self._timings.keys())

    def snapshot(self, name: str) -> list[float]:
        """Return a copy of all recorded durations for *name*."""
        with self._lock:
            return list(self._timings.get(name, []))

    def summary(self) -> dict[str, dict[str, Any]]:
        """Return a summary dict of all operations with count, p50, p95, p99, mean, total."""
        with self._lock:
            result: dict[str, dict[str, Any]] = {}
            for name, samples in sorted(self._timings.items()):
                if not samples:
                    continue
                result[name] = {
                    "count": len(samples),
                    "mean": round(sum(samples) / len(samples), 6),
                    "total": round(sum(samples), 6),
                    "p50": round(_percentile(samples, 50), 6),
                    "p95": round(_percentile(samples, 95), 6),
                    "p99": round(_percentile(samples, 99), 6),
                    "min": round(min(samples), 6),
                    "max": round(max(samples), 6),
                }
            return result

    def clear(self, name: str | None = None) -> None:
        """Clear timings for *name*, or all timings if *name* is ``None``."""
        with self._lock:
            if name is None:
                self._timings.clear()
            else:
                self._timings.pop(name, None)


def _percentile(sorted_or_unsorted: list[float], p: float) -> float:
    """Compute the *p*-th percentile (0–100) using linear interpolation."""
    data = sorted(sorted_or_unsorted)
    n = len(data)
    if n == 0:
        raise ValueError("Cannot compute percentile of empty list")
    if n == 1:
        return data[0]
    # Map p to a fractional index
    k = (p / 100.0) * (n - 1)
    lo = int(k)
    hi = min(lo + 1, n - 1)
    frac = k - lo
    return data[lo] + frac * (data[hi] - data[lo])


# ── Module-level singleton ───────────────────────────────────────────

_global_registry: OperationTimingRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> OperationTimingRegistry:
    """Return the module-level singleton registry (created on first call)."""
    global _global_registry
    if _global_registry is not None:
        return _global_registry
    with _registry_lock:
        if _global_registry is None:
            _global_registry = OperationTimingRegistry()
        return _global_registry


def reset_registry() -> None:
    """Replace the global registry with a fresh instance. For tests only."""
    global _global_registry
    with _registry_lock:
        _global_registry = OperationTimingRegistry()


# ── Decorator ────────────────────────────────────────────────────────

@overload
def timed_operation(name: str) -> Callable[[_F], _F]: ...

@overload
def timed_operation(name: str, registry: OperationTimingRegistry) -> Callable[[_F], _F]: ...

def timed_operation(
    name: str, registry: OperationTimingRegistry | None = None
) -> Callable[[_F], _F]:
    """Decorator that records wall-clock duration of the wrapped function.

    Usage::

        @timed_operation("worktree.create")
        def create_worktree(...):
            ...
    """
    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            reg = registry or get_registry()
            start = time.monotonic()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.monotonic() - start
                reg.record(name, elapsed)
        return wrapper  # type: ignore[return-value]
    return decorator


# ── Context manager ──────────────────────────────────────────────────

@contextmanager
def timed_block(
    name: str, registry: OperationTimingRegistry | None = None
) -> Iterator[None]:
    """Context manager that records wall-clock duration of the enclosed block.

    Usage::

        with timed_block("merge_queue.rebase"):
            do_rebase()
    """
    reg = registry or get_registry()
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        reg.record(name, elapsed)
