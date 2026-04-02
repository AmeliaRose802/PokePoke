"""Tests for OpenTelemetry logging integration."""

import builtins
import logging
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import pokepoke.utils.otel_logging as otel_mod
from pokepoke.otel_config import OtelConfig
from pokepoke.utils.logging_filters import WorkItemFilter
from pokepoke.utils.logging_utils import configure_logging
from pokepoke.utils.otel_logging import (
    _LOG_LEVEL_MAP,
    _check_otel_available,
    setup_otel_logging,
    shutdown_otel_logging,
)


@pytest.fixture(autouse=True)
def _reset_otel_state() -> Iterator[None]:
    """Reset module-level OTEL state after each test."""
    yield
    otel_mod._provider = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _mock_otel() -> Iterator[dict[str, Any]]:
    """Context manager that patches all OTEL SDK classes used by setup_otel_logging."""
    with ExitStack() as stack:
        mocks: dict[str, Any] = {}
        mocks["resource_cls"] = stack.enter_context(
            patch("opentelemetry.sdk.resources.Resource")
        )
        mocks["provider_cls"] = stack.enter_context(
            patch("opentelemetry.sdk._logs.LoggerProvider")
        )
        mocks["handler_cls"] = stack.enter_context(
            patch("opentelemetry.sdk._logs.LoggingHandler")
        )
        mocks["batch_cls"] = stack.enter_context(
            patch("opentelemetry.sdk._logs.export.BatchLogRecordProcessor")
        )
        mocks["simple_cls"] = stack.enter_context(
            patch("opentelemetry.sdk._logs.export.SimpleLogRecordProcessor")
        )
        mocks["console_cls"] = stack.enter_context(
            patch("opentelemetry.sdk._logs.export.ConsoleLogExporter")
        )
        mocks["set_provider"] = stack.enter_context(
            patch("opentelemetry._logs.set_logger_provider")
        )
        yield mocks


# ---------------------------------------------------------------------------
# OtelConfig tests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# _check_otel_available tests
# ---------------------------------------------------------------------------

class TestCheckOtelAvailable:
    """Tests for _check_otel_available."""

    def test_returns_true_when_packages_installed(self) -> None:
        assert _check_otel_available() is True

    def test_returns_false_when_packages_missing(self) -> None:
        original_import = builtins.__import__
        # Temporarily remove cached OTEL modules so the import triggers __import__
        saved_modules: dict[str, Any] = {}
        otel_keys = [k for k in sys.modules if k.startswith("opentelemetry")]
        for key in otel_keys:
            saved_modules[key] = sys.modules.pop(key)

        def _blocking_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("opentelemetry"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=_blocking_import):
                assert _check_otel_available() is False
        finally:
            sys.modules.update(saved_modules)


# ---------------------------------------------------------------------------
# setup_otel_logging tests
# ---------------------------------------------------------------------------

class TestSetupOtelLogging:
    """Tests for setup_otel_logging."""

    def test_returns_none_when_disabled(self) -> None:
        config = OtelConfig(enabled=False)
        assert setup_otel_logging(config) is None

    @patch("pokepoke.utils.otel_logging._check_otel_available", return_value=False)
    def test_returns_none_when_packages_missing(self, _mock_check: MagicMock) -> None:
        config = OtelConfig(enabled=True)
        assert setup_otel_logging(config) is None

    def test_console_exporter_batch(self) -> None:
        config = OtelConfig(enabled=True, exporter="console", batch_export=True)
        with _mock_otel() as mocks:
            handler = setup_otel_logging(config)

        assert handler is not None
        mocks["batch_cls"].assert_called_once()
        mocks["simple_cls"].assert_not_called()
        mocks["set_provider"].assert_called_once()
        mocks["resource_cls"].create.assert_called()
        assert otel_mod._provider is not None

    def test_console_exporter_simple(self) -> None:
        config = OtelConfig(enabled=True, exporter="console", batch_export=False)
        with _mock_otel() as mocks:
            handler = setup_otel_logging(config)

        assert handler is not None
        mocks["simple_cls"].assert_called_once()
        mocks["batch_cls"].assert_not_called()

    def test_unknown_exporter_falls_back_to_console(self) -> None:
        config = OtelConfig(enabled=True, exporter="unknown_exporter")
        with _mock_otel() as mocks:
            handler = setup_otel_logging(config)

        assert handler is not None
        mocks["console_cls"].assert_called_once()

    def test_otlp_exporter_batch(self) -> None:
        config = OtelConfig(
            enabled=True, exporter="otlp",
            endpoint="http://localhost:4318", batch_export=True,
        )
        with (
            _mock_otel() as mocks,
            patch(
                "opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter"
            ) as mock_otlp,
        ):
            handler = setup_otel_logging(config)

        assert handler is not None
        mock_otlp.assert_called_once_with(endpoint="http://localhost:4318")
        mocks["batch_cls"].assert_called_once()

    def test_otlp_exporter_simple(self) -> None:
        config = OtelConfig(
            enabled=True, exporter="otlp",
            endpoint="http://localhost:4318", batch_export=False,
        )
        with (
            _mock_otel() as mocks,
            patch(
                "opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter"
            ),
        ):
            handler = setup_otel_logging(config)

        assert handler is not None
        mocks["simple_cls"].assert_called_once()

    def test_otlp_import_error_returns_none(self) -> None:
        config = OtelConfig(enabled=True, exporter="otlp")
        with (
            _mock_otel(),
            patch(
                "pokepoke.utils.otel_logging._create_otlp_processor",
                return_value=None,
            ),
        ):
            handler = setup_otel_logging(config)

        assert handler is None

    def test_log_level_debug(self) -> None:
        config = OtelConfig(enabled=True, log_level="DEBUG")
        with _mock_otel() as mocks:
            setup_otel_logging(config)

        mocks["handler_cls"].assert_called_once()
        _, kwargs = mocks["handler_cls"].call_args
        assert kwargs["level"] == logging.DEBUG

    def test_log_level_warning(self) -> None:
        config = OtelConfig(enabled=True, log_level="WARNING")
        with _mock_otel() as mocks:
            setup_otel_logging(config)

        _, kwargs = mocks["handler_cls"].call_args
        assert kwargs["level"] == logging.WARNING

    def test_log_level_unknown_defaults_to_info(self) -> None:
        config = OtelConfig(enabled=True, log_level="UNKNOWN_LEVEL")
        with _mock_otel() as mocks:
            setup_otel_logging(config)

        _, kwargs = mocks["handler_cls"].call_args
        assert kwargs["level"] == logging.INFO

    def test_resource_includes_service_name(self) -> None:
        config = OtelConfig(enabled=True, service_name="test-svc")
        with _mock_otel() as mocks:
            setup_otel_logging(config)

        mocks["resource_cls"].create.assert_called_once()
        call_args = mocks["resource_cls"].create.call_args[0][0]
        assert call_args["service.name"] == "test-svc"
        assert "service.version" in call_args


# ---------------------------------------------------------------------------
# _create_otlp_processor tests
# ---------------------------------------------------------------------------

class TestCreateOtlpProcessor:
    """Tests for _create_otlp_processor."""

    def test_import_error_returns_none(self) -> None:
        from pokepoke.utils.otel_logging import _create_otlp_processor

        config = OtelConfig(enabled=True, exporter="otlp")
        # Temporarily hide the OTLP exporter module
        saved_modules: dict[str, Any] = {}
        otlp_keys = [
            k for k in sys.modules
            if "otlp" in k and "log_exporter" in k
        ]
        for key in otlp_keys:
            saved_modules[key] = sys.modules.pop(key)

        original_import = builtins.__import__

        def _block_otlp(name: str, *args: object, **kwargs: object) -> object:
            if "otlp" in name and "log_exporter" in name:
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        try:
            with patch("builtins.__import__", side_effect=_block_otlp):
                result = _create_otlp_processor(config)
            assert result is None
        finally:
            sys.modules.update(saved_modules)

    def test_batch_processor_created(self) -> None:
        from pokepoke.utils.otel_logging import _create_otlp_processor

        config = OtelConfig(enabled=True, exporter="otlp", batch_export=True)
        mock_batch = MagicMock()
        with patch(
            "opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter"
        ), patch(
            "opentelemetry.sdk._logs.export.BatchLogRecordProcessor", mock_batch
        ):
            result = _create_otlp_processor(config)

        assert result is not None
        mock_batch.assert_called_once()

    def test_simple_processor_created(self) -> None:
        from pokepoke.utils.otel_logging import _create_otlp_processor

        config = OtelConfig(enabled=True, exporter="otlp", batch_export=False)
        mock_simple = MagicMock()
        with patch(
            "opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter"
        ), patch(
            "opentelemetry.sdk._logs.export.SimpleLogRecordProcessor", mock_simple
        ):
            result = _create_otlp_processor(config)

        assert result is not None
        mock_simple.assert_called_once()


# ---------------------------------------------------------------------------
# shutdown_otel_logging tests
# ---------------------------------------------------------------------------

class TestShutdownOtelLogging:
    """Tests for shutdown_otel_logging."""

    def test_no_op_when_no_provider(self) -> None:
        otel_mod._provider = None
        shutdown_otel_logging()
        assert otel_mod._provider is None

    def test_calls_shutdown_on_active_provider(self) -> None:
        mock_provider = MagicMock()
        otel_mod._provider = mock_provider
        shutdown_otel_logging()
        mock_provider.shutdown.assert_called_once()
        assert otel_mod._provider is None

    def test_clears_provider_even_on_error(self) -> None:
        mock_provider = MagicMock()
        mock_provider.shutdown.side_effect = RuntimeError("shutdown failed")
        otel_mod._provider = mock_provider
        shutdown_otel_logging()
        assert otel_mod._provider is None


# ---------------------------------------------------------------------------
# _LOG_LEVEL_MAP tests
# ---------------------------------------------------------------------------

class TestLogLevelMap:
    """Tests for the log level mapping."""

    def test_all_standard_levels_present(self) -> None:
        for level_name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            assert level_name in _LOG_LEVEL_MAP

    def test_values_match_logging_constants(self) -> None:
        assert _LOG_LEVEL_MAP["DEBUG"] == logging.DEBUG
        assert _LOG_LEVEL_MAP["INFO"] == logging.INFO
        assert _LOG_LEVEL_MAP["WARNING"] == logging.WARNING
        assert _LOG_LEVEL_MAP["ERROR"] == logging.ERROR
        assert _LOG_LEVEL_MAP["CRITICAL"] == logging.CRITICAL


# ---------------------------------------------------------------------------
# configure_logging OTEL integration tests
# ---------------------------------------------------------------------------

class TestConfigureLoggingOtelIntegration:
    """Tests for OTEL integration in configure_logging."""

    def test_otel_handler_added_to_root_logger(self, tmp_path: Any) -> None:
        log_file = tmp_path / "debug.log"
        config = OtelConfig(enabled=True)

        root = logging.getLogger()
        original_handlers = root.handlers[:]
        root.handlers.clear()

        pokepoke_logger = logging.getLogger("pokepoke")
        original_pp_handlers = pokepoke_logger.handlers[:]
        pokepoke_logger.handlers.clear()

        mock_handler = MagicMock(spec=logging.Handler)
        mock_handler.filters = []

        try:
            with patch(
                "pokepoke.utils.otel_logging.setup_otel_logging",
                return_value=mock_handler,
            ):
                configure_logging(log_file, otel_config=config)

            assert mock_handler in root.handlers
            mock_handler.addFilter.assert_called_once()
            filter_arg = mock_handler.addFilter.call_args[0][0]
            assert isinstance(filter_arg, WorkItemFilter)
        finally:
            root.handlers = original_handlers
            pokepoke_logger.handlers = original_pp_handlers

    def test_no_handler_added_when_setup_returns_none(self, tmp_path: Any) -> None:
        log_file = tmp_path / "debug.log"
        config = OtelConfig(enabled=True)

        root = logging.getLogger()
        original_handlers = root.handlers[:]
        root.handlers.clear()

        pokepoke_logger = logging.getLogger("pokepoke")
        original_pp_handlers = pokepoke_logger.handlers[:]
        pokepoke_logger.handlers.clear()

        try:
            with patch(
                "pokepoke.utils.otel_logging.setup_otel_logging",
                return_value=None,
            ):
                configure_logging(log_file, otel_config=config)

            # Only file handler(s) and no OTEL handler
            otel_handlers = [
                h for h in root.handlers if isinstance(h, MagicMock)
            ]
            assert len(otel_handlers) == 0
        finally:
            root.handlers = original_handlers
            pokepoke_logger.handlers = original_pp_handlers

    def test_no_otel_when_config_is_none(self, tmp_path: Any) -> None:
        log_file = tmp_path / "debug.log"

        root = logging.getLogger()
        original_handlers = root.handlers[:]
        root.handlers.clear()

        pokepoke_logger = logging.getLogger("pokepoke")
        original_pp_handlers = pokepoke_logger.handlers[:]
        pokepoke_logger.handlers.clear()

        try:
            with patch(
                "pokepoke.utils.otel_logging.setup_otel_logging"
            ) as mock_setup:
                configure_logging(log_file, otel_config=None)

            mock_setup.assert_not_called()
        finally:
            root.handlers = original_handlers
            pokepoke_logger.handlers = original_pp_handlers


# ---------------------------------------------------------------------------
# Entry-point wiring tests
# ---------------------------------------------------------------------------

class TestEntryPointOtelWiring:
    """Verify that entry points pass otel_config to configure_logging."""

    def test_orchestrator_passes_otel_config(self) -> None:
        """_setup_orchestrator must forward cfg.otel to configure_logging."""
        from pokepoke.otel_config import OtelConfig

        with patch(
            "pokepoke.orchestration.orchestrator.configure_logging"
        ) as mock_cl, patch(
            "pokepoke.orchestration.orchestrator.load_config"
        ) as mock_cfg, patch(
            "pokepoke.orchestration.orchestrator.register_shutdown_handlers"
        ), patch(
            "pokepoke.orchestration.orchestrator.terminal_ui"
        ), patch(
            "pokepoke.orchestration.orchestrator.set_terminal_banner"
        ), patch(
            "pokepoke.orchestration.orchestrator.initialize_agent_name",
            return_value="test-agent",
        ), patch(
            "pokepoke.orchestration.orchestrator.get_beads_stats",
        ), patch(
            "pokepoke.orchestration.orchestrator.get_failed_unassign_count",
            return_value=0,
        ), patch(
            "pokepoke.orchestration.orchestrator.backfill_from_beads_db",
            return_value={"backfilled": 0},
        ), patch(
            "pokepoke.orchestration.orchestrator._get_beads_summary",
            return_value={"total_created": 0, "total_completed": 0},
        ):
            otel = OtelConfig(enabled=True, service_name="test-svc")
            mock_cfg.return_value = MagicMock(
                max_parallel_agents=1,
                preflight_health=MagicMock(enabled=False),
                otel=otel,
            )
            from pokepoke.orchestration.orchestrator import _setup_orchestrator

            _setup_orchestrator(
                interactive=False, continuous=False,
                run_beta_first=False, agent_name_override=None,
                max_parallel_agents=1,
            )

        mock_cl.assert_called_once()
        _, kwargs = mock_cl.call_args
        assert kwargs.get("otel_config") is otel

    def test_desktop_api_passes_otel_config(self) -> None:
        """DesktopAPI.__init__ must forward cfg.otel to configure_logging."""
        from pokepoke.otel_config import OtelConfig

        otel = OtelConfig(enabled=False)
        mock_cfg_obj = MagicMock(otel=otel)

        with patch(
            "pokepoke.desktop.desktop_api.configure_logging"
        ) as mock_cl, patch(
            "pokepoke.config.load_config", return_value=mock_cfg_obj,
        ), patch(
            "pokepoke.desktop.desktop_api.get_repository_name",
            return_value="test-repo",
        ):
            from pokepoke.desktop.desktop_api import DesktopAPI

            DesktopAPI()

        mock_cl.assert_called_once()
        _, kwargs = mock_cl.call_args
        assert kwargs.get("otel_config") is otel
