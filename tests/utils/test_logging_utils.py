"""Tests for pokepoke.utils.logging_utils — coverage discovery bridge.

The comprehensive logging_utils test suite lives in ``test_logging.py``
(historical naming).  The pre-commit coverage checker maps source modules
by stem name (``logging_utils`` → ``test_logging_utils``), so this file
re-exports the canonical tests to make them discoverable.
"""

from tests.utils.test_logging import *  # noqa: F403
