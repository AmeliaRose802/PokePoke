"""OpenTelemetry configuration for PokePoke."""

from dataclasses import dataclass


@dataclass
class OtelConfig:
    """OpenTelemetry logging configuration.

    Disabled by default.  When *enabled* is ``True``, a
    :class:`logging.Handler` backed by the OTEL Logs SDK is attached to the
    root logger so that every Python log record is also exported to the
    configured OTEL backend.
    """

    enabled: bool = False
    service_name: str = "pokepoke"
    exporter: str = "console"  # "console" or "otlp"
    endpoint: str = "http://localhost:4318"
    log_level: str = "INFO"
    batch_export: bool = True
