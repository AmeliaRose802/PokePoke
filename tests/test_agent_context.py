"""Tests for per-thread agent context isolation (PokePoke-furd)."""

import os
import threading
from unittest.mock import patch

import pytest

from pokepoke.agent_context import (
    clear_agent_name,
    get_agent_name,
    set_agent_name,
)


class TestGetAgentName:
    """Tests for get_agent_name resolution order."""

    def setup_method(self) -> None:
        """Ensure a clean thread-local state before every test."""
        clear_agent_name()

    def teardown_method(self) -> None:
        clear_agent_name()

    def test_returns_default_when_nothing_set(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert get_agent_name() == "agent"

    def test_returns_custom_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert get_agent_name(default="fallback") == "fallback"

    def test_env_var_takes_precedence_over_default(self) -> None:
        with patch.dict(os.environ, {"AGENT_NAME": "env_agent"}):
            assert get_agent_name() == "env_agent"

    def test_thread_local_takes_precedence_over_env(self) -> None:
        with patch.dict(os.environ, {"AGENT_NAME": "env_agent"}):
            set_agent_name("thread_agent")
            assert get_agent_name() == "thread_agent"

    def test_clear_falls_back_to_env(self) -> None:
        with patch.dict(os.environ, {"AGENT_NAME": "env_agent"}):
            set_agent_name("thread_agent")
            clear_agent_name()
            assert get_agent_name() == "env_agent"


class TestSetAgentName:
    """Tests for set_agent_name."""

    def teardown_method(self) -> None:
        clear_agent_name()

    def test_set_and_get(self) -> None:
        set_agent_name("my_worker")
        assert get_agent_name() == "my_worker"

    def test_overwrite(self) -> None:
        set_agent_name("first")
        set_agent_name("second")
        assert get_agent_name() == "second"


class TestClearAgentName:
    """Tests for clear_agent_name."""

    def test_clear_removes_thread_local(self) -> None:
        set_agent_name("temp")
        clear_agent_name()
        with patch.dict(os.environ, {}, clear=True):
            assert get_agent_name() == "agent"


class TestThreadIsolation:
    """Verify that different threads see different agent names."""

    def test_threads_get_independent_names(self) -> None:
        """Each thread should resolve its own name without cross-talk."""
        results: dict[str, str] = {}
        barrier = threading.Barrier(3)

        def worker(name: str) -> None:
            set_agent_name(name)
            barrier.wait()  # ensure all threads have set their names
            results[name] = get_agent_name()
            clear_agent_name()

        threads = [
            threading.Thread(target=worker, args=(f"worker-{i}",))
            for i in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert results == {
            "worker-0": "worker-0",
            "worker-1": "worker-1",
            "worker-2": "worker-2",
        }

    def test_main_thread_unaffected_by_worker(self) -> None:
        """Setting an agent name in a worker must not mutate the main thread."""
        set_agent_name("main_agent")

        def worker() -> None:
            set_agent_name("child_agent")

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)

        assert get_agent_name() == "main_agent"
        clear_agent_name()

    def test_clear_in_worker_does_not_affect_main(self) -> None:
        set_agent_name("main")

        def worker() -> None:
            set_agent_name("child")
            clear_agent_name()

        t = threading.Thread(target=worker)
        t.start()
        t.join(timeout=5)

        assert get_agent_name() == "main"
        clear_agent_name()

    def test_env_fallback_shared_across_threads(self) -> None:
        """When no thread-local is set, all threads see the env var."""
        results: dict[int, str] = {}

        def worker(idx: int) -> None:
            results[idx] = get_agent_name()

        with patch.dict(os.environ, {"AGENT_NAME": "shared_env"}):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

        assert all(v == "shared_env" for v in results.values())
