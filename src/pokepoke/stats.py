"""Agent statistics parsing and display utilities."""

import re
from typing import Optional

from pokepoke.types import AgentStats


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


def print_stats(items_completed: int, total_requests: int, elapsed_seconds: float, session_stats: Optional[AgentStats] = None) -> None:
    """Print session statistics in a formatted way.
    
    Args:
        items_completed: Number of work items completed
        total_requests: Total number of Copilot CLI requests (including retries)
        elapsed_seconds: Total elapsed time in seconds
        session_stats: Aggregated statistics from all agents
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
    
    # Print agent statistics if available and has non-zero values
    if session_stats and (
        session_stats.wall_duration > 0 or
        session_stats.input_tokens > 0 or
        session_stats.output_tokens > 0 or
        session_stats.lines_added > 0 or
        session_stats.lines_removed > 0 or
        session_stats.premium_requests > 0
    ):
        print("\n" + "=" * 60)
        print("🤖 Agent Usage Statistics")
        print("=" * 60)
        if session_stats.wall_duration > 0:
            print(f"⏱️  Wall duration:      {session_stats.wall_duration:.1f}s")
        if session_stats.api_duration > 0:
            print(f"⚡ API duration:       {session_stats.api_duration:.1f}s")
        if session_stats.input_tokens > 0:
            print(f"📊 Input tokens:       {session_stats.input_tokens:,}")
        if session_stats.output_tokens > 0:
            print(f"📤 Output tokens:      {session_stats.output_tokens:,}")
        if session_stats.lines_added > 0:
            print(f"➕ Lines added:        {session_stats.lines_added:,}")
        if session_stats.lines_removed > 0:
            print(f"➖ Lines removed:      {session_stats.lines_removed:,}")
        if session_stats.premium_requests > 0:
            print(f"💎 Premium requests:   {session_stats.premium_requests}")
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
