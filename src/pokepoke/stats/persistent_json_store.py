"""Generic persistence helper for small JSON stores.

Several PokePoke stats modules persist a JSON document with an append-only
"log" plus a derived "summary". Historically those modules copy-pasted the
same patterns:

- validate-or-empty on load
- atomic write (tmp file then replace) with Windows retry
- intra-process (thread) + cross-process (file) locking

PersistentJsonStore centralizes that plumbing so individual stores can focus
on their schema and summary rebuild logic.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager, nullcontext, suppress
from pathlib import Path
from typing import Any

from pokepoke.utils.file_utils import replace_with_retry
from pokepoke.worktrees.coordination import acquire_lock

JsonDict = dict[str, Any]


class PersistentJsonStore:
    """A tiny JSON persistence wrapper with locking and atomic writes."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        default_path: Path,
        empty: Callable[[], JsonDict],
        thread_lock: threading.Lock | None = None,
        lock_name: str | None = None,
        lock_name_resolver: Callable[[], str] | None = None,
        path_resolver: Callable[[Path | None], Path] | None = None,
        normalize: Callable[[Any], JsonDict] | None = None,
        indent: int = 2,
    ) -> None:
        if lock_name is not None and lock_name_resolver is not None:
            raise ValueError("Provide lock_name OR lock_name_resolver, not both")

        self._default_path = default_path
        self._empty = empty
        self._thread_lock = thread_lock
        self._lock_name = lock_name
        self._lock_name_resolver = lock_name_resolver
        self._path_resolver = path_resolver
        self._normalize = normalize
        self._indent = int(indent)

    def resolve_path(self, path: Path | None = None) -> Path:
        if self._path_resolver is not None:
            return self._path_resolver(path)
        return path or self._default_path

    def resolve_lock_name(self) -> str:
        if self._lock_name_resolver is not None:
            return self._lock_name_resolver()
        return self._lock_name or ""

    def load(self, path: Path | None = None) -> JsonDict:
        stats_path = self.resolve_path(path)
        if not stats_path.exists():
            return self._empty()

        try:
            with stats_path.open(encoding="utf-8") as f:
                data: Any = json.load(f)
        except (json.JSONDecodeError, OSError):
            return self._empty()

        if self._normalize is not None:
            try:
                normalized = self._normalize(data)
                if isinstance(normalized, dict):
                    return normalized
            except Exception:
                return self._empty()

        return data if isinstance(data, dict) else self._empty()

    def save(self, data: JsonDict, path: Path | None = None) -> None:
        stats_path = self.resolve_path(path)
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = stats_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=self._indent)
            f.flush()
            with suppress(OSError):
                os.fsync(f.fileno())
        replace_with_retry(tmp_path, stats_path)

    @contextmanager
    def lock(self, *, timeout: float = 60) -> Generator[None, None, None]:
        """Acquire thread + cross-process locks to serialize read-modify-write."""
        thread_cm = self._thread_lock if self._thread_lock is not None else nullcontext()
        lock_name = self.resolve_lock_name()
        if lock_name:
            with thread_cm, acquire_lock(lock_name, timeout=timeout):
                yield
        else:
            with thread_cm:
                yield
