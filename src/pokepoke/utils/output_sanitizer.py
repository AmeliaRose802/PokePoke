"""Utilities for sanitizing raw agent output before parsing.

Removes noise injected by infrastructure components (e.g. ProcessMonitor)
that can corrupt structured output like JSON verdict blocks.
"""

import re

# Matches full lines produced by SubprocessMonitor / ProcessMonitor.
# Examples:
#   [ProcessMonitor] Started monitoring PID 1234 (python.exe)
#   [ProcessMonitor] PID 1234 (python.exe) active - wrote 2048 bytes
#   [ProcessMonitor] PID 1234 (python.exe) completed
_PROCESS_MONITOR_LINE_RE = re.compile(
    r'^\s*\[ProcessMonitor\][^\n]*$', re.MULTILINE,
)


def strip_process_monitor_lines(text: str) -> str:
    """Remove ``[ProcessMonitor]`` lines from *text*.

    These lines are emitted by :class:`SubprocessMonitor` on a background
    thread and can interleave with structured agent output (JSON blocks),
    corrupting it.  Stripping them before ``json.loads()`` prevents
    false parse failures.
    """
    return _PROCESS_MONITOR_LINE_RE.sub('', text)
