"""Logging utilities for PokePoke - File-based logging for runs and work items."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid


class RunLogger:
    """Manages logging for a PokePoke run.
    
    Creates a unique directory for each run and manages two types of logs:
    1. Orchestrator log - High-level actions taken by PokePoke (no agent output)
    2. Per-item logs - Detailed agent output for each work item processed
    """
    
    def __init__(self, base_dir: str = "logs"):
        """Initialize the run logger.
        
        Args:
            base_dir: Base directory for all log runs (default: "logs")
        """
        self.run_id = self._generate_run_id()
        self.base_dir = Path(base_dir)
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        
        # Create log files
        self.orchestrator_log_path = self.run_dir / "orchestrator.log"
        self.item_logs_dir = self.run_dir / "items"
        self.item_logs_dir.mkdir(exist_ok=True)
        
        # Track current item logger
        self._current_item_logger: Optional['ItemLogger'] = None
        
        # Write initial orchestrator log entry
        self._init_orchestrator_log()
    
    def _generate_run_id(self) -> str:
        """Generate a unique run ID with timestamp and short UUID.
        
        Returns:
            Run ID in format: YYYYMMDD_HHMMSS_<short-uuid>
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        return f"{timestamp}_{short_uuid}"
    
    def _init_orchestrator_log(self) -> None:
        """Write initial header to orchestrator log."""
        with open(self.orchestrator_log_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("PokePoke Orchestrator Log\n")
            f.write("=" * 80 + "\n")
            f.write(f"Run ID: {self.run_id}\n")
            f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
    
    def log_orchestrator(self, message: str, level: str = "INFO") -> None:
        """Log a message to the orchestrator log.
        
        Args:
            message: Message to log
            level: Log level (INFO, WARNING, ERROR, etc.)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.orchestrator_log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] [{level}] {message}\n")
    
    def start_item_log(self, item_id: str, item_title: str) -> 'ItemLogger':
        """Start logging for a specific work item.
        
        Args:
            item_id: Work item ID
            item_title: Work item title
            
        Returns:
            ItemLogger instance for the work item
        """
        # Close previous item logger if exists
        if self._current_item_logger:
            self._current_item_logger.close()
        
        self._current_item_logger = ItemLogger(
            self.item_logs_dir,
            item_id,
            item_title
        )
        
        self.log_orchestrator(f"Started processing work item: {item_id} - {item_title}")
        return self._current_item_logger
    
    def end_item_log(self, success: bool, request_count: int) -> None:
        """End logging for the current work item.
        
        Args:
            success: Whether the work item was completed successfully
            request_count: Number of agent requests made
        """
        if self._current_item_logger:
            self._current_item_logger.log_summary(success, request_count)
            self._current_item_logger.close()
            self._current_item_logger = None
        
        status = "SUCCESS" if success else "FAILURE"
        self.log_orchestrator(
            f"Completed work item with {request_count} agent requests - Status: {status}"
        )
    
    def log_maintenance(self, agent_type: str, message: str) -> None:
        """Log a maintenance agent action.
        
        Args:
            agent_type: Type of maintenance agent (tech_debt, janitor, etc.)
            message: Message to log
        """
        self.log_orchestrator(f"[MAINTENANCE:{agent_type}] {message}")
    
    def finalize(self, items_completed: int, total_requests: int, elapsed: float) -> None:
        """Write final summary to orchestrator log.
        
        Args:
            items_completed: Number of work items completed
            total_requests: Total number of agent requests made
            elapsed: Total elapsed time in seconds
        """
        with open(self.orchestrator_log_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write("Run Summary\n")
            f.write("=" * 80 + "\n")
            f.write(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Items completed: {items_completed}\n")
            f.write(f"Total agent requests: {total_requests}\n")
            f.write(f"Total time: {elapsed / 60:.1f} minutes\n")
            f.write("=" * 80 + "\n")
        
        self.log_orchestrator("PokePoke run completed")
    
    def get_run_id(self) -> str:
        """Get the run ID for this logger.
        
        Returns:
            Run ID string
        """
        return self.run_id
    
    def get_run_dir(self) -> Path:
        """Get the run directory path.
        
        Returns:
            Path to the run directory
        """
        return self.run_dir


class ItemLogger:
    """Manages logging for a single work item's agent interactions."""
    
    def __init__(self, logs_dir: Path, item_id: str, item_title: str):
        """Initialize the item logger.
        
        Args:
            logs_dir: Directory to store item logs
            item_id: Work item ID
            item_title: Work item title
        """
        self.item_id = item_id
        self.item_title = item_title
        
        # Create log file with sanitized filename
        safe_id = item_id.replace('/', '_').replace('\\', '_')
        self.log_path = logs_dir / f"{safe_id}.log"
        
        # Initialize log file
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"Work Item: {item_id}\n")
            f.write(f"Title: {item_title}\n")
            f.write("=" * 80 + "\n")
            f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
        
        # Track whether file is open
        self._file_handle: Optional[object] = None
    
    def log(self, message: str) -> None:
        """Log a message to the item log.
        
        Args:
            message: Message to log
        """
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(message)
            # Don't add newline - let caller control formatting
    
    def log_with_timestamp(self, message: str, level: str = "INFO") -> None:
        """Log a message with timestamp.
        
        Args:
            message: Message to log
            level: Log level
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] [{level}] {message}\n")
    
    def log_summary(self, success: bool, request_count: int) -> None:
        """Log summary information for the work item.
        
        Args:
            success: Whether the work item was completed successfully
            request_count: Number of agent requests made
        """
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write("Summary\n")
            f.write("=" * 80 + "\n")
            f.write(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Status: {'SUCCESS' if success else 'FAILURE'}\n")
            f.write(f"Agent requests: {request_count}\n")
            f.write("=" * 80 + "\n")
    
    def close(self) -> None:
        """Close the item logger."""
        # Nothing to do - we use context managers for writes
        pass
