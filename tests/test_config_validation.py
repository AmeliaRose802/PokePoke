"""Tests for pokepoke.config_validation module.

Covers ConfigError, clamp_with_warning() boundary logic, and logging behaviour.
"""

from __future__ import annotations

import logging

import pytest

from pokepoke.config_validation import ConfigError, clamp_with_warning


class TestConfigError:
    """Tests for the ConfigError exception."""

    def test_is_exception(self) -> None:
        assert issubclass(ConfigError, Exception)

    def test_message(self) -> None:
        err = ConfigError("bad value")
        assert str(err) == "bad value"


class TestClampWithWarningNoRange:
    """Tests for clamp_with_warning when no min/max is given."""

    def test_int_pass_through(self) -> None:
        assert clamp_with_warning("Cls", "f", 42) == 42

    def test_float_pass_through(self) -> None:
        result = clamp_with_warning("Cls", "f", 3.14)
        assert result == pytest.approx(3.14)

    def test_negative_pass_through_no_minimum(self) -> None:
        assert clamp_with_warning("Cls", "f", -5) == -5


class TestClampWithWarningMinimum:
    """Tests for clamp_with_warning with minimum bound."""

    def test_value_above_minimum(self) -> None:
        assert clamp_with_warning("Cls", "f", 10, minimum=5) == 10

    def test_value_at_minimum(self) -> None:
        assert clamp_with_warning("Cls", "f", 5, minimum=5) == 5

    def test_value_below_minimum_coerces(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cls", "f", 2, minimum=5)
        assert result == 5
        assert "below minimum" in caplog.text

    def test_negative_value_with_nonneg_minimum_raises(self) -> None:
        with pytest.raises(ConfigError, match="negative value"):
            clamp_with_warning("Cls", "f", -1, minimum=0)

    def test_negative_value_with_positive_minimum_raises(self) -> None:
        with pytest.raises(ConfigError, match="negative value"):
            clamp_with_warning("Cls", "f", -10, minimum=1)

    def test_negative_minimum_allows_negative_value(self, caplog: pytest.LogCaptureFixture) -> None:
        # minimum is negative, so negative values are allowed (no ConfigError)
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cls", "f", -5, minimum=-10)
        assert result == -5


class TestClampWithWarningMaximum:
    """Tests for clamp_with_warning with maximum bound."""

    def test_value_below_maximum(self) -> None:
        assert clamp_with_warning("Cls", "f", 5, maximum=10) == 5

    def test_value_at_maximum(self) -> None:
        assert clamp_with_warning("Cls", "f", 10, maximum=10) == 10

    def test_value_above_maximum_coerces(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cls", "f", 15, maximum=10)
        assert result == 10
        assert "exceeds maximum" in caplog.text


class TestClampWithWarningBothBounds:
    """Tests for clamp_with_warning with both min and max."""

    def test_value_in_range(self) -> None:
        assert clamp_with_warning("Cls", "f", 5, minimum=1, maximum=10) == 5

    def test_value_below_range(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cls", "f", 0.5, minimum=1.0, maximum=10.0)
        assert result == pytest.approx(1.0)
        assert "below minimum" in caplog.text

    def test_value_above_range(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cls", "f", 20.0, minimum=1.0, maximum=10.0)
        assert result == pytest.approx(10.0)
        assert "exceeds maximum" in caplog.text

    def test_negative_with_nonneg_range_raises(self) -> None:
        with pytest.raises(ConfigError, match="negative value"):
            clamp_with_warning("Cls", "f", -1, minimum=0, maximum=100)


class TestClampWithWarningFloats:
    """Float-specific edge cases."""

    def test_float_clamp_to_minimum(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cfg", "val", 0.01, minimum=0.1)
        assert result == pytest.approx(0.1)

    def test_float_clamp_to_maximum(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cfg", "val", 99.9, maximum=50.0)
        assert result == pytest.approx(50.0)

    def test_zero_value_with_zero_minimum(self) -> None:
        assert clamp_with_warning("Cfg", "val", 0.0, minimum=0.0) == pytest.approx(0.0)


class TestClampWarningMessages:
    """Verify log messages include qualified field names."""

    def test_warning_includes_class_and_field(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            clamp_with_warning("MyClass", "my_field", 0, minimum=1)
        assert "MyClass.my_field" in caplog.text

    def test_error_includes_class_and_field(self) -> None:
        with pytest.raises(ConfigError, match=r"MyClass\.my_field"):
            clamp_with_warning("MyClass", "my_field", -1, minimum=0)
