"""Hung command detection for PokePoke agents.

Detects when a powershell command appears to be hung based on repeated
read_powershell calls with no new output, and provides corrective feedback
to help the agent recover.
"""

import time
from dataclasses import dataclass, field


@dataclass
class ShellReadState:
    """Tracks read_powershell calls for a single shell session."""
    shell_id: str
    read_count: int = 0
    first_read_time: float = field(default_factory=time.time)
    last_read_time: float = field(default_factory=time.time)
    total_wait_seconds: float = 0.0
    last_output_hash: int | None = None
    consecutive_empty_reads: int = 0


class HungCommandDetector:
    """Detects hung commands based on read_powershell call patterns.

    A command is considered hung when:
    1. read_powershell has been called max_retries times with no new output, OR
    2. Total cumulative wait time exceeds cumulative_timeout seconds

    The detector tracks state per shell session and provides corrective
    feedback messages when a hung state is detected.
    """

    def __init__(
        self,
        max_retries: int = 3,
        cumulative_timeout: float = 300.0,
    ):
        """Initialize the detector.

        Args:
            max_retries: Maximum read_powershell calls before considering hung.
            cumulative_timeout: Maximum total wait time in seconds.
        """
        self.max_retries = max_retries
        self.cumulative_timeout = cumulative_timeout
        self._shell_states: dict[str, ShellReadState] = {}

    def record_powershell_start(self, shell_id: str) -> None:
        """Record that a new powershell command was started.

        Resets any existing state for this shell.

        Args:
            shell_id: The shell session ID.
        """
        self._shell_states[shell_id] = ShellReadState(shell_id=shell_id)

    def record_read_powershell(
        self,
        shell_id: str,
        delay: float,
        output: str | None = None,
    ) -> tuple[bool, str | None]:
        """Record a read_powershell call and check if command appears hung.

        Args:
            shell_id: The shell session ID.
            delay: The delay parameter used in the read call.
            output: The output returned from the read (if any).

        Returns:
            Tuple of (is_hung, corrective_message).
            If is_hung is True, corrective_message contains guidance for the agent.
        """
        now = time.time()

        # Get or create state for this shell
        if shell_id not in self._shell_states:
            self._shell_states[shell_id] = ShellReadState(
                shell_id=shell_id,
                first_read_time=now,
            )

        state = self._shell_states[shell_id]
        state.read_count += 1
        state.last_read_time = now
        state.total_wait_seconds += delay

        # Check if output has changed
        output_hash = hash(output) if output else None
        if output_hash == state.last_output_hash or not output or output.strip() == "":
            state.consecutive_empty_reads += 1
        else:
            state.consecutive_empty_reads = 0
        state.last_output_hash = output_hash

        # Check hung conditions
        is_hung = False
        reason = ""

        if state.consecutive_empty_reads >= self.max_retries:
            is_hung = True
            reason = f"No new output after {state.consecutive_empty_reads} consecutive read_powershell calls"
        elif (state.total_wait_seconds >= self.cumulative_timeout
              and state.consecutive_empty_reads > 0):
            # Only flag cumulative timeout when output has stopped changing.
            # If the command is still producing new output (e.g. git commit
            # with pre-commit hooks running tests), it is making progress
            # and should not be flagged as hung.
            is_hung = True
            reason = f"Command has been running for {state.total_wait_seconds:.0f}s (timeout: {self.cumulative_timeout:.0f}s)"

        if is_hung:
            message = self._build_corrective_message(shell_id, state, reason)
            return True, message

        return False, None

    def record_stop_powershell(self, shell_id: str) -> None:
        """Record that a shell was stopped (clears state).

        Args:
            shell_id: The shell session ID.
        """
        self._shell_states.pop(shell_id, None)

    def get_state(self, shell_id: str) -> ShellReadState | None:
        """Get the current state for a shell session.

        Args:
            shell_id: The shell session ID.

        Returns:
            The ShellReadState if tracked, None otherwise.
        """
        return self._shell_states.get(shell_id)

    def _build_corrective_message(
        self,
        shell_id: str,
        state: ShellReadState,
        reason: str,
    ) -> str:
        """Build a corrective feedback message for the agent.

        Args:
            shell_id: The shell session ID.
            state: The current shell read state.
            reason: Why the command was detected as hung.

        Returns:
            A corrective message with guidance for recovery.
        """
        return f"""
⚠️ HUNG COMMAND DETECTED ⚠️

{reason}

Shell ID: {shell_id}
Total read_powershell calls: {state.read_count}
Total wait time: {state.total_wait_seconds:.0f}s

REQUIRED ACTION:
1. Use stop_powershell with shellId="{shell_id}" to kill the hung process
2. Retry the command with a timeout flag, for example:
   - pytest --timeout=300
   - pytest tests/specific_test.py --timeout=300
3. Or run more targeted tests instead of the full test suite

Do NOT continue calling read_powershell on this shell - the command is hung.
"""
