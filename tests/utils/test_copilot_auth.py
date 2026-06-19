"""Tests for the Copilot CLI authentication pre-flight check."""
from unittest.mock import AsyncMock, MagicMock, patch

from pokepoke.utils import copilot_auth
from pokepoke.utils.copilot_auth import (
    COPILOT_AUTH_HELP,
    CopilotAuthStatus,
    check_copilot_auth,
)


def test_help_text_is_actionable():
    """Guidance must mention the copilot login flow."""
    assert "copilot" in COPILOT_AUTH_HELP.lower()
    assert "login" in COPILOT_AUTH_HELP.lower()


def test_check_returns_authenticated_when_cli_reports_user():
    """A successful probe with an authenticated user yields checked+authenticated."""
    async def fake_query():
        return CopilotAuthStatus(checked=True, authenticated=True, message="ok")

    with patch.object(copilot_auth, "_query_auth_status_async", side_effect=fake_query):
        result = check_copilot_auth()

    assert result.checked is True
    assert result.authenticated is True


def test_check_returns_unauthenticated_when_cli_reports_no_user():
    """A successful probe with no user yields checked but not authenticated."""
    async def fake_query():
        return CopilotAuthStatus(
            checked=True, authenticated=False, message="Not authenticated"
        )

    with patch.object(copilot_auth, "_query_auth_status_async", side_effect=fake_query):
        result = check_copilot_auth()

    assert result.checked is True
    assert result.authenticated is False
    assert result.message == "Not authenticated"


def test_check_is_inconclusive_on_probe_error():
    """Any exception in the probe is swallowed and reported as inconclusive."""
    async def boom():
        raise RuntimeError("cli launch failed")

    with patch.object(copilot_auth, "_query_auth_status_async", side_effect=boom):
        result = check_copilot_auth()

    assert result.checked is False
    assert result.authenticated is False
    assert "cli launch failed" in (result.message or "")


def test_check_is_inconclusive_on_timeout():
    """A probe that exceeds the timeout is reported as inconclusive, not a hang."""
    async def slow():
        import asyncio

        await asyncio.sleep(10)
        return CopilotAuthStatus(checked=True, authenticated=True)

    with patch.object(copilot_auth, "_query_auth_status_async", side_effect=slow):
        result = check_copilot_auth(timeout=0.01)

    assert result.checked is False
    assert result.authenticated is False


def test_query_reports_missing_sdk():
    """When the SDK is unavailable the probe is inconclusive."""
    import asyncio

    with patch("pokepoke.models.copilot_sdk._HAS_COPILOT", False):
        result = asyncio.run(copilot_auth._query_auth_status_async())

    assert result.checked is False
    assert result.authenticated is False


def test_query_uses_client_auth_status():
    """The probe starts a client, reads auth status, and shuts it down."""
    import asyncio

    fake_status = MagicMock(isAuthenticated=True, statusMessage="signed in")
    fake_client = MagicMock()
    fake_client.start = AsyncMock()
    fake_client.get_auth_status = AsyncMock(return_value=fake_status)

    with (
        patch("pokepoke.models.copilot_sdk._HAS_COPILOT", True),
        patch("pokepoke.models.copilot_sdk._create_sdk_client", return_value=fake_client),
        patch(
            "pokepoke.utils.process_utils.shutdown_copilot_client",
            new=AsyncMock(),
        ) as mock_shutdown,
    ):
        result = asyncio.run(copilot_auth._query_auth_status_async())

    assert result.checked is True
    assert result.authenticated is True
    assert result.message == "signed in"
    fake_client.start.assert_awaited_once()
    mock_shutdown.assert_awaited_once()
