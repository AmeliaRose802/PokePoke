"""Agent statistics parsing and display utilities."""

import json
import logging
import os
import re
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from pokepoke.agent_types import iter_agent_types
from pokepoke.file_utils import replace_with_retry
from pokepoke.types import AgentStats, MergeQueueStats, SessionStats, ModelCompletionRecord


def parse_agent_stats(output: str) -> AgentStats | None:
    """Parse agent statistics from copilot CLI output.

    Args:
        output: The output text from copilot CLI

    Returns:
        AgentStats object with parsed values, or None if no stats found
    """
    if not output:
        return None

    stats = AgentStats()
    found_any = False  # Track if we found at least one stat

    try:
        # Parse durations
        if match := re.search(r'Total duration \(wall\):\s*([\d.]+)s', output):
            stats.wall_duration = float(match.group(1))
            found_any = True
        if match := re.search(r'Total duration \(API\):\s*([\d.]+)s', output):
            stats.api_duration = float(match.group(1))
            found_any = True

        # Parse code changes
        if match := re.search(r'Total code changes:\s*(\d+) lines added,\s*(\d+) lines removed', output):
            stats.lines_added = int(match.group(1))
            stats.lines_removed = int(match.group(2))
            found_any = True

        # Parse tokens - look for input and output
        if match := re.search(r'(\d+\.?\d*)k?\s+input', output, re.IGNORECASE):
            value = match.group(1).replace('k', '')
            stats.input_tokens = int(float(value) * 1000 if 'k' in match.group(0).lower() else float(value))
            found_any = True
        if match := re.search(r'(\d+\.?\d*)k?\s+output', output, re.IGNORECASE):
            value = match.group(1).replace('k', '')
            stats.output_tokens = int(float(value) * 1000 if 'k' in match.group(0).lower() else float(value))
            found_any = True

        # Parse premium requests
        if (match := re.search(r'Est\.\s*(\d+)\s+Premium request', output, re.IGNORECASE)) or \
           (match := re.search(r'Total usage est:\s*(\d+)\s+Premium request', output, re.IGNORECASE)):
            stats.premium_requests = int(match.group(1))
            found_any = True

        # Only return stats if we found at least one value
        if not found_any:
            logger.warning(
                "No agent statistics found in copilot output (output length=%d). "
                "The CLI output format may not match expected patterns. "
                "Output preview: %.200s",
                len(output),
                output,
            )
            return None
        return stats
    except (ValueError, AttributeError) as e:
        logger.warning("Failed to parse agent stats: %s", e, exc_info=True)
        return None


def print_stats(items_completed: int, total_requests: int, elapsed_seconds: float, session_stats: SessionStats | None = None) -> None:
    """Print session statistics in a formatted way.

    Args:
        items_completed: Number of work items completed
        total_requests: Total number of Copilot CLI requests (including retries)
        elapsed_seconds: Total elapsed time in seconds
        session_stats: Session statistics including agent stats, run counts, and beads stats
    """
    print("\n" + "=" * 60)
    print("📊 Session Statistics")
    print("=" * 60)
    print(f"✅ Items completed:     {items_completed}")
    if session_stats:
        print(f"➕ Items created:       {session_stats.items_created}")
        print(f"📈 Net delta:           {session_stats.items_created - items_completed:+d}")
    print(f"🔄 Total API requests:  {total_requests}")

    print(f"⏱️  Total time:         {_format_duration(elapsed_seconds)}")

    if session_stats:
        _print_beads_stats(session_stats)
        _print_agent_run_counts(session_stats)
        _print_agent_usage_stats(session_stats)
    else:
        print("\n⚠️  No agent statistics available (stats parsing may have failed)")

    if items_completed > 0:
        print(f"📈 Avg time per item:  {_format_duration(elapsed_seconds / items_completed)}")

    if session_stats and session_stats.completed_items_list:
        print("\n" + "=" * 60)
        print("✅ Completed Work Items")
        print("=" * 60)
        for item in session_stats.completed_items_list:
            print(f"• {item.id}: {item.title}")

    if session_stats and session_stats.model_completions:
        _print_model_comparison(session_stats.model_completions)

    from pokepoke.model_stats_store import print_model_leaderboard
    print_model_leaderboard()

    mqs = getattr(session_stats, 'merge_queue_stats', None) if session_stats else None
    if isinstance(mqs, MergeQueueStats) and mqs.total_merges > 0:
        _print_merge_queue_stats(mqs)

    print("=" * 60)


def _print_beads_stats(session_stats: SessionStats) -> None:
    """Print beads database statistics if available."""
    if not (session_stats.starting_beads_stats and session_stats.ending_beads_stats):
        return
    start = session_stats.starting_beads_stats
    end = session_stats.ending_beads_stats
    print("\n" + "=" * 60)
    print("📋 Beads Database Statistics")
    print("=" * 60)
    print("                      Start → End (Change)")
    print(f"📝 Total issues:      {start.total_issues:5} → {end.total_issues:5} ({end.total_issues - start.total_issues:+d})")
    print(f"🔓 Open issues:       {start.open_issues:5} → {end.open_issues:5} ({end.open_issues - start.open_issues:+d})")
    print(f"🏃 In progress:       {start.in_progress_issues:5} → {end.in_progress_issues:5} ({end.in_progress_issues - start.in_progress_issues:+d})")
    print(f"✅ Closed issues:     {start.closed_issues:5} → {end.closed_issues:5} ({end.closed_issues - start.closed_issues:+d})")
    print(f"🚀 Ready to work:     {start.ready_issues:5} → {end.ready_issues:5} ({end.ready_issues - start.ready_issues:+d})")


def _print_agent_run_counts(session_stats: SessionStats) -> None:
    """Print per-agent run counts."""
    print("\n" + "=" * 60)
    print("🤖 Agent Run Counts")
    print("=" * 60)
    for agent in iter_agent_types():
        count = session_stats.get_agent_run_count(agent.key)
        if count <= 0 and not agent.always_show:
            continue
        emoji = f"{agent.emoji} " if agent.emoji else ""
        print(f"{emoji}{agent.display_name} agents:".ljust(28) + f"{count}")


def _print_agent_usage_stats(session_stats: SessionStats) -> None:
    """Print agent usage statistics (tokens, durations, etc)."""
    astats = session_stats.agent_stats
    has_stats = astats and (
        astats.wall_duration > 0 or astats.input_tokens > 0 or
        astats.output_tokens > 0 or astats.lines_added > 0 or
        astats.lines_removed > 0 or astats.premium_requests > 0
    )
    if not has_stats:
        print("\n⚠️  No agent statistics available (stats parsing may have failed)")
        return

    print("\n" + "=" * 60)
    print("🤖 Agent Usage Statistics")
    print("=" * 60)
    if astats.wall_duration > 0:
        print(f"⏱️  Wall duration:      {astats.wall_duration:.1f}s")
    if astats.api_duration > 0:
        print(f"⚡ API duration:       {astats.api_duration:.1f}s")
    if astats.input_tokens > 0:
        print(f"📊 Input tokens:       {astats.input_tokens:,}")
    if astats.output_tokens > 0:
        print(f"📤 Output tokens:      {astats.output_tokens:,}")
    if astats.lines_added > 0:
        print(f"➕ Lines added:        {astats.lines_added:,}")
    if astats.lines_removed > 0:
        print(f"➖ Lines removed:      {astats.lines_removed:,}")
    if astats.premium_requests > 0:
        print(f"💎 Premium requests:   {astats.premium_requests}")


def _format_duration(seconds: float) -> str:
    """Format a duration in seconds to a human-readable string."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _print_model_comparison(completions: list[ModelCompletionRecord]) -> None:
    """Print per-model comparison statistics for A/B testing.

    Groups completions by model and displays:
    - Number of items processed
    - Average, min, max completion time
    - Gate pass rate (passed / total with gate results)

    Args:
        completions: List of ModelCompletionRecord from the session.
    """
    # Group by model
    by_model: dict[str, list[ModelCompletionRecord]] = {}
    for rec in completions:
        by_model.setdefault(rec.model, []).append(rec)

    if len(by_model) < 1:
        return

    print("\n" + "=" * 60)
    print("🔬 Model Comparison (A/B Testing)")
    print("=" * 60)

    for model_name, records in sorted(by_model.items()):
        durations = [r.duration_seconds for r in records]
        avg_dur = sum(durations) / len(durations)
        min_dur = min(durations)
        max_dur = max(durations)

        # Gate pass/reject stats (only for records where gate ran)
        gate_records = [r for r in records if r.gate_passed is not None]
        gate_passed = sum(1 for r in gate_records if r.gate_passed)
        gate_total = len(gate_records)

        print(f"\n  🤖 {model_name}")
        print(f"     Items processed:  {len(records)}")
        print(f"     Avg time:         {_format_duration(avg_dur)}")
        print(f"     Min/Max time:     {_format_duration(min_dur)} / {_format_duration(max_dur)}")

        if gate_total > 0:
            pass_pct = (gate_passed / gate_total) * 100
            print(f"     Gate pass rate:   {pass_pct:.0f}% ({gate_passed}/{gate_total})")
        else:
            print("     Gate pass rate:   N/A (no gate runs)")


def _print_merge_queue_stats(mqs: MergeQueueStats) -> None:
    """Print merge queue performance metrics section."""
    print("\n" + "=" * 60)
    print("🔀 Merge Queue Performance")
    print("=" * 60)
    print(f"📦 Total merges:       {mqs.total_merges}")
    print(f"✅ Successful:         {mqs.successful_merges}")
    print(f"❌ Failed:             {mqs.failed_merges}")
    if mqs.total_rebases > 0:
        rate_pct = mqs.rebase_success_rate * 100
        print(f"🔄 Rebases:            {mqs.successful_rebases}/{mqs.total_rebases} succeeded ({rate_pct:.0f}%)")
    if mqs.high_conflict_merges > 0:
        print(f"⚠️  High-conflict:     {mqs.high_conflict_merges}")
        if mqs.double_rebase_overhead_seconds:
            print(f"   Double-rebase avg:  {_format_duration(mqs.avg_double_rebase_overhead)}")
    if mqs.merge_durations:
        print(f"⏱️  Merge duration avg: {_format_duration(mqs.avg_merge_duration)}")
        print(f"   Merge duration max: {_format_duration(mqs.max_merge_duration)}")
    if mqs.wait_times:
        print(f"⏳ Queue wait avg:     {_format_duration(mqs.avg_wait_time)}")
        print(f"   Queue wait max:     {_format_duration(mqs.max_wait_time)}")
    if mqs.queue_depth_samples:
        print(f"📊 Max queue depth:    {mqs.max_queue_depth}")
        print(f"   Avg queue depth:    {mqs.avg_queue_depth:.1f}")


def serialize_session_stats(
    session_stats: SessionStats,
    elapsed_seconds: float,
    items_completed: int,
    total_requests: int,
) -> dict[str, Any]:
    """Serialize SessionStats into a JSON-compatible dictionary.

    Includes all agent stats, run counts, beads deltas, model completions,
    and summary timing information so that no data is lost if the terminal
    scrollback is cleared or the session crashes.

    Args:
        session_stats: The session statistics to serialize.
        elapsed_seconds: Total elapsed wall-clock time for the session.
        items_completed: Number of items completed in this session.
        total_requests: Total number of Copilot CLI requests.

    Returns:
        A plain dict suitable for ``json.dumps``.
    """
    run_counts = {
        f"{agent.key}_agent": session_stats.get_agent_run_count(agent.key)
        for agent in iter_agent_types()
    }

    data: dict[str, Any] = {
        "items_completed": items_completed,
        "items_created": session_stats.items_created,
        "net_items_delta": session_stats.items_created - items_completed,
        "total_requests": total_requests,
        "elapsed_seconds": round(elapsed_seconds, 2),
        "agent_stats": asdict(session_stats.agent_stats),
        "run_counts": {
            **run_counts,
            "janitor_lines_removed": session_stats.janitor_lines_removed,
        },
        "created_counts_by_agent_type": dict(session_stats.created_counts_by_agent_type),
        "completed_counts_by_agent_type": dict(session_stats.completed_counts_by_agent_type),
        "lifetime_items_created": session_stats.lifetime_items_created,
        "lifetime_items_completed": session_stats.lifetime_items_completed,
        "completed_items": [
            {"id": item.id, "title": item.title}
            for item in session_stats.completed_items_list
        ],
        "created_items": [
            {"id": item.id, "title": item.title, "agent_type": item.agent_type}
            for item in session_stats.created_items_list
        ],
        "model_completions": [asdict(mc) for mc in session_stats.model_completions],
    }

    # Beads deltas
    if session_stats.starting_beads_stats:
        data["beads_start"] = asdict(session_stats.starting_beads_stats)
    if session_stats.ending_beads_stats:
        data["beads_end"] = asdict(session_stats.ending_beads_stats)
    if session_stats.starting_beads_stats and session_stats.ending_beads_stats:
        start = session_stats.starting_beads_stats
        end = session_stats.ending_beads_stats
        data["beads_delta"] = {
            "total_issues": end.total_issues - start.total_issues,
            "open_issues": end.open_issues - start.open_issues,
            "in_progress_issues": end.in_progress_issues - start.in_progress_issues,
            "closed_issues": end.closed_issues - start.closed_issues,
            "ready_issues": end.ready_issues - start.ready_issues,
        }

    # Merge queue performance
    mqs = getattr(session_stats, 'merge_queue_stats', None)
    if isinstance(mqs, MergeQueueStats) and mqs.total_merges > 0:
        data["merge_queue"] = mqs.to_summary_dict()

    return data


def save_session_stats_to_disk(
    run_dir: Path,
    session_stats: SessionStats,
    elapsed_seconds: float,
    items_completed: int,
    total_requests: int,
) -> Path:
    """Persist session statistics as ``stats.json`` in the run log directory.

    Args:
        run_dir: The run-specific log directory (e.g. ``.pokepoke/logs/<run-id>/``).
        session_stats: The session statistics to persist.
        elapsed_seconds: Total elapsed wall-clock time for the session.
        items_completed: Number of items completed in this session.
        total_requests: Total number of Copilot CLI requests.

    Returns:
        Path to the written ``stats.json`` file.
    """
    data = serialize_session_stats(
        session_stats, elapsed_seconds, items_completed, total_requests
    )
    stats_path = run_dir / "stats.json"
    tmp_path = stats_path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        with suppress(OSError):
            os.fsync(f.fileno())
    # Retry os.replace on Windows where the destination file may be briefly
    # locked by a previous operation, causing PermissionError.
    replace_with_retry(tmp_path, stats_path)
    return stats_path
