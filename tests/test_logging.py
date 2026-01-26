"""Tests for logging utilities."""

import pytest
from pathlib import Path
import tempfile
import shutil
from pokepoke.logging_utils import RunLogger, ItemLogger


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
        with open(logger.orchestrator_log_path, 'r', encoding='utf-8') as f:
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
        item_logger = logger.start_item_log("test-item-123", "Test Item Title")
        
        # Log some content
        item_logger.log("Test agent output\n")
        item_logger.log_with_timestamp("Test timestamped message")
        
        # End item log
        logger.end_item_log(success=True, request_count=5)
        
        # Check that item log file exists
        item_log_path = logger.item_logs_dir / "test-item-123.log"
        assert item_log_path.exists()
        
        # Read the log file
        with open(item_log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that content is present
        assert "test-item-123" in content
        assert "Test Item Title" in content
        assert "Test agent output" in content
        assert "Test timestamped message" in content
        assert "SUCCESS" in content
        assert "Agent requests: 5" in content


def test_run_logger_finalize():
    """Test that finalize writes summary correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)
        
        # Finalize the run
        logger.finalize(items_completed=3, total_requests=15, elapsed=120.5)
        
        # Read the log file
        with open(logger.orchestrator_log_path, 'r', encoding='utf-8') as f:
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
        with open(logger.orchestrator_log_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check that maintenance logs are present
        assert "[MAINTENANCE:tech_debt]" in content
        assert "Starting Tech Debt Agent" in content
        assert "[MAINTENANCE:janitor]" in content
        assert "Janitor Agent completed successfully" in content


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


def test_multiple_item_logs():
    """Test that multiple items can be logged in sequence."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = RunLogger(base_dir=tmpdir)
        
        # Process first item
        item_logger1 = logger.start_item_log("item-1", "First Item")
        item_logger1.log("First item output\n")
        logger.end_item_log(success=True, request_count=3)
        
        # Process second item
        item_logger2 = logger.start_item_log("item-2", "Second Item")
        item_logger2.log("Second item output\n")
        logger.end_item_log(success=False, request_count=5)
        
        # Check that both item logs exist
        assert (logger.item_logs_dir / "item-1.log").exists()
        assert (logger.item_logs_dir / "item-2.log").exists()
        
        # Read first item log
        with open(logger.item_logs_dir / "item-1.log", 'r', encoding='utf-8') as f:
            content1 = f.read()
        assert "First item output" in content1
        assert "SUCCESS" in content1
        
        # Read second item log
        with open(logger.item_logs_dir / "item-2.log", 'r', encoding='utf-8') as f:
            content2 = f.read()
        assert "Second item output" in content2
        assert "FAILURE" in content2
