"""Shared fixtures for orchestration tests."""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_is_beads_item_closed():
    """Prevent bd subprocess calls from is_beads_item_closed in all orchestration tests.

    The function runs ``bd show <id> --json`` which hangs in CI/test
    environments where the beads daemon isn't running.
    """
    with patch(
        "pokepoke.beads.reconciliation.is_beads_item_closed",
        return_value=False,
    ):
        yield
