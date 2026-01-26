"""Agent statistics parsing and display utilities."""

import re
from typing import Optional

from pokepoke.types import AgentStats, SessionStats


def parse_agent_stats(output: str) -> Optional[AgentStats]:
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
        if match := re.search(r'Est\.\s*(\d+)\s+Premium request', output, re.IGNORECASE):
            stats.premium_requests = int(match.group(1))
            found_any = True
        elif match := re.search(r'Total usage est:\s*(\d+)\s+Premium request', output, re.IGNORECASE):
            stats.premium_requests = int(match.group(1))
            found_any = True
        
        # Only return stats if we found at least one value
        return stats if found_any else None
    except (ValueError, AttributeError) as e:
        print(f"⚠️  Warning: Failed to parse agent stats: {e}")
        return None


def print_stats(items_completed: int, total_requests: int, elapsed_seconds: float, session_stats: Optional[SessionStats] = None) -> None:
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
    print(f"🔄 Total API requests:  {total_requests}")
    
    # Format elapsed time
    hours = int(elapsed_seconds // 3600)
    minutes = int((elapsed_seconds % 3600) // 60)
    seconds = int(elapsed_seconds % 60)
    
    if hours > 0:
        time_str = f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        time_str = f"{minutes}m {seconds}s"
    else:
        time_str = f"{seconds}s"
    
    print(f"⏱️  Total time:         {time_str}")
    
    # Print beads statistics if available
    if session_stats and session_stats.starting_beads_stats and session_stats.ending_beads_stats:
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
    
    # Print agent run counts
    if session_stats:
        print("\n" + "=" * 60)
        print("🤖 Agent Run Counts")
        print("=" * 60)
        print(f"📋 Work agents:         {session_stats.work_agent_runs}")
        if session_stats.cleanup_agent_runs > 0:
            print(f"🧹 Cleanup agents:      {session_stats.cleanup_agent_runs}")
        if session_stats.tech_debt_agent_runs > 0:
            print(f"📊 Tech Debt agents:    {session_stats.tech_debt_agent_runs}")
        if session_stats.janitor_agent_runs > 0:
            print(f"🧹 Janitor agents:      {session_stats.janitor_agent_runs}")
        if session_stats.backlog_cleanup_agent_runs > 0:
            print(f"🗑️  Backlog agents:      {session_stats.backlog_cleanup_agent_runs}")
        if session_stats.beta_tester_agent_runs > 0:
            print(f"🧪 Beta Tester agents:  {session_stats.beta_tester_agent_runs}")
    
    # Print agent statistics if available and has non-zero values
    if session_stats and session_stats.agent_stats and (
        session_stats.agent_stats.wall_duration > 0 or
        session_stats.agent_stats.input_tokens > 0 or
        session_stats.agent_stats.output_tokens > 0 or
        session_stats.agent_stats.lines_added > 0 or
        session_stats.agent_stats.lines_removed > 0 or
        session_stats.agent_stats.premium_requests > 0
    ):
        print("\n" + "=" * 60)
        print("🤖 Agent Usage Statistics")
        print("=" * 60)
        agent = session_stats.agent_stats
        if agent.wall_duration > 0:
            print(f"⏱️  Wall duration:      {agent.wall_duration:.1f}s")
        if agent.api_duration > 0:
            print(f"⚡ API duration:       {agent.api_duration:.1f}s")
        if agent.input_tokens > 0:
            print(f"📊 Input tokens:       {agent.input_tokens:,}")
        if agent.output_tokens > 0:
            print(f"📤 Output tokens:      {agent.output_tokens:,}")
        if agent.lines_added > 0:
            print(f"➕ Lines added:        {agent.lines_added:,}")
        if agent.lines_removed > 0:
            print(f"➖ Lines removed:      {agent.lines_removed:,}")
        if agent.premium_requests > 0:
            print(f"💎 Premium requests:   {agent.premium_requests}")
    else:
        print("\n⚠️  No agent statistics available (stats parsing may have failed)")
    
    # Calculate average time per item if any completed
    if items_completed > 0:
        avg_seconds = elapsed_seconds / items_completed
        avg_minutes = int(avg_seconds // 60)
        avg_secs = int(avg_seconds % 60)
        if avg_minutes > 0:
            avg_str = f"{avg_minutes}m {avg_secs}s"
        else:
            avg_str = f"{avg_secs}s"
        print(f"📈 Avg time per item:  {avg_str}")
    
    print("=" * 60)
