"""Process diagnostics log parser for desktop UI visualization."""
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ProcessSnapshot:
    """Single snapshot of process resource usage."""

    timestamp: datetime
    copilot_count: int
    child_count: int
    total_memory_mb: float
    cpu_percent: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            'timestamp': self.timestamp.isoformat(),
            'copilot_count': self.copilot_count,
            'child_count': self.child_count,
            'total_memory_mb': round(self.total_memory_mb, 1),
            'cpu_percent': round(self.cpu_percent, 1),
        }


def parse_diagnostics_log(log_path: Path, limit: int = 100) -> list[ProcessSnapshot]:
    """Parse tool_diagnostics.log and extract process snapshots.

    Args:
        log_path: Path to tool_diagnostics.log file
        limit: Maximum number of snapshots to return (most recent)

    Returns:
        List of ProcessSnapshot objects, ordered by timestamp (oldest first)
    """
    if not log_path.exists():
        return []

    snapshots: list[ProcessSnapshot] = []

    # Regex to match: [2026-04-01 20:15:00] PROCESS_SNAPSHOT copilot_count=8 child_count=42 total_memory_mb=3456.7 cpu_percent=25.3
    # Also matches legacy format without cpu_percent for backward compatibility
    pattern = re.compile(
        r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] PROCESS_SNAPSHOT '
        r'copilot_count=(\d+) '
        r'child_count=(\d+) '
        r'total_memory_mb=([\d.]+)'
        r'(?: cpu_percent=([\d.]+))?'
    )

    try:
        with open(log_path, encoding='utf-8', errors='replace') as f:
            for line in f:
                match = pattern.search(line)
                if match:
                    groups = match.groups()
                    timestamp_str = groups[0]
                    copilot_count_str = groups[1]
                    child_count_str = groups[2]
                    memory_str = groups[3]
                    cpu_str = groups[4]  # May be None for legacy entries
                    try:
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                        copilot_count = int(copilot_count_str)
                        child_count = int(child_count_str)
                        total_memory_mb = float(memory_str)
                        cpu_percent = float(cpu_str) if cpu_str else 0.0

                        snapshot = ProcessSnapshot(
                            timestamp=timestamp,
                            copilot_count=copilot_count,
                            child_count=child_count,
                            total_memory_mb=total_memory_mb,
                            cpu_percent=cpu_percent,
                        )
                        snapshots.append(snapshot)
                    except (ValueError, TypeError):
                        continue  # Skip malformed entries
    except Exception:
        return []

    # Return last N snapshots
    if len(snapshots) > limit:
        snapshots = snapshots[-limit:]

    return snapshots


def get_latest_diagnostics(run_dir: Path, limit: int = 100) -> list[ProcessSnapshot]:
    """Get latest process diagnostics snapshots from current run.

    Args:
        run_dir: Path to PokePoke run directory (e.g., .pokepoke/logs/run_YYYYMMDD_HHMMSS)
        limit: Maximum number of snapshots to return

    Returns:
        List of ProcessSnapshot objects, ordered by timestamp
    """
    log_path = run_dir / "tool_diagnostics.log"
    return parse_diagnostics_log(log_path, limit=limit)
