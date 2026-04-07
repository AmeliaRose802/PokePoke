"""Tests for pokepoke.utils.memory_utils module."""
from __future__ import annotations

import pytest

from pokepoke.utils.memory_utils import (
    apply_memory_backpressure,
    get_available_memory_mb,
    get_cpu_usage_percent,
    get_process_rss_mb,
    is_memory_critical,
    is_memory_pressure,
)


class TestGetAvailableMemoryMb:
    """Tests for get_available_memory_mb function."""

    def test_returns_non_negative(self) -> None:
        """Should return non-negative value or 0 on failure."""
        result = get_available_memory_mb()
        assert result >= 0

    def test_caching_behavior(self) -> None:
        """Sequential calls should use cache within TTL."""
        first = get_available_memory_mb()
        second = get_available_memory_mb()
        # Both should succeed (or both fail)
        assert first == second or (first == 0 and second >= 0)


class TestGetProcessRssMb:
    """Tests for get_process_rss_mb function."""

    def test_returns_non_negative(self) -> None:
        """Should return non-negative value or 0 if psutil unavailable."""
        result = get_process_rss_mb()
        assert result >= 0

    def test_caching_behavior(self) -> None:
        """Sequential calls should use cache within TTL."""
        first = get_process_rss_mb()
        second = get_process_rss_mb()
        # If psutil is available, should return same cached value
        if first > 0:
            assert second == first


class TestGetCpuUsagePercent:
    """Tests for get_cpu_usage_percent function."""

    def test_returns_valid_percentage(self) -> None:
        """Should return value in range 0.0-100.0 or 0.0 on failure."""
        result = get_cpu_usage_percent()
        assert 0.0 <= result <= 100.0

    def test_returns_float(self) -> None:
        """Should return a float value."""
        result = get_cpu_usage_percent()
        assert isinstance(result, float)

    def test_caching_behavior(self) -> None:
        """Sequential calls should use cache within TTL."""
        first = get_cpu_usage_percent()
        second = get_cpu_usage_percent()
        # If psutil is available, should return same cached value
        if first > 0.0:
            assert second == first

    def test_handles_psutil_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return 0.0 when psutil is not available."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "_HAS_PSUTIL", False)
        result = get_cpu_usage_percent()
        assert result == 0.0


class TestIsMemoryPressure:
    """Tests for is_memory_pressure function."""

    def test_returns_true_on_windows_when_monitoring_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return True on Windows when get_available_memory_mb returns 0 (fail closed)."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 0)
        monkeypatch.setattr(mem_utils.os, "name", "nt")
        result = is_memory_pressure()
        assert result is True

    def test_returns_false_on_non_windows_when_monitoring_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return False on non-Windows when monitoring is unavailable (expected behavior)."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 0)
        monkeypatch.setattr(mem_utils.os, "name", "posix")
        result = is_memory_pressure()
        assert result is False

    def test_returns_true_when_below_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return True when available memory < 2048 MB."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 1500)
        result = is_memory_pressure()
        assert result is True

    def test_returns_false_when_above_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return False when available memory >= 2048 MB."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 3000)
        result = is_memory_pressure()
        assert result is False


class TestIsMemoryCritical:
    """Tests for is_memory_critical function."""

    def test_returns_true_on_windows_when_monitoring_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return True on Windows when get_available_memory_mb returns 0 (fail closed)."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 0)
        monkeypatch.setattr(mem_utils.os, "name", "nt")
        result = is_memory_critical()
        assert result is True

    def test_returns_false_on_non_windows_when_monitoring_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return False on non-Windows when monitoring is unavailable (expected behavior)."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 0)
        monkeypatch.setattr(mem_utils.os, "name", "posix")
        result = is_memory_critical()
        assert result is False

    def test_returns_true_when_below_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return True when available memory < 1024 MB."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 500)
        result = is_memory_critical()
        assert result is True

    def test_returns_false_when_above_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return False when available memory >= 1024 MB."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 2000)
        result = is_memory_critical()
        assert result is False


class TestApplyMemoryBackpressure:
    """Tests for apply_memory_backpressure function."""

    def test_returns_zero_on_windows_when_monitoring_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return 0 slots on Windows when monitoring fails (fail closed via is_memory_critical)."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 0)
        monkeypatch.setattr(mem_utils.os, "name", "nt")
        adjusted, avail = apply_memory_backpressure(5)
        assert adjusted == 0  # Critical backpressure applied
        assert avail == 0

    def test_returns_slots_on_non_windows_when_monitoring_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return original slots on non-Windows when monitoring unavailable (expected behavior)."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 0)
        monkeypatch.setattr(mem_utils.os, "name", "posix")
        adjusted, avail = apply_memory_backpressure(5)
        assert adjusted == 5  # No backpressure on non-Windows
        assert avail == 0

    def test_returns_zero_when_critical(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return 0 slots when memory is critical."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 500)
        adjusted, avail = apply_memory_backpressure(5)
        assert adjusted == 0
        assert avail == 500

    def test_limits_slots_when_under_pressure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should limit to 1 slot when under pressure."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 1500)
        adjusted, avail = apply_memory_backpressure(5)
        assert adjusted == 1
        assert avail == 1500

    def test_returns_zero_when_under_pressure_and_zero_slots(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return 0 slots when already 0 and under pressure."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 1500)
        adjusted, avail = apply_memory_backpressure(0)
        assert adjusted == 0
        assert avail == 1500

    def test_returns_slots_when_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should return original slots when memory is healthy."""
        import pokepoke.utils.memory_utils as mem_utils
        monkeypatch.setattr(mem_utils, "get_available_memory_mb", lambda: 4000)
        adjusted, avail = apply_memory_backpressure(5)
        assert adjusted == 5
        assert avail == 4000
