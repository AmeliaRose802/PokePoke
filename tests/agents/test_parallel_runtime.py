"""Tests for pokepoke.agents.parallel_runtime — runtime parallel agent limits."""

from pokepoke.agents.parallel_runtime import (
    clear_runtime_parallel_limits,
    compute_effective_max_agents,
    set_runtime_parallel_limits,
)


class TestComputeEffectiveMaxAgents:
    """Tests for compute_effective_max_agents function."""

    def setup_method(self) -> None:
        clear_runtime_parallel_limits()

    def teardown_method(self) -> None:
        clear_runtime_parallel_limits()

    def test_returns_dynamic_max_when_no_cap(self) -> None:
        result = compute_effective_max_agents(4)
        assert result == 4

    def test_returns_cap_when_cli_override_and_baseline_matches(self) -> None:
        set_runtime_parallel_limits(effective_parallel=3, cli_override=True, baseline=4)
        result = compute_effective_max_agents(4)
        assert result == 3

    def test_returns_capped_dynamic_when_config_changed(self) -> None:
        """Covers line 44: return max(1, min(cap, dynamic_max))."""
        set_runtime_parallel_limits(effective_parallel=3, cli_override=True, baseline=4)
        # dynamic_max differs from baseline, so cap is applied as min
        result = compute_effective_max_agents(6)
        assert result == 3

    def test_capped_dynamic_never_below_one(self) -> None:
        """Covers line 44: clamped to min 1."""
        set_runtime_parallel_limits(effective_parallel=1, cli_override=True, baseline=4)
        # dynamic_max=5 differs from baseline=4, min(1,5)=1, max(1,1)=1
        result = compute_effective_max_agents(5)
        assert result == 1

    def test_returns_dynamic_when_no_cli_override(self) -> None:
        set_runtime_parallel_limits(effective_parallel=2, cli_override=False, baseline=4)
        result = compute_effective_max_agents(6)
        assert result == 6


class TestSetAndClearLimits:
    """Tests for set/clear runtime limits."""

    def setup_method(self) -> None:
        clear_runtime_parallel_limits()

    def teardown_method(self) -> None:
        clear_runtime_parallel_limits()

    def test_set_then_clear_resets(self) -> None:
        set_runtime_parallel_limits(effective_parallel=2, cli_override=True, baseline=4)
        clear_runtime_parallel_limits()
        result = compute_effective_max_agents(4)
        assert result == 4

    def test_set_without_baseline(self) -> None:
        set_runtime_parallel_limits(effective_parallel=3, cli_override=True, baseline=None)
        # baseline is None → goes to line 44 path
        result = compute_effective_max_agents(5)
        assert result == 3
