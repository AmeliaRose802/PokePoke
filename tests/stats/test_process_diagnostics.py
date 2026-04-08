"""Test process diagnostics log parsing."""
import tempfile
from datetime import datetime
from pathlib import Path

from pokepoke.stats.process_diagnostics import (
    ProcessSnapshot,
    get_latest_diagnostics,
    parse_diagnostics_log,
)


def test_parse_diagnostics_log_empty_file():
    """Test parsing an empty log file."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        log_path = Path(f.name)

    try:
        snapshots = parse_diagnostics_log(log_path)
        assert snapshots == []
    finally:
        log_path.unlink()


def test_parse_diagnostics_log_nonexistent_file():
    """Test parsing a file that doesn't exist."""
    log_path = Path("/nonexistent/path/tool_diagnostics.log")
    snapshots = parse_diagnostics_log(log_path)
    assert snapshots == []


def test_parse_diagnostics_log_single_snapshot():
    """Test parsing a log file with a single snapshot."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        f.write("[2026-04-01 20:15:30] PROCESS_SNAPSHOT copilot_count=4 child_count=12 total_memory_mb=2048.5 cpu_percent=25.3\n")
        log_path = Path(f.name)

    try:
        snapshots = parse_diagnostics_log(log_path)
        assert len(snapshots) == 1
        assert snapshots[0].copilot_count == 4
        assert snapshots[0].child_count == 12
        assert snapshots[0].total_memory_mb == 2048.5
        assert snapshots[0].cpu_percent == 25.3
        assert snapshots[0].timestamp == datetime(2026, 4, 1, 20, 15, 30)
    finally:
        log_path.unlink()


def test_parse_diagnostics_log_multiple_snapshots():
    """Test parsing a log file with multiple snapshots."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        f.write("[2026-04-01 20:15:00] PROCESS_SNAPSHOT copilot_count=2 child_count=6 total_memory_mb=1024.0 cpu_percent=10.0\n")
        f.write("[2026-04-01 20:16:00] PROCESS_SNAPSHOT copilot_count=4 child_count=12 total_memory_mb=2048.5 cpu_percent=25.5\n")
        f.write("[2026-04-01 20:17:00] PROCESS_SNAPSHOT copilot_count=8 child_count=24 total_memory_mb=4096.2 cpu_percent=50.0\n")
        log_path = Path(f.name)

    try:
        snapshots = parse_diagnostics_log(log_path)
        assert len(snapshots) == 3
        assert snapshots[0].copilot_count == 2
        assert snapshots[1].copilot_count == 4
        assert snapshots[2].copilot_count == 8
        assert snapshots[0].cpu_percent == 10.0
        assert snapshots[2].cpu_percent == 50.0
    finally:
        log_path.unlink()


def test_parse_diagnostics_log_with_limit():
    """Test parsing with a limit on number of snapshots returned."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        for i in range(10):
            f.write(f"[2026-04-01 20:{i:02d}:00] PROCESS_SNAPSHOT copilot_count={i} child_count={i*3} total_memory_mb={i*100.0} cpu_percent={i*5.0}\n")
        log_path = Path(f.name)

    try:
        snapshots = parse_diagnostics_log(log_path, limit=5)
        assert len(snapshots) == 5
        # Should get the last 5 snapshots
        assert snapshots[0].copilot_count == 5
        assert snapshots[4].copilot_count == 9
    finally:
        log_path.unlink()


def test_parse_diagnostics_log_mixed_content():
    """Test parsing a log file with mixed content (snapshots and other log entries)."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        f.write("[2026-04-01 20:15:00] SNAPSHOT tool_id=123 tool=copilot elapsed=45s\n")
        f.write("  args: some arguments here\n")
        f.write("[2026-04-01 20:15:30] PROCESS_SNAPSHOT copilot_count=4 child_count=12 total_memory_mb=2048.5 cpu_percent=30.0\n")
        f.write("Some other log entry\n")
        f.write("[2026-04-01 20:16:00] PROCESS_SNAPSHOT copilot_count=6 child_count=18 total_memory_mb=3072.0 cpu_percent=45.5\n")
        log_path = Path(f.name)

    try:
        snapshots = parse_diagnostics_log(log_path)
        assert len(snapshots) == 2
        assert snapshots[0].copilot_count == 4
        assert snapshots[1].copilot_count == 6
        assert snapshots[0].cpu_percent == 30.0
        assert snapshots[1].cpu_percent == 45.5
    finally:
        log_path.unlink()


def test_parse_diagnostics_log_malformed_entries():
    """Test parsing with malformed entries (should skip them gracefully)."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        f.write("[2026-04-01 20:15:00] PROCESS_SNAPSHOT copilot_count=4 child_count=12 total_memory_mb=2048.5 cpu_percent=25.0\n")
        f.write("[2026-04-01 20:16:00] PROCESS_SNAPSHOT copilot_count=invalid child_count=18 total_memory_mb=3072.0 cpu_percent=30.0\n")
        f.write("[2026-04-01 20:17:00] PROCESS_SNAPSHOT copilot_count=8 child_count=24 total_memory_mb=4096.2 cpu_percent=50.0\n")
        log_path = Path(f.name)

    try:
        snapshots = parse_diagnostics_log(log_path)
        # Should skip the malformed entry
        assert len(snapshots) == 2
        assert snapshots[0].copilot_count == 4
        assert snapshots[1].copilot_count == 8
    finally:
        log_path.unlink()


def test_process_snapshot_to_dict():
    """Test ProcessSnapshot to_dict method."""
    snapshot = ProcessSnapshot(
        timestamp=datetime(2026, 4, 1, 20, 15, 30),
        copilot_count=4,
        child_count=12,
        total_memory_mb=2048.5,
        cpu_percent=25.3,
    )

    result = snapshot.to_dict()
    assert result['timestamp'] == '2026-04-01T20:15:30'
    assert result['copilot_count'] == 4
    assert result['child_count'] == 12
    assert result['total_memory_mb'] == 2048.5
    assert result['cpu_percent'] == 25.3


def test_get_latest_diagnostics_nonexistent_dir():
    """Test get_latest_diagnostics with a directory that doesn't exist."""
    run_dir = Path("/nonexistent/run_dir")
    snapshots = get_latest_diagnostics(run_dir)
    assert snapshots == []


def test_get_latest_diagnostics():
    """Test get_latest_diagnostics with a real log file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        log_path = run_dir / "tool_diagnostics.log"

        with open(log_path, 'w') as f:
            f.write("[2026-04-01 20:15:00] PROCESS_SNAPSHOT copilot_count=2 child_count=6 total_memory_mb=1024.0 cpu_percent=15.0\n")
            f.write("[2026-04-01 20:16:00] PROCESS_SNAPSHOT copilot_count=4 child_count=12 total_memory_mb=2048.5 cpu_percent=30.0\n")

        snapshots = get_latest_diagnostics(run_dir, limit=10)
        assert len(snapshots) == 2
        assert snapshots[0].copilot_count == 2
        assert snapshots[1].copilot_count == 4
        assert snapshots[0].cpu_percent == 15.0
        assert snapshots[1].cpu_percent == 30.0


def test_parse_diagnostics_log_legacy_format_without_cpu():
    """Test backward compatibility with old log format missing cpu_percent."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log') as f:
        f.write("[2026-04-01 20:15:00] PROCESS_SNAPSHOT copilot_count=4 child_count=12 total_memory_mb=2048.5\n")
        log_path = Path(f.name)

    try:
        snapshots = parse_diagnostics_log(log_path)
        assert len(snapshots) == 1
        assert snapshots[0].copilot_count == 4
        assert snapshots[0].cpu_percent == 0.0  # Defaults to 0 for legacy entries
    finally:
        log_path.unlink()
