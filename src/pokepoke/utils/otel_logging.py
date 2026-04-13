"""OpenTelemetry logging integration for PokePoke.

Bridges Python's standard :mod:`logging` to the OpenTelemetry Logs SDK,
enabling structured log export to OTLP-compatible backends (Jaeger, Grafana,
Azure Monitor, etc.).  When the OTEL SDK packages are not installed the module
degrades gracefully — :func:`setup_otel_logging` returns ``None`` and all other
functions become safe no-ops.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pokepoke.otel_config import OtelConfig

logger = logging.getLogger(__name__)

__all__ = [
    "get_current_otel_handler",
    "setup_otel_logging",
    "shutdown_otel_logging",
]

# Module-level state for shutdown coordination and handler deduplication.
_provider: Any = None  # LoggerProvider | None at runtime
_handler: logging.Handler | None = None

_LOG_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _check_otel_available() -> bool:
    """Return True if the core OpenTelemetry SDK packages are importable."""
    try:
        import opentelemetry.sdk._logs
        import opentelemetry.sdk.resources

        # Reference the modules so the imports are not flagged as unused.
        _ = opentelemetry.sdk._logs
        _ = opentelemetry.sdk.resources
    except ImportError:
        return False
    return True


def setup_otel_logging(config: OtelConfig) -> logging.Handler | None:
    """Configure OpenTelemetry log export and return a handler for Python logging.

    Returns ``None`` when OTEL is disabled in *config*, the required SDK
    packages are not installed, or the requested exporter is unavailable.

    Safe to call repeatedly — any previously created provider is shut down
    first to prevent resource leaks, and the tracked handler reference is
    updated so callers can remove stale handlers from loggers.
    """
    global _provider, _handler

    if not config.enabled:
        return None

    if not _check_otel_available():
        logger.warning(
            "OpenTelemetry packages not installed — OTEL logging disabled. "
            "Install with: pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http"
        )
        return None

    # Shut down previous provider to avoid resource leaks on repeated calls.
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:
            logger.debug("Error shutting down previous OTEL provider", exc_info=True)
        _provider = None
        _handler = None

    from opentelemetry._logs import set_logger_provider
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import (
        BatchLogRecordProcessor,
        ConsoleLogExporter,
        SimpleLogRecordProcessor,
    )
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.version": "0.1.0",
        }
    )

    provider = LoggerProvider(resource=resource)

    if config.exporter == "otlp":
        processor = _create_otlp_processor(config)
        if processor is None:
            return None
    else:
        # Default to console exporter for any non-OTLP value
        exporter = ConsoleLogExporter()
        if config.batch_export:
            processor = BatchLogRecordProcessor(exporter)
        else:
            processor = SimpleLogRecordProcessor(exporter)

    provider.add_log_record_processor(processor)
    set_logger_provider(provider)
    _provider = provider

    handler_level = _LOG_LEVEL_MAP.get(config.log_level.upper(), logging.INFO)
    handler = LoggingHandler(level=handler_level, logger_provider=provider)
    _handler = handler
    return handler


def get_current_otel_handler() -> logging.Handler | None:
    """Return the handler created by the most recent :func:`setup_otel_logging` call.

    Used by :func:`~pokepoke.utils.logging_utils.configure_logging` to remove
    stale handlers from loggers before attaching a fresh one.
    """
    return _handler


def _create_otlp_processor(config: OtelConfig) -> Any | None:
    """Create a log record processor backed by the OTLP HTTP exporter.

    Returns ``None`` if the OTLP exporter package is not installed.
    """
    try:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )
        from opentelemetry.sdk._logs.export import (
            BatchLogRecordProcessor,
            SimpleLogRecordProcessor,
        )
    except ImportError:
        logger.warning(
            "OTLP log exporter not installed — OTEL logging disabled. "
            "Install with: pip install opentelemetry-exporter-otlp-proto-http"
        )
        return None

    exporter = OTLPLogExporter(endpoint=config.endpoint)
    if config.batch_export:
        return BatchLogRecordProcessor(exporter)
    return SimpleLogRecordProcessor(exporter)


def shutdown_otel_logging() -> None:
    """Flush pending log exports and shut down the OTEL logger provider.

    Safe to call even when OTEL was never initialized — the function is a
    no-op when no provider is active.
    """
    global _provider, _handler
    if _provider is not None:
        try:
            _provider.shutdown()
        except Exception:
            logger.debug("Error during OTEL provider shutdown", exc_info=True)
        finally:
            _provider = None
            _handler = None
