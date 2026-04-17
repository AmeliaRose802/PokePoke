"""Tests for pokepoke.config_validation module.

Covers clamp_with_warning() and ConfigError for all branches:
negative-value rejection, below-minimum coercion, above-maximum coercion,
values within range, and edge cases (None bounds, boundary equality).
"""

import logging

import pytest

from pokepoke.config_validation import ConfigError, clamp_with_warning


class TestClampWithWarningInRange:
    """Values already within [minimum, maximum] are returned unchanged."""

    def test_value_within_range(self):
        assert clamp_with_warning("Cfg", "field", 5, minimum=1, maximum=10) == 5

    def test_value_equals_minimum(self):
        assert clamp_with_warning("Cfg", "field", 1, minimum=1, maximum=10) == 1

    def test_value_equals_maximum(self):
        assert clamp_with_warning("Cfg", "field", 10, minimum=1, maximum=10) == 10

    def test_float_within_range(self):
        result = clamp_with_warning("Cfg", "field", 3.5, minimum=1.0, maximum=5.0)
        assert result == 3.5

    def test_no_bounds_returns_value_unchanged(self):
        assert clamp_with_warning("Cfg", "field", 42) == 42

    def test_only_minimum_value_above(self):
        assert clamp_with_warning("Cfg", "field", 10, minimum=5) == 10

    def test_only_maximum_value_below(self):
        assert clamp_with_warning("Cfg", "field", 3, maximum=10) == 3


class TestClampWithWarningCoercion:
    """Out-of-range values are coerced to the nearest bound with a warning."""

    def test_below_minimum_coerced(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cfg", "field", 0.5, minimum=1.0)
        assert result == 1.0
        assert "below minimum" in caplog.text

    def test_above_maximum_coerced(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cfg", "field", 200, maximum=100)
        assert result == 100
        assert "exceeds maximum" in caplog.text

    def test_float_below_minimum_coerced(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cfg", "val", 0.01, minimum=0.1, maximum=1.0)
        assert result == 0.1

    def test_float_above_maximum_coerced(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cfg", "val", 99.9, minimum=0.0, maximum=1.0)
        assert result == 1.0


class TestClampWithWarningNegativeRejection:
    """Negative values when minimum >= 0 raise ConfigError."""

    def test_negative_int_raises(self):
        with pytest.raises(ConfigError, match="negative value"):
            clamp_with_warning("Cfg", "count", -1, minimum=0)

    def test_negative_float_raises(self):
        with pytest.raises(ConfigError, match="negative value"):
            clamp_with_warning("Cfg", "timeout", -0.5, minimum=0.0)

    def test_negative_with_positive_minimum_raises(self):
        with pytest.raises(ConfigError, match="negative value"):
            clamp_with_warning("Cfg", "retry", -3, minimum=1, maximum=10)


class TestClampWithWarningNegativeAllowed:
    """Negative values are allowed when minimum is None or negative."""

    def test_negative_with_no_minimum(self):
        assert clamp_with_warning("Cfg", "offset", -5) == -5

    def test_negative_with_negative_minimum(self):
        assert clamp_with_warning("Cfg", "temp", -10, minimum=-20) == -10

    def test_negative_below_negative_minimum_coerced(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = clamp_with_warning("Cfg", "temp", -30, minimum=-20)
        assert result == -20


class TestConfigError:
    """ConfigError is a plain Exception subclass."""

    def test_is_exception(self):
        assert issubclass(ConfigError, Exception)

    def test_message_preserved(self):
        err = ConfigError("bad config value")
        assert str(err) == "bad config value"
