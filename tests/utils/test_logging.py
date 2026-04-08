"""Tests for logging utilities."""

import json
import logging
import tempfile
import time
from pathlib import Path

from pokepoke.utils.logging_utils import (
    EventFilter,
    ItemLogger,
    JsonFormatter,
    LifecycleFilter,
    MaintenanceFilter,
    RunLogger,
    WorkItemFilter,
    configure_logging,
)


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

        try:
            # Check that run directory was created
            assert logger.get_run_dir().exists()

            # Check that all three orchestrator logs were created
            assert (logger.get_run_dir() / "orchestrator-events.log").exists()
            assert (logger.get_run_dir() / "orchestrator-maintenance.log").exists()
            assert (logger.get_run_dir() / "orchestrator-lifecycle.log").exists()

            # Check that items directory was created
            assert (logger.get_run_dir() / "items").exists()

            # Check run ID format (should be YYYYMMDD_HHMMSS_<uuid>)
            run_id = logger.get_run_id()
            parts = run_id.split('_')
            assert len(parts) == 3
            assert len(parts[0]) == 8  # YYYYMMDD
            assert len(parts[1]) == 6  # HHMMSS
            assert len(parts[2]) == 8  # short UUID
        finally:
            logger.close()


def test_run_logger_orchestrator_logging():
    """Test that orchestrator logging works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            # Log some messages
            logger.log_orchestrator("Test message 1")
            logger.log_orchestrator("Test warning", level="WARNING")
            logger.log_orchestrator("Test error", level="ERROR")

            # Read the log file (events log for warnings/errors)
            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            # Check that messages are present (Note: "Test message 1" won't be in events log)
            # Only warnings and errors go to events log
            assert "Test warning" in content
            assert "Test error" in content
            assert "[WARNING]" in content
            assert "[ERROR]" in content
        finally:
            logger.close()


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
        logger.close()


def test_run_logger_finalize():
    """Test that finalize writes summary correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            # Finalize the run
            logger.finalize(items_completed=3, total_requests=15, elapsed=120.5)

            # Read the log file (events log contains finalize messages)
            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            # Check that summary is present
            assert "Run Summary" in content
            assert "Items completed: 3" in content
            assert "Total agent requests: 15" in content
            assert "Total time: 2.0 minutes" in content
        finally:
            logger.close()


def test_run_logger_maintenance_logging():
    """Test that maintenance logging works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            # Log maintenance actions
            logger.log_maintenance("tech_debt", "Starting Tech Debt Agent")
            logger.log_maintenance("janitor", "Janitor Agent completed successfully")

            # Read the maintenance log file (not events log)
            with open(logger.orchestrator_maintenance_log_path, encoding='utf-8') as f:
                content = f.read()

            # Check that maintenance logs are present
            assert "[MAINTENANCE:tech_debt]" in content
            assert "Starting Tech Debt Agent" in content
            assert "[MAINTENANCE:janitor]" in content
            assert "Janitor Agent completed successfully" in content
        finally:
            logger.close()


def test_run_logger_creates_maintenance_dir():
    """Test that RunLogger creates a maintenance logs directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)
        assert (logger.get_run_dir() / "maintenance").exists()
        logger.close()


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
        logger.close()


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
        logger.close()


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
        logger.close()


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
        logger.close()


def test_get_item_dir_sanitizes_slashes():
    """Test that _get_item_dir replaces slashes in item IDs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        item_dir = logger._get_item_dir("task/with/slashes")
        assert item_dir.name == "task_with_slashes"
        assert item_dir.exists()
        logger.close()


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
        logger.close()


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
        logger.close()


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
        logger.close()


def test_start_item_phase_log_clamps_attempt():
    """Test that attempt < 1 is clamped to 1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        item_logger = logger.start_item_phase_log(
            "item-1", "Test", phase="work", attempt=0, agent_name="agent"
        )
        assert "attempt_1" in item_logger.log_path.name
        logger.close()


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
        logger.close()


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


def test_log_polling_first_cycle_is_debug():
    """First poll cycle should be logged at DEBUG (not INFO)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir, poll_log_interval=5)

        try:
            logger.log_polling("Checking status")

            # Polling messages go to lifecycle log
            with open(logger.orchestrator_lifecycle_log_path, encoding='utf-8') as f:
                content = f.read()

            assert "[DEBUG]" in content
            assert "[poll #1]" in content
            assert "Checking status" in content
        finally:
            logger.close()


def test_log_polling_nth_cycle_is_info():
    """Every Nth poll cycle should be logged at INFO."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir, poll_log_interval=3)

        try:
            for _ in range(3):
                logger.log_polling("status check")

            # Polling messages go to lifecycle log
            with open(logger.orchestrator_lifecycle_log_path, encoding='utf-8') as f:
                content = f.read()

            lines = [ln for ln in content.splitlines() if "status check" in ln]
            assert len(lines) == 3
            # Cycles 1, 2 are DEBUG; cycle 3 is INFO
            assert "[DEBUG]" in lines[0]
            assert "[DEBUG]" in lines[1]
            assert "[INFO]" in lines[2]
            assert "[poll #3]" in lines[2]
        finally:
            logger.close()


def test_log_polling_suppresses_most_cycles():
    """With default interval=50, only cycle 50 out of 50 should be INFO."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            for _ in range(50):
                logger.log_polling("polling message")

            # Polling messages go to lifecycle log
            with open(logger.orchestrator_lifecycle_log_path, encoding='utf-8') as f:
                content = f.read()

            poll_lines = [ln for ln in content.splitlines() if "polling message" in ln]
            info_lines = [ln for ln in poll_lines if "[INFO]" in ln]
            debug_lines = [ln for ln in poll_lines if "[DEBUG]" in ln]
            assert len(poll_lines) == 50
            assert len(info_lines) == 1
            assert len(debug_lines) == 49
        finally:
            logger.close()


def test_enter_idle_logs_once():
    """enter_idle should log a message on first call, be a no-op on subsequent calls."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            logger.enter_idle()
            logger.enter_idle()  # should be no-op

            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            idle_lines = [ln for ln in content.splitlines() if "Entering idle state" in ln]
            assert len(idle_lines) == 1
        finally:
            logger.close()


def test_exit_idle_logs_duration():
    """exit_idle should log idle duration and reset poll cycle counter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            logger._idle_since = time.time() - 65  # 1m 5s ago
            logger._poll_cycle = 42

            logger.exit_idle()

            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            assert "Exiting idle state" in content
            assert "1m" in content
            assert "42 poll cycles" in content
            assert logger._idle_since is None
            assert logger._poll_cycle == 0
        finally:
            logger.close()


def test_exit_idle_noop_when_not_idle():
    """exit_idle should be a no-op if not currently idle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            logger.exit_idle()  # not idle — should not log anything

            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            assert "Exiting idle state" not in content
        finally:
            logger.close()


def test_exit_idle_resets_poll_cycle():
    """exit_idle should reset the poll cycle counter so INFO cycles restart."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir, poll_log_interval=3)

        try:
            # Simulate idle period with some polls
            logger.enter_idle()
            for _ in range(5):
                logger.log_polling("idle poll")

            logger._idle_since = time.time() - 10
            logger.exit_idle()

            # After exit, poll cycle should restart from 0
            assert logger._poll_cycle == 0

            # Next cycle 3 should be INFO again
            for _ in range(3):
                logger.log_polling("active poll")

            # Polling messages go to lifecycle log
            with open(logger.orchestrator_lifecycle_log_path, encoding='utf-8') as f:
                content = f.read()

            active_lines = [ln for ln in content.splitlines() if "active poll" in ln]
            assert "[INFO]" in active_lines[2]
            assert "[poll #3]" in active_lines[2]
        finally:
            logger.close()


def test_idle_duration_hours_format():
    """Long idle periods should format with hours."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            logger._idle_since = time.time() - 3661  # 1h 1m 1s
            logger._poll_cycle = 100

            logger.exit_idle()

            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            assert "1h 1m 1s" in content
        finally:
            logger.close()


# ── Repo-context logging tests───────────────────────────────────────


def test_run_logger_repo_name_in_header():
    """RunLogger with repo_name should include it in the orchestrator log header."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir, repo_name="PokePoke")

        try:
            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            assert "Repository: PokePoke" in content
        finally:
            logger.close()


def test_run_logger_repo_name_in_log_lines():
    """Log lines should include repo name tag when set."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir, repo_name="MyRepo")

        try:
            # Use WARNING level so message passes EventFilter
            logger.log_orchestrator("something happened", level="WARNING")

            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            assert "[MyRepo]" in content
            assert "something happened" in content
        finally:
            logger.close()


def test_run_logger_no_repo_name_omits_tag():
    """When no repo name is set, log lines should not have an empty tag."""
    from pokepoke.stats.metrics_context import set_current_repo_name
    set_current_repo_name(None)

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)

        try:
            # Use WARNING level so message passes EventFilter
            logger.log_orchestrator("plain message", level="WARNING")

            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            lines = [ln for ln in content.splitlines() if "plain message" in ln]
            assert len(lines) == 1
            assert "[]" not in lines[0]
        finally:
            logger.close()


def test_run_logger_picks_up_thread_local_repo():
    """Without repo_name param, log_orchestrator should read thread-local context."""
    from pokepoke.stats.metrics_context import set_current_repo_name
    set_current_repo_name("ThreadRepo")

    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)
        try:
            # Use WARNING level so message passes EventFilter
            logger.log_orchestrator("from context", level="WARNING")

            with open(logger.orchestrator_log_path, encoding='utf-8') as f:
                content = f.read()

            assert "[ThreadRepo]" in content
        finally:
            logger.close()
            set_current_repo_name(None)


# ── WorkItemFilter tests ────────────────────────────────────────────


def test_work_item_filter_injects_fields():
    """WorkItemFilter should add work_item_id, repo_name, agent_type to records."""
    from pokepoke.stats.metrics_context import (
        set_current_agent_type,
        set_current_repo_name,
        set_current_work_item_id,
    )
    set_current_work_item_id("PokePoke-abc1")
    set_current_repo_name("MyRepo")
    set_current_agent_type("work")

    try:
        filt = WorkItemFilter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        result = filt.filter(record)

        assert result is True
        assert record.work_item_id == "PokePoke-abc1"  # type: ignore[attr-defined]
        assert record.repo_name == "MyRepo"  # type: ignore[attr-defined]
        assert record.agent_type == "work"  # type: ignore[attr-defined]
    finally:
        set_current_work_item_id(None)
        set_current_repo_name(None)
        set_current_agent_type(None)


def test_work_item_filter_defaults_to_empty():
    """WorkItemFilter should default to empty strings when context is unset."""
    from pokepoke.stats.metrics_context import (
        set_current_agent_type,
        set_current_repo_name,
        set_current_work_item_id,
    )
    set_current_work_item_id(None)
    set_current_repo_name(None)
    set_current_agent_type(None)

    filt = WorkItemFilter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    filt.filter(record)

    assert record.work_item_id == ""  # type: ignore[attr-defined]
    assert record.repo_name == ""  # type: ignore[attr-defined]
    assert record.agent_type == ""  # type: ignore[attr-defined]


# ── JsonFormatter tests ─────────────────────────────────────────────


def test_json_formatter_basic_output():
    """JsonFormatter should produce valid JSON with required fields."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="pokepoke.test", level=logging.WARNING, pathname="", lineno=0,
        msg="test warning", args=(), exc_info=None,
    )
    output = formatter.format(record)
    data = json.loads(output)

    assert data["level"] == "WARNING"
    assert data["logger"] == "pokepoke.test"
    assert data["message"] == "test warning"
    assert "timestamp" in data


def test_json_formatter_includes_work_item_id():
    """JsonFormatter should include work_item_id when present on record."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="pokepoke.test", level=logging.INFO, pathname="", lineno=0,
        msg="processing", args=(), exc_info=None,
    )
    record.work_item_id = "PokePoke-xyz9"  # type: ignore[attr-defined]
    record.repo_name = ""  # type: ignore[attr-defined]
    record.agent_type = ""  # type: ignore[attr-defined]

    output = formatter.format(record)
    data = json.loads(output)

    assert data["work_item_id"] == "PokePoke-xyz9"
    assert "repo_name" not in data
    assert "agent_type" not in data


def test_json_formatter_includes_all_context():
    """JsonFormatter should include all context fields when present."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="pokepoke.test", level=logging.INFO, pathname="", lineno=0,
        msg="full context", args=(), exc_info=None,
    )
    record.work_item_id = "item-1"  # type: ignore[attr-defined]
    record.repo_name = "PokePoke"  # type: ignore[attr-defined]
    record.agent_type = "gate"  # type: ignore[attr-defined]

    output = formatter.format(record)
    data = json.loads(output)

    assert data["work_item_id"] == "item-1"
    assert data["repo_name"] == "PokePoke"
    assert data["agent_type"] == "gate"


def test_json_formatter_omits_empty_context():
    """JsonFormatter should omit context fields when empty."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="no context", args=(), exc_info=None,
    )
    record.work_item_id = ""  # type: ignore[attr-defined]
    record.repo_name = ""  # type: ignore[attr-defined]
    record.agent_type = ""  # type: ignore[attr-defined]

    output = formatter.format(record)
    data = json.loads(output)

    assert "work_item_id" not in data


# ==============================================================================
# Tests for split log files (events, maintenance, lifecycle)
# ==============================================================================


def test_run_logger_creates_three_separate_log_files(tmp_path):
    """RunLogger should create three separate log files: events, maintenance, lifecycle."""
    run_logger = RunLogger(base_dir=str(tmp_path), repo_name="test-repo")

    try:
        # Check that all three log files exist
        assert run_logger.orchestrator_events_log_path.exists()
        assert run_logger.orchestrator_maintenance_log_path.exists()
        assert run_logger.orchestrator_lifecycle_log_path.exists()

        # Check file names
        assert run_logger.orchestrator_events_log_path.name == "orchestrator-events.log"
        assert run_logger.orchestrator_maintenance_log_path.name == "orchestrator-maintenance.log"
        assert run_logger.orchestrator_lifecycle_log_path.name == "orchestrator-lifecycle.log"

        # Check backwards compatibility
        assert run_logger.orchestrator_log_path == run_logger.orchestrator_events_log_path
    finally:
        run_logger.close()


def test_run_logger_events_log_contains_important_events(tmp_path):
    """Events log should contain submissions, completions, errors, warnings."""
    run_logger = RunLogger(base_dir=str(tmp_path))

    try:
        # Log various types of messages
        run_logger.log_orchestrator("Started processing work item: TEST-123", level="INFO")
        run_logger.log_orchestrator("Work item completed successfully", level="INFO")
        run_logger.log_orchestrator("An error occurred", level="ERROR")
        run_logger.log_orchestrator("A warning was issued", level="WARNING")
        run_logger.log_orchestrator("Cleanup agent still holding lock", level="DEBUG")  # Maintenance
        run_logger.log_polling("Poll iteration check")  # Lifecycle

        # Read events log
        events_content = run_logger.orchestrator_events_log_path.read_text(encoding="utf-8")

        # Events should contain important messages
        assert "Started processing work item: TEST-123" in events_content
        assert "Work item completed successfully" in events_content
        assert "An error occurred" in events_content
        assert "A warning was issued" in events_content

        # Events should NOT contain maintenance or lifecycle messages
        assert "Cleanup agent still holding lock" not in events_content
        assert "Poll iteration check" not in events_content
    finally:
        run_logger.close()


def test_run_logger_maintenance_log_contains_lock_messages(tmp_path):
    """Maintenance log should contain cleanup locks, dirty repo waits."""
    run_logger = RunLogger(base_dir=str(tmp_path))

    try:
        # Log various types of messages
        run_logger.log_orchestrator("Started processing work item: TEST-123", level="INFO")  # Event
        run_logger.log_orchestrator("Cleanup agent still holding lock", level="DEBUG")
        run_logger.log_orchestrator("Waiting for cleanup to finish", level="DEBUG")
        run_logger.log_orchestrator("dirty repo detected, waiting", level="DEBUG")
        run_logger.log_orchestrator("[MAINTENANCE:cleanup] Running cleanup", level="INFO")
        run_logger.log_polling("Poll iteration check")  # Lifecycle

        # Read maintenance log
        maintenance_content = run_logger.orchestrator_maintenance_log_path.read_text(encoding="utf-8")

        # Maintenance should contain lock/wait messages
        assert "Cleanup agent still holding lock" in maintenance_content
        assert "Waiting for cleanup" in maintenance_content
        assert "dirty repo" in maintenance_content
        assert "[MAINTENANCE:cleanup]" in maintenance_content

        # Maintenance should NOT contain events or lifecycle messages
        assert "Started processing work item: TEST-123" not in maintenance_content
        assert "Poll iteration check" not in maintenance_content
    finally:
        run_logger.close()


def test_run_logger_lifecycle_log_contains_poll_messages(tmp_path):
    """Lifecycle log should contain poll iterations and memory tracking."""
    run_logger = RunLogger(base_dir=str(tmp_path))

    try:
        # Log various types of messages
        run_logger.log_orchestrator("Started processing work item: TEST-123", level="INFO")  # Event
        run_logger.log_orchestrator("Cleanup agent still holding lock", level="DEBUG")  # Maintenance
        run_logger.log_polling("Checking for work items")
        run_logger.log_orchestrator("Memory usage: 256MB", level="DEBUG")
        run_logger.log_orchestrator("Poll cycle #50 completed", level="DEBUG")

        # Read lifecycle log
        lifecycle_content = run_logger.orchestrator_lifecycle_log_path.read_text(encoding="utf-8")

        # Lifecycle should contain poll and memory messages
        assert "[poll #" in lifecycle_content
        assert "Checking for work items" in lifecycle_content
        assert "Memory usage" in lifecycle_content
        assert "Poll cycle" in lifecycle_content

        # Lifecycle should NOT contain events or maintenance messages
        assert "Started processing work item: TEST-123" not in lifecycle_content
        assert "Cleanup agent still holding lock" not in lifecycle_content
    finally:
        run_logger.close()


def test_run_logger_idle_messages_in_events_log(tmp_path):
    """Idle state messages should appear in events log as they're important state changes."""
    run_logger = RunLogger(base_dir=str(tmp_path))

    try:
        run_logger.enter_idle()
        time.sleep(0.1)
        run_logger.exit_idle()

        events_content = run_logger.orchestrator_events_log_path.read_text(encoding="utf-8")

        assert "Entering idle state" in events_content
        assert "Exiting idle state" in events_content
    finally:
        run_logger.close()


def test_run_logger_headers_in_all_three_files(tmp_path):
    """All three log files should have descriptive headers."""
    run_logger = RunLogger(base_dir=str(tmp_path), repo_name="test-repo")

    try:
        events_content = run_logger.orchestrator_events_log_path.read_text(encoding="utf-8")
        maintenance_content = run_logger.orchestrator_maintenance_log_path.read_text(encoding="utf-8")
        lifecycle_content = run_logger.orchestrator_lifecycle_log_path.read_text(encoding="utf-8")

        # Check events header
        assert "PokePoke Orchestrator Events Log" in events_content
        assert "Submissions, completions, errors, warnings" in events_content
        assert "test-repo" in events_content

        # Check maintenance header
        assert "PokePoke Orchestrator Maintenance Log" in maintenance_content
        assert "Cleanup locks, dirty repo waits, merge locks" in maintenance_content
        assert "test-repo" in maintenance_content

        # Check lifecycle header
        assert "PokePoke Orchestrator Lifecycle Log" in lifecycle_content
        assert "Poll iterations, memory tracking" in lifecycle_content
        assert "test-repo" in lifecycle_content
    finally:
        run_logger.close()


def test_run_logger_close_removes_all_handlers(tmp_path):
    """close() should remove and close all three handlers."""
    run_logger = RunLogger(base_dir=str(tmp_path))

    # Get logger and count handlers before close
    py_logger = run_logger._py_logger
    initial_handler_count = len(py_logger.handlers)
    assert initial_handler_count >= 3, "Should have at least 3 handlers (events, maintenance, lifecycle)"

    # Close should remove all handlers
    run_logger.close()

    # Verify handlers are removed
    assert len(py_logger.handlers) < initial_handler_count

    # close() should be idempotent
    run_logger.close()  # Should not raise


def test_event_filter_accepts_warnings_and_errors():
    """EventFilter should accept all WARNING and ERROR level messages."""

    event_filter = EventFilter()

    # Create records at different levels
    warning_record = logging.LogRecord(
        name="test", level=logging.WARNING, pathname="", lineno=0,
        msg="This is a warning", args=(), exc_info=None,
    )
    error_record = logging.LogRecord(
        name="test", level=logging.ERROR, pathname="", lineno=0,
        msg="This is an error", args=(), exc_info=None,
    )
    debug_record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="This is debug", args=(), exc_info=None,
    )

    assert event_filter.filter(warning_record) is True
    assert event_filter.filter(error_record) is True
    assert event_filter.filter(debug_record) is False


def test_event_filter_accepts_info_with_keywords():
    """EventFilter should accept INFO messages with event keywords."""

    event_filter = EventFilter()

    # INFO with event keyword
    event_record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Started processing work item TEST-123", args=(), exc_info=None,
    )

    # INFO without event keyword
    non_event_record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Just some regular info", args=(), exc_info=None,
    )

    assert event_filter.filter(event_record) is True
    assert event_filter.filter(non_event_record) is False


def test_maintenance_filter_accepts_lock_messages():
    """MaintenanceFilter should accept messages with maintenance keywords."""

    maintenance_filter = MaintenanceFilter()

    # Maintenance keyword present
    lock_record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="Cleanup agent still holding lock", args=(), exc_info=None,
    )

    # No maintenance keyword
    normal_record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="Regular debug message", args=(), exc_info=None,
    )

    assert maintenance_filter.filter(lock_record) is True
    assert maintenance_filter.filter(normal_record) is False


def test_lifecycle_filter_accepts_poll_messages():
    """LifecycleFilter should accept DEBUG and INFO messages with lifecycle keywords."""

    lifecycle_filter = LifecycleFilter()

    # DEBUG with lifecycle keyword
    poll_record = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="[poll #50] Checking for work", args=(), exc_info=None,
    )

    # INFO with lifecycle keyword (should accept now)
    info_poll_record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="[poll #50] Checking for work", args=(), exc_info=None,
    )

    # WARNING with lifecycle keyword (should reject to avoid duplicates with events)
    warning_poll_record = logging.LogRecord(
        name="test", level=logging.WARNING, pathname="", lineno=0,
        msg="[poll #50] Checking for work", args=(), exc_info=None,
    )

    # DEBUG without lifecycle keyword
    normal_debug = logging.LogRecord(
        name="test", level=logging.DEBUG, pathname="", lineno=0,
        msg="Regular debug message", args=(), exc_info=None,
    )

    assert lifecycle_filter.filter(poll_record) is True
    assert lifecycle_filter.filter(info_poll_record) is True
    assert lifecycle_filter.filter(warning_poll_record) is False
    assert lifecycle_filter.filter(normal_debug) is False


def test_json_formatter_includes_exception():
    """JsonFormatter should include exception info when present."""
    formatter = JsonFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="error occurred", args=(), exc_info=sys.exc_info(),
        )

    output = formatter.format(record)
    data = json.loads(output)

    assert "exception" in data
    assert "ValueError" in data["exception"]
    assert "test error" in data["exception"]


# ── configure_logging with new features ─────────────────────────────


def test_configure_logging_attaches_work_item_filter(tmp_path):
    """configure_logging should attach WorkItemFilter to root handlers."""
    log_file = tmp_path / "debug.log"

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_filters = root.filters[:]
    root.handlers.clear()
    root.filters.clear()

    pokepoke_logger = logging.getLogger("pokepoke")
    original_pp_handlers = pokepoke_logger.handlers[:]
    pokepoke_logger.handlers.clear()

    try:
        configure_logging(log_file)

        for handler in root.handlers:
            assert any(isinstance(f, WorkItemFilter) for f in handler.filters), \
                f"Handler {handler} should have WorkItemFilter"
    finally:
        root.handlers = original_handlers
        root.filters = original_filters
        pokepoke_logger.handlers = original_pp_handlers


def test_configure_logging_no_duplicate_filters(tmp_path):
    """Calling configure_logging twice should not add duplicate WorkItemFilters."""
    log_file = tmp_path / "debug.log"

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_filters = root.filters[:]
    root.handlers.clear()
    root.filters.clear()

    pokepoke_logger = logging.getLogger("pokepoke")
    original_pp_handlers = pokepoke_logger.handlers[:]
    pokepoke_logger.handlers.clear()

    try:
        configure_logging(log_file)
        configure_logging(log_file)

        for handler in root.handlers:
            filter_count = sum(1 for f in handler.filters if isinstance(f, WorkItemFilter))
            assert filter_count == 1, f"Handler {handler} should have exactly one WorkItemFilter"
    finally:
        root.handlers = original_handlers
        root.filters = original_filters
        pokepoke_logger.handlers = original_pp_handlers


def test_configure_logging_json_output(tmp_path):
    """configure_logging with json_output=True should use JsonFormatter."""
    log_file = tmp_path / "debug.log"

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_filters = root.filters[:]
    root.handlers.clear()
    root.filters.clear()

    pokepoke_logger = logging.getLogger("pokepoke")
    original_pp_handlers = pokepoke_logger.handlers[:]
    pokepoke_logger.handlers.clear()

    try:
        configure_logging(log_file, json_output=True)

        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) >= 1
        assert isinstance(file_handlers[0].formatter, JsonFormatter), \
            "File handler should use JsonFormatter"
    finally:
        root.handlers = original_handlers
        root.filters = original_filters
        pokepoke_logger.handlers = original_pp_handlers


def test_configure_logging_json_output_writes_valid_json(tmp_path):
    """JSON output mode should write valid JSON lines to the log file."""
    from pokepoke.stats.metrics_context import set_current_work_item_id
    log_file = tmp_path / "debug.log"

    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_filters = root.filters[:]
    root.handlers.clear()
    root.filters.clear()

    pokepoke_logger = logging.getLogger("pokepoke")
    original_pp_handlers = pokepoke_logger.handlers[:]
    pokepoke_logger.handlers.clear()

    set_current_work_item_id("json-test-item")
    try:
        configure_logging(log_file, json_output=True)

        test_logger = logging.getLogger("pokepoke.json_test")
        test_logger.info("json log message")

        # Flush handlers
        for h in root.handlers:
            h.flush()

        with open(log_file, encoding="utf-8") as f:
            content = f.read().strip()

        assert content, "Log file should not be empty"
        data = json.loads(content)
        assert data["message"] == "json log message"
        assert data["work_item_id"] == "json-test-item"
    finally:
        root.handlers = original_handlers
        root.filters = original_filters
        pokepoke_logger.handlers = original_pp_handlers
        set_current_work_item_id(None)


# ── RunLogger Python logging bridge tests ───────────────────────────


def test_run_logger_bridges_to_python_logging():
    """RunLogger.log_orchestrator should also emit via Python logging."""
    captured: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    py_logger = logging.getLogger("pokepoke.orchestration.orchestrator")
    handler = CaptureHandler()
    py_logger.addHandler(handler)
    original_level = py_logger.level
    py_logger.setLevel(logging.DEBUG)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(base_dir=tmpdir)
            run_logger.log_orchestrator("bridge test message")
            run_logger.close()

        assert any("bridge test message"in r.getMessage() for r in captured)
    finally:
        py_logger.removeHandler(handler)
        py_logger.setLevel(original_level)


def test_run_logger_bridge_respects_level():
    """RunLogger bridge should map string level to Python logging level."""
    captured: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    py_logger = logging.getLogger("pokepoke.orchestration.orchestrator")
    handler = CaptureHandler()
    py_logger.addHandler(handler)
    original_level = py_logger.level
    py_logger.setLevel(logging.DEBUG)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(base_dir=tmpdir)
            run_logger.log_orchestrator("warning msg", level="WARNING")
            run_logger.close()

        warning_records= [r for r in captured if r.levelno == logging.WARNING]
        assert any("warning msg" in r.getMessage() for r in warning_records)
    finally:
        py_logger.removeHandler(handler)
        py_logger.setLevel(original_level)


# ── ItemLogger Python logging bridge tests ──────────────────────────


def test_item_logger_error_bridges_to_python_logging():
    """ItemLogger.log_error should emit via Python logging."""
    captured: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    py_logger = logging.getLogger("pokepoke.item.test-item-42")
    handler = CaptureHandler()
    py_logger.addHandler(handler)
    original_level = py_logger.level
    py_logger.setLevel(logging.DEBUG)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logs_dir = Path(tmpdir)
            item_logger = ItemLogger(logs_dir, "test-item-42", "Test Item")
            item_logger.log_error("something broke")

        error_records = [r for r in captured if r.levelno == logging.ERROR]
        assert any("something broke" in r.getMessage() for r in error_records)
    finally:
        py_logger.removeHandler(handler)
        py_logger.setLevel(original_level)


def test_item_logger_summary_bridges_to_python_logging():
    """ItemLogger.log_summary should emit via Python logging."""
    captured: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    py_logger = logging.getLogger("pokepoke.item.test-summary-1")
    handler = CaptureHandler()
    py_logger.addHandler(handler)
    original_level = py_logger.level
    py_logger.setLevel(logging.DEBUG)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logs_dir = Path(tmpdir)
            item_logger = ItemLogger(logs_dir, "test-summary-1", "Summary Test")
            item_logger.log_summary(success=True, request_count=7)

        info_records = [r for r in captured if r.levelno == logging.INFO]
        assert any("SUCCESS" in r.getMessage() for r in info_records)
        assert any("7" in r.getMessage() for r in info_records)
    finally:
        py_logger.removeHandler(handler)
        py_logger.setLevel(original_level)


def test_item_logger_tool_call_bridges_to_python_logging():
    """ItemLogger.log_tool_call should emit via Python logging."""
    captured: list[logging.LogRecord] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    py_logger = logging.getLogger("pokepoke.item.test-tool-bridge")
    handler = CaptureHandler()
    py_logger.addHandler(handler)
    original_level = py_logger.level
    py_logger.setLevel(logging.DEBUG)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            logs_dir = Path(tmpdir)
            item_logger = ItemLogger(logs_dir, "test-tool-bridge", "Tool Bridge")
            item_logger.log_tool_call("grep", "pattern=TODO", result="found 3", success=True)

        assert any("grep" in r.getMessage() for r in captured)
    finally:
        py_logger.removeHandler(handler)
        py_logger.setLevel(original_level)
