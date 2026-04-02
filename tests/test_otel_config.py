"""Tests for OtelConfig dataclass."""

from pokepoke.otel_config import OtelConfig


class TestOtelConfig:
    """Tests for the OtelConfig dataclass."""

    def test_defaults(self) -> None:
        config = OtelConfig()
        assert config.enabled is False
        assert config.service_name == "pokepoke"
        assert config.exporter == "console"
        assert config.endpoint == "http://localhost:4318"
        assert config.log_level == "INFO"
        assert config.batch_export is True

    def test_custom_values(self) -> None:
        config = OtelConfig(
            enabled=True,
            service_name="my-service",
            exporter="otlp",
            endpoint="http://otel-collector:4318",
            log_level="DEBUG",
            batch_export=False,
        )
        assert config.enabled is True
        assert config.service_name == "my-service"
        assert config.exporter == "otlp"
        assert config.endpoint == "http://otel-collector:4318"
        assert config.log_level == "DEBUG"
        assert config.batch_export is False

    def test_available_via_config_module(self) -> None:
        """OtelConfig should be importable from the main config module."""
        from pokepoke.config import OtelConfig as ConfigOtelConfig
        assert ConfigOtelConfig is OtelConfig
