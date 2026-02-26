"""Tests for logging utilities."""

import logging
from pathlib import Path
import sys
import tempfile
from pokepoke.logging_utils import RunLogger, ItemLogger, configure_logging


def test_configure_logging_creates_debug_log(tmp_path):
    """configure_logging should create the debug log file and set up handlers."""
    log_file = tmp_path / "debug.log"

    # Use a fresh root logger state by removing existing handlers
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()

    pokepoke_logger = logging.getLogger("pokepoke")
    original_pp_handlers = pokepoke_logger.handlers[:]
    pokepoke_logger.handlers.clear()

    try:
        configure_logging(log_file)

        # Root logger should have a file handler at DEBUG
        assert root.level == logging.DEBUG
        assert any(
            isinstance(h, logging.FileHandler) for h in root.handlers
        ), "Root logger should have a FileHandler"

        # 'pokepoke' logger should have a console StreamHandler
        console_handlers = [
            h for h in pokepoke_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1, "pokepoke logger should have one console handler"
        assert console_handlers[0].level == logging.WARNING

        # Writing a debug message should appear in the file
        test_logger = logging.getLogger("pokepoke.test_module")
        test_logger.debug("test debug message")

        with open(log_file, encoding="utf-8") as f:
            content = f.read()
        assert "test debug message" in content
    finally:
        # Restore original handler state
        root.handlers = original_handlers
        pokepoke_logger.handlers = original_pp_handlers


def test_configure_logging_no_duplicate_console_handlers(tmp_path):
    """Calling configure_logging twice should not add duplicate console handlers."""
    log_file = tmp_path / "debug.log"

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()

    pokepoke_logger = logging.getLogger("pokepoke")
    original_pp_handlers = pokepoke_logger.handlers[:]
    pokepoke_logger.handlers.clear()

    try:
        configure_logging(log_file)
        configure_logging(log_file)

        console_handlers = [
            h for h in pokepoke_logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        assert len(console_handlers) == 1, "Should not add duplicate console handlers"
    finally:
        root.handlers = original_handlers
        pokepoke_logger.handlers = original_pp_handlers


def test_configure_logging_creates_parent_dirs(tmp_path):
    """configure_logging should create parent directories for the log file."""
    log_file = tmp_path / "nested" / "dirs" / "debug.log"

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()

    pokepoke_logger = logging.getLogger("pokepoke")
    original_pp_handlers = pokepoke_logger.handlers[:]
    pokepoke_logger.handlers.clear()

    try:
        configure_logging(log_file)
        assert log_file.parent.exists()
    finally:
        root.handlers = original_handlers
        pokepoke_logger.handlers = original_pp_handlers


def test_run_logger_initialization():
    """Test that RunLogger creates proper directory structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        # Check that run directory was created
        assert logger.get_run_dir().exists()

        # Check that orchestrator log was created
        assert (logger.get_run_dir() / "orchestrator.log").exists()

        # Check that items directory was created
        assert (logger.get_run_dir() / "items").exists()

        # Check run ID format (should be YYYYMMDD_HHMMSS_<uuid>)
        run_id = logger.get_run_id()
        parts = run_id.split('_')
        assert len(parts) == 3
        assert len(parts[0]) == 8  # YYYYMMDD
        assert len(parts[1]) == 6  # HHMMSS
        assert len(parts[2]) == 8  # short UUID


def test_run_logger_orchestrator_logging():
    """Test that orchestrator logging works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        # Log some messages
        logger.log_orchestrator("Test message 1")
        logger.log_orchestrator("Test warning", level="WARNING")
        logger.log_orchestrator("Test error", level="ERROR")

        # Read the log file
        with open(logger.orchestrator_log_path, encoding='utf-8') as f:
            content = f.read()

        # Check that messages are present
        assert "Test message 1" in content
        assert "Test warning" in content
        assert "Test error" in content
        assert "[INFO]" in content
        assert "[WARNING]" in content
        assert "[ERROR]" in content


def test_run_logger_item_logging():
    """Test that item logging works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        # Start item log
        item_logger = logger.start_item_log(
            "test-item-123",
            "Test Item Title",
            agent_name="pokepoke_unit_agent",
        )

        # Log some content
        item_logger.log("Test agent output\n")

        # End item log directly (no longer calling run_logger.end_item_log)
        item_logger.log_summary(success=True, request_count=5)

        # Check that item log file exists
        item_log_path = logger.item_logs_dir / "test-item-123_pokepoke_unit_agent.log"
        assert item_log_path.exists()

        # Read the log file
        with open(item_log_path, encoding='utf-8') as f:
            content = f.read()

        # Check that content is present
        assert "test-item-123" in content
        assert "Test Item Title" in content
        assert "Agent: pokepoke_unit_agent" in content
        assert "Test agent output" in content
        assert "SUCCESS" in content
        assert "Agent requests: 5" in content


def test_run_logger_finalize():
    """Test that finalize writes summary correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        # Finalize the run
        logger.finalize(items_completed=3, total_requests=15, elapsed=120.5)

        # Read the log file
        with open(logger.orchestrator_log_path, encoding='utf-8') as f:
            content = f.read()

        # Check that summary is present
        assert "Run Summary" in content
        assert "Items completed: 3" in content
        assert "Total agent requests: 15" in content
        assert "Total time: 2.0 minutes" in content


def test_run_logger_maintenance_logging():
    """Test that maintenance logging works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        # Log maintenance actions
        logger.log_maintenance("tech_debt", "Starting Tech Debt Agent")
        logger.log_maintenance("janitor", "Janitor Agent completed successfully")

        # Read the log file
        with open(logger.orchestrator_log_path, encoding='utf-8') as f:
            content = f.read()

        # Check that maintenance logs are present
        assert "[MAINTENANCE:tech_debt]" in content
        assert "Starting Tech Debt Agent" in content
        assert "[MAINTENANCE:janitor]" in content
        assert "Janitor Agent completed successfully" in content


def test_run_logger_creates_maintenance_dir():
    """Test that RunLogger creates a maintenance logs directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)
        assert (logger.get_run_dir() / "maintenance").exists()


def test_start_maintenance_log_creates_log_file():
    """Test that start_maintenance_log creates a log file under maintenance/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        maint_logger = logger.start_maintenance_log("Janitor")

        # Log file should exist under maintenance/
        expected_path = logger.maintenance_logs_dir / "janitor.log"
        assert expected_path.exists()
        assert maint_logger.log_path == expected_path

        # Header should contain agent name
        with open(expected_path, encoding='utf-8') as f:
            content = f.read()
        assert "Janitor Maintenance Agent" in content


def test_maintenance_log_captures_output():
    """Test that maintenance log captures copilot output and tool calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        maint_logger = logger.start_maintenance_log("Tech Debt")
        maint_logger.log_copilot_output("Analyzing codebase...\n")
        maint_logger.log_tool_call("grep", "pattern=TODO", result="Found 3", success=True)
        maint_logger.log_error("Rate limit hit")
        maint_logger.log_summary(success=True, request_count=2)

        with open(maint_logger.log_path, encoding='utf-8') as f:
            content = f.read()

        assert "Analyzing codebase..." in content
        assert "grep" in content
        assert "Found 3" in content
        assert "Rate limit hit" in content
        assert "SUCCESS" in content
        assert "Agent requests: 2" in content


def test_item_logger_sanitizes_filenames():
    """Test that ItemLogger sanitizes item IDs for filenames."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir)

        # Create item logger with ID containing path separators
        item_logger = ItemLogger(logs_dir, "task/with/slashes", "Test Item")

        # Check that log file was created with sanitized name
        expected_path = logs_dir / "task_with_slashes.log"
        assert item_logger.log_path == expected_path

        # Verify file exists
        assert expected_path.exists()


def test_item_logger_sanitizes_agent_name_in_filename():
    """Agent names should be appended to filenames after sanitization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir)
        agent_name = "Pokepoke Mighty/Onix D27A"
        item_logger = ItemLogger(
            logs_dir,
            "task-42",
            "Agent Test",
            agent_name=agent_name,
        )

        expected_path = logs_dir / "task-42_pokepoke_mighty_onix_d27a.log"
        assert item_logger.log_path == expected_path
        assert expected_path.exists()

        with open(expected_path, encoding='utf-8') as f:
            content = f.read()

        assert f"Agent: {agent_name}" in content


def test_multiple_item_logs():
    """Test that multiple items can be logged in sequence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        # Process first item
        item_logger1 = logger.start_item_log("item-1", "First Item", agent_name="Agent One")
        item_logger1.log("First item output\n")
        item_logger1.log_summary(success=True, request_count=3)

        # Process second item
        item_logger2 = logger.start_item_log(
            "item-2",
            "Second Item",
            agent_name="Agent Two",
        )
        item_logger2.log("Second item output\n")
        item_logger2.log_summary(success=False, request_count=5)

        # Check that both item logs exist
        assert (logger.item_logs_dir / "item-1_agent_one.log").exists()
        assert (logger.item_logs_dir / "item-2_agent_two.log").exists()

        # Read first item log
        with open(logger.item_logs_dir / "item-1_agent_one.log", encoding='utf-8') as f:
            content1 = f.read()
        assert "First item output" in content1
        assert "SUCCESS" in content1

        # Read second item log
        with open(logger.item_logs_dir / "item-2_agent_two.log", encoding='utf-8') as f:
            content2 = f.read()
        assert "Second item output" in content2
        assert "FAILURE" in content2


def test_item_logger_log_copilot_output():
    """Test that log_copilot_output writes streamed text to log."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir)
        item_logger = ItemLogger(logs_dir, "test-stream", "Stream Test")

        item_logger.log_copilot_output("Hello ")
        item_logger.log_copilot_output("world!")

        with open(item_logger.log_path, encoding='utf-8') as f:
            content = f.read()

        assert "Hello world!" in content


def test_item_logger_log_tool_call():
    """Test that log_tool_call writes tool invocation details."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir)
        item_logger = ItemLogger(logs_dir, "test-tool", "Tool Test")

        item_logger.log_tool_call("read_file", "path=src/main.py")
        item_logger.log_tool_call(
            "write_file", "path=out.py",
            result="File written", success=True
        )
        item_logger.log_tool_call(
            "compile", "target=all",
            result="Compilation error", success=False
        )

        with open(item_logger.log_path, encoding='utf-8') as f:
            content = f.read()

        assert "[TOOL]" in content
        assert "read_file" in content
        assert "write_file" in content
        assert "File written" in content
        assert "[RESULT]" in content
        assert "✅" in content
        assert "❌" in content


def test_item_logger_log_error():
    """Test that log_error writes error messages."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir)
        item_logger = ItemLogger(logs_dir, "test-error", "Error Test")

        item_logger.log_error("Something went wrong")

        with open(item_logger.log_path, encoding='utf-8') as f:
            content = f.read()

        assert "[ERROR]" in content
        assert "Something went wrong" in content


def test_get_item_dir_creates_subdirectory():
    """Test that _get_item_dir creates a per-item subdirectory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        item_dir = logger._get_item_dir("my-item-42")
        assert item_dir.exists()
        assert item_dir.parent == logger.item_logs_dir
        assert item_dir.name == "my-item-42"


def test_get_item_dir_sanitizes_slashes():
    """Test that _get_item_dir replaces slashes in item IDs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        item_dir = logger._get_item_dir("task/with/slashes")
        assert item_dir.name == "task_with_slashes"
        assert item_dir.exists()


def test_start_item_phase_log_creates_log_in_item_dir():
    """Test that start_item_phase_log creates a log file inside a per-item directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        item_logger = logger.start_item_phase_log(
            item_id="item-99",
            item_title="Phase Test",
            phase="work",
            attempt=1,
            agent_name="test_agent",
        )

        # Log file should be inside items/item-99/
        assert item_logger.log_path.parent == logger.item_logs_dir / "item-99"
        assert item_logger.log_path.exists()
        assert "work" in item_logger.log_path.name
        assert "attempt_1" in item_logger.log_path.name
        assert "test_agent" in item_logger.log_path.name


def test_start_item_phase_log_multiple_phases():
    """Test that different phases get separate log files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        work_logger = logger.start_item_phase_log(
            "item-1", "Test", phase="work", attempt=1, agent_name="agent"
        )
        gate_logger = logger.start_item_phase_log(
            "item-1", "Test", phase="gate", attempt=1, agent_name="agent"
        )

        assert work_logger.log_path != gate_logger.log_path
        assert work_logger.log_path.parent == gate_logger.log_path.parent


def test_start_item_phase_log_retry_attempt():
    """Test that retries get separate log files with attempt number."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        attempt1 = logger.start_item_phase_log(
            "item-1", "Test", phase="work", attempt=1, agent_name="agent"
        )
        attempt2 = logger.start_item_phase_log(
            "item-1", "Test", phase="work", attempt=2, agent_name="agent"
        )

        assert attempt1.log_path != attempt2.log_path
        assert "attempt_1" in attempt1.log_path.name
        assert "attempt_2" in attempt2.log_path.name


def test_start_item_phase_log_clamps_attempt():
    """Test that attempt < 1 is clamped to 1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        item_logger = logger.start_item_phase_log(
            "item-1", "Test", phase="work", attempt=0, agent_name="agent"
        )
        assert "attempt_1" in item_logger.log_path.name


def test_start_item_phase_log_writes_header():
    """Test that phase log files contain proper header content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        item_logger = logger.start_item_phase_log(
            "item-7", "My Feature", phase="cleanup", attempt=1, agent_name="bot"
        )

        with open(item_logger.log_path, encoding='utf-8') as f:
            content = f.read()

        assert "My Feature" in content
        assert "Agent: bot" in content


def test_item_logger_full_agent_session():
    """Test a realistic sequence: output, tool calls, errors, summary."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir)
        item_logger = ItemLogger(logs_dir, "full-session", "Full Session")

        # Streamed agent output
        item_logger.log_copilot_output("I will fix the bug.\n")
        # Tool call
        item_logger.log_tool_call("grep", "pattern=TODO")
        item_logger.log_tool_call("grep", "pattern=TODO",
                                  result="src/main.py:10: TODO fix", success=True)
        # More output
        item_logger.log_copilot_output("Found the issue, applying fix.\n")
        # Error
        item_logger.log_error("Rate limit exceeded")
        # Summary
        item_logger.log_summary(success=True, request_count=3)

        with open(item_logger.log_path, encoding='utf-8') as f:
            content = f.read()

        assert "I will fix the bug." in content
        assert "grep" in content
        assert "TODO fix" in content
        assert "Found the issue" in content
        assert "Rate limit exceeded" in content
        assert "SUCCESS" in content
        assert "Agent requests: 3" in content
