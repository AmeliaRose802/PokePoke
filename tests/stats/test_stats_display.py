"""Tests for orchestrator statistics display functions."""

import builtins
import io
from unittest.mock import patch

from pokepoke.stats.stats import print_stats
from pokepoke.types import AgentStats, SessionStats


def _capture_stdout(fn, *args, **kwargs):
    """Capture print() output robustly, even when builtins.print is mocked."""
    buf = io.StringIO()
    real_print = builtins.print  # snapshot before any mock can replace it

    def _print_to_buf(*a, **kw):
        kw["file"] = buf
        real_print(*a, **kw)

    with patch("builtins.print", side_effect=_print_to_buf):
        fn(*args, **kwargs)
    return buf.getvalue()


def _find_agent_line(output: str, label: str) -> str | None:
    for line in output.splitlines():
        if label in line:
            return line
    return None


def _assert_agent_line(output: str, label: str, expected: int) -> None:
    line = _find_agent_line(output, label)
    assert line is not None, f"{label} missing from output"
    assert line.rstrip().endswith(str(expected)), f"{label} should end with {expected}, got: {line!r}"


def test_print_stats_with_full_stats():
    """Test print_stats displays all statistics when available."""
    stats = SessionStats(
        agent_stats=AgentStats(
            wall_duration=120.5,
            api_duration=90.2,
            input_tokens=15000,
            output_tokens=8000,
            lines_added=150,
            lines_removed=45,
            premium_requests=3
        )
    )

    output = _capture_stdout(print_stats, items_completed=2, total_requests=5, elapsed_seconds=125.0, session_stats=stats)

    # Check session statistics
    assert "📊 Session Statistics" in output
    assert "Items completed:     2" in output
    assert "Total API requests:  5" in output
    assert "Total time:" in output

    # Check agent statistics
    assert "🤖 Agent Usage Statistics" in output
    assert "Wall duration:      120.5s" in output
    assert "API duration:       90.2s" in output
    assert "Input tokens:       15,000" in output
    assert "Output tokens:      8,000" in output
    assert "Lines added:        150" in output
    assert "Lines removed:      45" in output
    assert "Premium requests:   3" in output


def test_print_stats_with_partial_stats():
    """Test print_stats only displays non-zero statistics."""
    stats = SessionStats(
        agent_stats=AgentStats(
            wall_duration=60.0,
            input_tokens=5000,
            output_tokens=2000,
            # All other fields are 0
        )
    )

    output = _capture_stdout(print_stats, items_completed=1, total_requests=2, elapsed_seconds=65.0, session_stats=stats)

    # Check that non-zero stats are shown
    assert "Wall duration:      60.0s" in output
    assert "Input tokens:       5,000" in output
    assert "Output tokens:      2,000" in output

    # Check that zero stats are NOT shown
    assert "Lines added:" not in output
    assert "Lines removed:" not in output
    assert "Premium requests:" not in output


def test_print_stats_with_no_stats():
    """Test print_stats shows warning when no stats available."""
    stats = SessionStats(agent_stats=AgentStats())  # All zeros

    output = _capture_stdout(print_stats, items_completed=1, total_requests=1, elapsed_seconds=30.0, session_stats=stats)

    # Should show session stats
    assert "📊 Session Statistics" in output
    assert "Items completed:     1" in output

    # Should show warning about missing agent stats
    assert "No agent statistics available" in output


def test_print_stats_with_none_stats():
    """Test print_stats handles None stats gracefully."""
    output = _capture_stdout(print_stats, items_completed=1, total_requests=1, elapsed_seconds=30.0, session_stats=None)

    # Should still show session stats
    assert "📊 Session Statistics" in output
    assert "Items completed:     1" in output

    # Should show warning about missing agent stats
    assert "No agent statistics available" in output


def test_print_stats_time_formatting():
    """Test that time is formatted correctly for different durations."""
    # Test hours, minutes, seconds
    output = _capture_stdout(print_stats, items_completed=1, total_requests=1, elapsed_seconds=3661.0, session_stats=None)
    assert "1h 1m 1s" in output

    # Test minutes and seconds only
    output = _capture_stdout(print_stats, items_completed=1, total_requests=1, elapsed_seconds=125.0, session_stats=None)
    assert "2m 5s" in output

    # Test seconds only
    output = _capture_stdout(print_stats, items_completed=1, total_requests=1, elapsed_seconds=45.0, session_stats=None)
    assert "45s" in output


def test_print_stats_average_time():
    """Test that average time per item is calculated and displayed."""
    stats = SessionStats(agent_stats=AgentStats(wall_duration=100.0))

    output = _capture_stdout(print_stats, items_completed=4, total_requests=8, elapsed_seconds=240.0, session_stats=stats)

    assert "Avg time per item:" in output
    assert "1m 0s" in output  # 240s / 4 items = 60s


def test_print_stats_zero_items_no_average():
    """Test that average is not shown when zero items completed."""
    stats = SessionStats(agent_stats=AgentStats(wall_duration=10.0))

    output = _capture_stdout(print_stats, items_completed=0, total_requests=0, elapsed_seconds=10.0, session_stats=stats)

    # Should not show average
    assert "Avg time per item:" not in output


def test_print_stats_with_large_numbers():
    """Test that large numbers are formatted with commas."""
    stats = SessionStats(
        agent_stats=AgentStats(
            input_tokens=1234567,
            output_tokens=987654,
            lines_added=5678,
            lines_removed=1234
        )
    )

    output = _capture_stdout(print_stats, items_completed=1, total_requests=1, elapsed_seconds=60.0, session_stats=stats)

    # Check comma formatting
    assert "1,234,567" in output  # input tokens
    assert "987,654" in output   # output tokens
    assert "5,678" in output      # lines added
    assert "1,234" in output      # lines removed


def test_print_stats_with_beads_statistics():
    """Test beads statistics display."""
    from pokepoke.types import BeadsStats

    stats = SessionStats(
        agent_stats=AgentStats(wall_duration=10.0),
        starting_beads_stats=BeadsStats(
            total_issues=100,
            open_issues=50,
            in_progress_issues=10,
            closed_issues=40,
            ready_issues=20
        ),
        ending_beads_stats=BeadsStats(
            total_issues=102,
            open_issues=48,
            in_progress_issues=12,
            closed_issues=42,
            ready_issues=18
        )
    )

    output = _capture_stdout(print_stats, items_completed=2, total_requests=3, elapsed_seconds=120.0, session_stats=stats)

    # Check beads statistics section
    assert "📋 Beads Database Statistics" in output
    assert "Start → End (Change)" in output
    assert "100 →   102 (+2)" in output  # total issues
    assert "50 →    48 (-2)" in output   # open issues
    assert "10 →    12 (+2)" in output   # in progress
    assert "40 →    42 (+2)" in output   # closed issues
    assert "20 →    18 (-2)" in output   # ready issues


def test_print_stats_with_agent_run_counts():
    """Test display of different agent run counts."""
    stats = SessionStats(
        agent_stats=AgentStats(wall_duration=10.0),
        work_agent_runs=5,
        cleanup_agent_runs=2,
        tech_debt_agent_runs=1,
        janitor_agent_runs=3,
        backlog_cleanup_agent_runs=1
    )

    output = _capture_stdout(print_stats, items_completed=5, total_requests=10, elapsed_seconds=300.0, session_stats=stats)

    # Check agent run counts section
    assert "🤖 Agent Run Counts" in output
    _assert_agent_line(output, "📋 Work agents:", 5)
    _assert_agent_line(output, "🧹 Cleanup agents:", 2)
    _assert_agent_line(output, "📊 Tech Debt agents:", 1)
    _assert_agent_line(output, "🧽 Janitor agents:", 3)
    _assert_agent_line(output, "🗑️ Backlog Cleanup agents:", 1)


def test_print_stats_with_only_work_agent_runs():
    """Test that only work agent runs are shown when other counts are zero."""
    stats = SessionStats(
        agent_stats=AgentStats(wall_duration=10.0),
        work_agent_runs=3,
        cleanup_agent_runs=0,
        tech_debt_agent_runs=0,
        janitor_agent_runs=0,
        backlog_cleanup_agent_runs=0
    )

    output = _capture_stdout(print_stats, items_completed=3, total_requests=5, elapsed_seconds=180.0, session_stats=stats)

    # Check work agents shown
    _assert_agent_line(output, "📋 Work agents:", 3)

    # Check other agents NOT shown (zero counts)
    assert "🚪 Gate agents:" not in output
    assert "🧹 Cleanup agents:" not in output
    assert "📊 Tech Debt agents:" not in output
    assert "🧽 Janitor agents:" not in output
    assert "🗑️ Backlog Cleanup agents:" not in output


def test_print_stats_gate_agent_runs_shown():
    """Test that gate agent runs are displayed when non-zero."""
    stats = SessionStats(
        agent_stats=AgentStats(wall_duration=60.0),
        work_agent_runs=2,
        gate_agent_runs=3
    )

    output = _capture_stdout(print_stats, items_completed=2, total_requests=4, elapsed_seconds=120.0, session_stats=stats)

    _assert_agent_line(output, "📋 Work agents:", 2)
    _assert_agent_line(output, "🚪 Gate agents:", 3)


def test_print_stats_gate_agent_runs_hidden_when_zero():
    """Test that gate agent runs are hidden when zero."""
    stats = SessionStats(
        agent_stats=AgentStats(wall_duration=60.0),
        work_agent_runs=1,
        gate_agent_runs=0
    )

    output = _capture_stdout(print_stats, items_completed=1, total_requests=1, elapsed_seconds=60.0, session_stats=stats)

    _assert_agent_line(output, "📋 Work agents:", 1)
    assert "🚪 Gate agents:" not in output
