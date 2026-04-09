"""Tests for output_sanitizer — ProcessMonitor line stripping."""

from pokepoke.utils.output_sanitizer import (
    contains_process_monitor_noise,
    strip_process_monitor_lines,
)


class TestStripProcessMonitorLines:
    """Tests for strip_process_monitor_lines."""

    def test_strips_started_monitoring_line(self):
        text = (
            '{\n'
            '  "status": "success",\n'
            '[ProcessMonitor] Started monitoring PID 1234 (python.exe)\n'
            '  "message": "ok"\n'
            '}'
        )
        result = strip_process_monitor_lines(text)
        assert "[ProcessMonitor]" not in result
        assert '"status": "success"' in result
        assert '"message": "ok"' in result

    def test_strips_active_monitoring_line(self):
        text = '[ProcessMonitor] PID 5678 (pytest.exe) active - wrote 2048 bytes\nclean text'
        result = strip_process_monitor_lines(text)
        assert "[ProcessMonitor]" not in result
        assert "clean text" in result

    def test_strips_completed_line(self):
        text = 'before\n[ProcessMonitor] PID 999 (node.exe) completed\nafter'
        result = strip_process_monitor_lines(text)
        assert "[ProcessMonitor]" not in result
        assert "before" in result
        assert "after" in result

    def test_strips_multiple_lines(self):
        text = (
            '{\n'
            '[ProcessMonitor] Started monitoring PID 1 (a.exe)\n'
            '  "status": "success",\n'
            '[ProcessMonitor] PID 1 (a.exe) active - wrote 100 bytes\n'
            '  "message": "All tests pass"\n'
            '[ProcessMonitor] PID 1 (a.exe) completed\n'
            '}'
        )
        result = strip_process_monitor_lines(text)
        assert result.count("[ProcessMonitor]") == 0

    def test_preserves_clean_text(self):
        text = '{"status": "success", "message": "All tests pass"}'
        result = strip_process_monitor_lines(text)
        assert result == text

    def test_handles_empty_string(self):
        assert strip_process_monitor_lines("") == ""

    def test_strips_indented_monitor_line(self):
        text = '  [ProcessMonitor] PID 123 (x.exe) completed\ndata'
        result = strip_process_monitor_lines(text)
        assert "[ProcessMonitor]" not in result
        assert "data" in result


class TestContainsProcessMonitorNoise:
    """Tests for contains_process_monitor_noise."""

    def test_detects_full_line_noise(self):
        text = "some text\n[ProcessMonitor] PID 1234 active\nmore text"
        assert contains_process_monitor_noise(text) is True

    def test_detects_inline_noise(self):
        text = 'value[ProcessMonitor] PID 1 completed'
        assert contains_process_monitor_noise(text) is True

    def test_clean_text_returns_false(self):
        text = "no monitor noise here"
        assert contains_process_monitor_noise(text) is False

    def test_empty_string_returns_false(self):
        assert contains_process_monitor_noise("") is False
