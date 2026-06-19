"""Copilot CLI authentication pre-flight check.

The orchestrator spawns GitHub Copilot CLI work agents via the SDK.  When the
CLI has no authenticated user, every spawned session fails with a cryptic
"Session was not created with authentication info or custom provider" error and
the run completes with zero items.  This module provides a fast, one-time
pre-flight check so PokePoke can fail with a clear, actionable message instead.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.orchestration.orchestrator import _OrchestratorContext

logger = logging.getLogger(__name__)

# Actionable guidance shown when the Copilot CLI is not authenticated.
COPILOT_AUTH_HELP = (
    "GitHub Copilot CLI is not authenticated. PokePoke cannot run work agents "
    "without an authenticated Copilot CLI.\n"
    "  To fix: run `copilot` in a terminal and complete the `/login` flow, "
    "then re-run PokePoke.\n"
    "  (Verify with `copilot` -> `/user` once logged in.)"
)


@dataclass
class CopilotAuthStatus:
    """Result of a Copilot CLI authentication probe."""

    checked: bool  # True if the probe completed without an internal error.
    authenticated: bool  # True only when the CLI reports an authenticated user.
    message: str | None = None  # Status/diagnostic message, if any.


async def _query_auth_status_async() -> CopilotAuthStatus:
    """Start a Copilot client, query auth status, then shut it down."""
    # Importing copilot_sdk applies the SDK's PingResponse ISO-timestamp patch.
    from pokepoke.models.copilot_sdk import _HAS_COPILOT, _create_sdk_client
    from pokepoke.utils.process_utils import shutdown_copilot_client

    if not _HAS_COPILOT:
        return CopilotAuthStatus(
            checked=False, authenticated=False, message="copilot SDK not installed"
        )

    client = _create_sdk_client(None)
    try:
        await client.start()
        status = await client.get_auth_status()
        return CopilotAuthStatus(
            checked=True,
            authenticated=bool(getattr(status, "isAuthenticated", False)),
            message=getattr(status, "statusMessage", None),
        )
    finally:
        await shutdown_copilot_client(client)


def check_copilot_auth(timeout: float = 30.0) -> CopilotAuthStatus:
    """Probe the Copilot CLI auth status synchronously.

    Returns a :class:`CopilotAuthStatus`.  ``checked`` is ``False`` when the
    probe itself could not run (SDK missing, CLI launch failure, timeout); in
    that case callers should treat the result as inconclusive and continue
    rather than blocking the run on a flaky check.
    """
    try:
        return asyncio.run(
            asyncio.wait_for(_query_auth_status_async(), timeout=timeout)
        )
    except Exception as e:
        logger.debug("Copilot auth check failed to run: %s", e, exc_info=True)
        return CopilotAuthStatus(checked=False, authenticated=False, message=str(e))


def run_copilot_auth_preflight(ctx: _OrchestratorContext) -> int | None:
    """Verify the Copilot CLI is authenticated before spawning work agents.

    Returns exit code 1 to stop when the CLI is confirmed unauthenticated, else
    None to continue.  An inconclusive probe (SDK/CLI error) only warns.
    """
    from pokepoke.desktop import terminal_ui

    if getattr(ctx.cfg.ai_backend, "provider", "copilot") != "copilot":
        return None
    logger.info("\n🔐 Verifying Copilot CLI authentication...")
    status = check_copilot_auth()
    if status.checked and not status.authenticated:
        terminal_ui.ui.stop_and_capture()
        logger.error(f"\n❌ {COPILOT_AUTH_HELP}")
        ctx.run_logger.log_orchestrator(
            f"Copilot CLI not authenticated ({status.message}) - shutting down",
            level="ERROR")
        ctx.finalize()
        return 1
    if not status.checked:
        logger.warning(
            f"⚠️  Could not verify Copilot auth status (continuing): {status.message}")
        ctx.run_logger.log_orchestrator(
            f"Copilot auth check inconclusive: {status.message}", level="WARNING")
    else:
        logger.info("✅ Copilot CLI authenticated")
    return None
