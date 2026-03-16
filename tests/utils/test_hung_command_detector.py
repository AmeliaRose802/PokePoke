"""Tests for hung command detection."""



from pokepoke.utils.hung_command_detector import HungCommandDetector, ShellReadState


class TestShellReadState:
    """Tests for ShellReadState dataclass."""

    def test_default_values(self):
        """Test ShellReadState has sensible defaults."""
        state = ShellReadState(shell_id="test-shell")
        assert state.shell_id == "test-shell"
        assert state.read_count == 0
        assert state.total_wait_seconds == 0.0
        assert state.last_output_hash is None
        assert state.consecutive_empty_reads == 0


class TestHungCommandDetector:
    """Tests for HungCommandDetector."""

    def test_default_settings(self):
        """Test detector initializes with default settings."""
        detector = HungCommandDetector()
        assert detector.max_retries == 3
        assert detector.cumulative_timeout == 300.0

    def test_custom_settings(self):
        """Test detector accepts custom settings."""
        detector = HungCommandDetector(max_retries=5, cumulative_timeout=600.0)
        assert detector.max_retries == 5
        assert detector.cumulative_timeout == 600.0

    def test_record_powershell_start_creates_state(self):
        """Test that starting a powershell creates tracked state."""
        detector = HungCommandDetector()
        detector.record_powershell_start("shell-123")

        state = detector.get_state("shell-123")
        assert state is not None
        assert state.shell_id == "shell-123"
        assert state.read_count == 0

    def test_record_powershell_start_resets_existing(self):
        """Test that starting a powershell resets any existing state."""
        detector = HungCommandDetector()
        detector.record_powershell_start("shell-123")

        # Simulate some reads
        detector.record_read_powershell("shell-123", 30, "")
        detector.record_read_powershell("shell-123", 30, "")

        # Verify reads were recorded
        state = detector.get_state("shell-123")
        assert state is not None
        assert state.read_count == 2

        # Start new command - should reset
        detector.record_powershell_start("shell-123")
        state = detector.get_state("shell-123")
        assert state is not None
        assert state.read_count == 0

    def test_record_read_increments_count(self):
        """Test that read_powershell increments read count."""
        detector = HungCommandDetector()
        detector.record_read_powershell("shell-1", 30, "output")

        state = detector.get_state("shell-1")
        assert state is not None
        assert state.read_count == 1

        detector.record_read_powershell("shell-1", 30, "more output")
        state = detector.get_state("shell-1")
        assert state.read_count == 2

    def test_record_read_tracks_wait_time(self):
        """Test that read_powershell accumulates wait time."""
        detector = HungCommandDetector()
        detector.record_read_powershell("shell-1", 30, "output")
        detector.record_read_powershell("shell-1", 60, "output")
        detector.record_read_powershell("shell-1", 120, "output")

        state = detector.get_state("shell-1")
        assert state is not None
        assert state.total_wait_seconds == 210.0

    def test_not_hung_with_new_output(self):
        """Test that command is not considered hung if output changes."""
        detector = HungCommandDetector(max_retries=3)

        # Each read has different output - should not be hung
        is_hung, msg = detector.record_read_powershell("shell-1", 30, "output 1")
        assert not is_hung
        assert msg is None

        is_hung, msg = detector.record_read_powershell("shell-1", 30, "output 2")
        assert not is_hung

        is_hung, msg = detector.record_read_powershell("shell-1", 30, "output 3")
        assert not is_hung

        is_hung, msg = detector.record_read_powershell("shell-1", 30, "output 4")
        assert not is_hung

    def test_hung_after_max_retries_no_output(self):
        """Test command is hung after max_retries with no new output."""
        detector = HungCommandDetector(max_retries=3, cumulative_timeout=9999)

        # First read - not hung
        is_hung, msg = detector.record_read_powershell("shell-1", 30, "")
        assert not is_hung

        # Second read - not hung
        is_hung, msg = detector.record_read_powershell("shell-1", 30, "")
        assert not is_hung

        # Third read - NOW hung (3 consecutive empty reads)
        is_hung, msg = detector.record_read_powershell("shell-1", 30, "")
        assert is_hung
        assert msg is not None
        assert "HUNG COMMAND DETECTED" in msg
        assert "shell-1" in msg

    def test_hung_after_cumulative_timeout(self):
        """Test command is hung after cumulative timeout exceeded."""
        detector = HungCommandDetector(max_retries=999, cumulative_timeout=100)

        # First read - 60s, not hung
        is_hung, msg = detector.record_read_powershell("shell-1", 60, "output")
        assert not is_hung

        # Second read - 60s more = 120s total, exceeds 100s timeout
        is_hung, msg = detector.record_read_powershell("shell-1", 60, "more output")
        assert is_hung
        assert msg is not None
        assert "HUNG COMMAND DETECTED" in msg
        assert "120s" in msg or "120" in msg

    def test_consecutive_empty_resets_on_new_output(self):
        """Test that consecutive empty count resets when output changes."""
        detector = HungCommandDetector(max_retries=3, cumulative_timeout=9999)

        # Two empty reads
        detector.record_read_powershell("shell-1", 30, "")
        detector.record_read_powershell("shell-1", 30, "")

        state = detector.get_state("shell-1")
        assert state is not None
        assert state.consecutive_empty_reads == 2

        # Now get output - resets counter
        detector.record_read_powershell("shell-1", 30, "actual output")
        state = detector.get_state("shell-1")
        assert state.consecutive_empty_reads == 0

        # Two more empty reads - still not hung
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "")
        assert not is_hung
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "")
        assert not is_hung

        # Third empty - NOW hung
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "")
        assert is_hung

    def test_stop_powershell_clears_state(self):
        """Test that stop_powershell removes tracked state."""
        detector = HungCommandDetector()
        detector.record_powershell_start("shell-1")
        detector.record_read_powershell("shell-1", 30, "")

        assert detector.get_state("shell-1") is not None

        detector.record_stop_powershell("shell-1")
        assert detector.get_state("shell-1") is None

    def test_stop_powershell_unknown_shell_no_error(self):
        """Test that stopping unknown shell doesn't raise error."""
        detector = HungCommandDetector()
        # Should not raise
        detector.record_stop_powershell("nonexistent-shell")

    def test_clear_all(self):
        """Test that clear_all removes all tracked states."""
        detector = HungCommandDetector()
        detector.record_powershell_start("shell-1")
        detector.record_powershell_start("shell-2")
        detector.record_powershell_start("shell-3")

        assert detector.get_state("shell-1") is not None
        assert detector.get_state("shell-2") is not None
        assert detector.get_state("shell-3") is not None

        detector.clear_all()

        assert detector.get_state("shell-1") is None
        assert detector.get_state("shell-2") is None
        assert detector.get_state("shell-3") is None

    def test_corrective_message_contains_shell_id(self):
        """Test that corrective message includes the shell ID."""
        detector = HungCommandDetector(max_retries=1)

        is_hung, msg = detector.record_read_powershell("my-special-shell", 30, "")
        assert is_hung
        assert "my-special-shell" in msg

    def test_corrective_message_contains_stop_instruction(self):
        """Test that corrective message tells agent to use stop_powershell."""
        detector = HungCommandDetector(max_retries=1)

        is_hung, msg = detector.record_read_powershell("shell-123", 30, "")
        assert is_hung
        assert "stop_powershell" in msg
        assert "shell-123" in msg

    def test_corrective_message_suggests_timeout(self):
        """Test that corrective message suggests using timeout flag."""
        detector = HungCommandDetector(max_retries=1)

        is_hung, msg = detector.record_read_powershell("shell-1", 30, "")
        assert is_hung
        assert "--timeout" in msg or "timeout" in msg.lower()

    def test_multiple_shells_tracked_independently(self):
        """Test that multiple shells are tracked independently."""
        detector = HungCommandDetector(max_retries=3, cumulative_timeout=9999)

        # Shell 1: two empty reads
        detector.record_read_powershell("shell-1", 30, "")
        detector.record_read_powershell("shell-1", 30, "")

        # Shell 2: one read with output
        detector.record_read_powershell("shell-2", 30, "output")

        state1 = detector.get_state("shell-1")
        state2 = detector.get_state("shell-2")

        assert state1 is not None
        assert state2 is not None
        assert state1.consecutive_empty_reads == 2
        assert state2.consecutive_empty_reads == 0

    def test_whitespace_only_output_counts_as_empty(self):
        """Test that whitespace-only output is treated as empty."""
        detector = HungCommandDetector(max_retries=2)

        is_hung, _ = detector.record_read_powershell("shell-1", 30, "   ")
        assert not is_hung

        is_hung, _ = detector.record_read_powershell("shell-1", 30, "\n\t\n")
        assert is_hung  # 2 empty reads

    def test_none_output_counts_as_empty(self):
        """Test that None output is treated as empty."""
        detector = HungCommandDetector(max_retries=2)

        is_hung, _ = detector.record_read_powershell("shell-1", 30, None)
        assert not is_hung

        is_hung, _ = detector.record_read_powershell("shell-1", 30, None)
        assert is_hung  # 2 empty reads

    def test_same_output_counts_as_empty(self):
        """Test that repeated identical output counts as empty."""
        detector = HungCommandDetector(max_retries=3)

        # First read with output
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "same output")
        assert not is_hung

        # Second read - same output, counts as empty
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "same output")
        state = detector.get_state("shell-1")
        assert state is not None
        assert state.consecutive_empty_reads == 1

        # Third read - same output again
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "same output")
        assert state.consecutive_empty_reads == 2

        # Fourth read - same output, NOW hung
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "same output")
        assert is_hung


class TestHungCommandDetectorIntegration:
    """Integration-style tests for hung command scenarios."""

    def test_typical_hung_pytest_scenario(self):
        """Test the typical scenario: pytest hangs, agent keeps reading."""
        detector = HungCommandDetector(max_retries=3, cumulative_timeout=600)

        # Agent starts pytest
        detector.record_powershell_start("shell-abc")

        # First read after 60s - some initial output
        is_hung, msg = detector.record_read_powershell(
            "shell-abc", 60, "===== test session starts ====="
        )
        assert not is_hung

        # Second read after 120s - no new output (test hung)
        is_hung, msg = detector.record_read_powershell("shell-abc", 120, "")
        assert not is_hung

        # Third read after 120s - still no output
        is_hung, msg = detector.record_read_powershell("shell-abc", 120, "")
        assert not is_hung

        # Fourth read - hung detected! (3 consecutive empty reads)
        is_hung, msg = detector.record_read_powershell("shell-abc", 120, "")
        assert is_hung
        assert "HUNG COMMAND DETECTED" in msg
        assert "stop_powershell" in msg

    def test_command_completes_before_hung(self):
        """Test that a command completing doesn't trigger hung detection."""
        detector = HungCommandDetector(max_retries=3, cumulative_timeout=300)

        detector.record_powershell_start("shell-1")

        # Initial output
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "Running tests...")
        assert not is_hung

        # One empty read
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "")
        assert not is_hung

        # Tests complete - new output
        is_hung, _ = detector.record_read_powershell("shell-1", 30, "All tests passed!")
        assert not is_hung

        # Shell stops naturally
        detector.record_stop_powershell("shell-1")

        # No state left
        assert detector.get_state("shell-1") is None

    def test_timeout_triggers_before_max_retries(self):
        """Test that timeout can trigger before max retries."""
        detector = HungCommandDetector(max_retries=10, cumulative_timeout=150)

        # Long delays that exceed timeout before retry count
        is_hung, _ = detector.record_read_powershell("shell-1", 60, "output 1")
        assert not is_hung  # 60s total

        is_hung, _ = detector.record_read_powershell("shell-1", 60, "output 2")
        assert not is_hung  # 120s total

        is_hung, msg = detector.record_read_powershell("shell-1", 60, "output 3")
        assert is_hung  # 180s > 150s timeout
        assert "180s" in msg or "180" in msg
