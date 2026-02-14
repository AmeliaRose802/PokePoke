"""Process utilities for SDK client management."""
import os
import subprocess
import time
from typing import Optional


def check_copilot_processes() -> int:
    """Check for running Copilot-related processes on Windows.
    
    Returns the number of processes found.
    """
    if os.name != 'nt':
        return 0
    
    try:
        result = subprocess.run([
            'tasklist', '/FI', 'IMAGENAME eq copilot.exe', '/FO', 'CSV'
        ], capture_output=True, text=True, timeout=5)
        
        # Count lines excluding header
        lines = result.stdout.strip().split('\n')
        return max(0, len(lines) - 1) if len(lines) > 1 else 0
    except Exception:
        return 0  # Assume no processes if check fails


def wait_for_process_cleanup(max_wait: float = 3.0) -> None:
    """Wait for Copilot processes to terminate on Windows.
    
    Args:
        max_wait: Maximum time to wait in seconds
    """
    if os.name != 'nt':
        return
    
    start_time = time.time()
    while time.time() - start_time < max_wait:
        if check_copilot_processes() == 0:
            return  # All processes cleaned up
        time.sleep(0.1)