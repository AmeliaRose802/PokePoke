"""Config validation helpers: coercion warnings and error detection."""

import logging
from typing import overload

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised for clearly invalid configuration values (e.g. negative numbers)."""


@overload
def clamp_with_warning(
    class_name: str, field_name: str, value: int,
    minimum: int | None = ..., maximum: int | None = ...,
) -> int: ...


@overload
def clamp_with_warning(
    class_name: str, field_name: str, value: float,
    minimum: float | None = ..., maximum: float | None = ...,
) -> float: ...


def clamp_with_warning(
    class_name: str,
    field_name: str,
    value: int | float,
    minimum: int | float | None = None,
    maximum: int | float | None = None,
) -> int | float:
    """Validate and clamp a config value to a valid range.

    Raises :class:`ConfigError` for clearly invalid values (negative numbers
    when the valid range is non-negative).  Logs a warning when coercing
    out-of-range values to the nearest bound.
    """
    qualified = f"{class_name}.{field_name}"

    if value < 0 and minimum is not None and minimum >= 0:
        raise ConfigError(
            f"{qualified}: negative value {value!r} is not valid "
            f"(minimum is {minimum!r})"
        )

    if minimum is not None and value < minimum:
        logger.warning(
            "%s: value %r is below minimum %r — coercing to %r",
            qualified, value, minimum, minimum,
        )
        return minimum

    if maximum is not None and value > maximum:
        logger.warning(
            "%s: value %r exceeds maximum %r — coercing to %r",
            qualified, value, maximum, maximum,
        )
        return maximum

    return value
