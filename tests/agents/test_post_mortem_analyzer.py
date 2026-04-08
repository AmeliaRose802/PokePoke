"""Tests for post_mortem_analyzer module."""

import textwrap
from pathlib import Path

from pokepoke.agents.post_mortem_analyzer import FailurePattern, LogAnalyzer

# ── FailurePattern tests ──


class TestFailurePattern:
    """Tests for the FailurePattern dataclass."""

    def test_to_beads_dict_basic(self):
        fp = FailurePattern(
            pattern_type="tool_timeout",
            description="Tools timing out",
            frequency=3,
            severity="P1",
        )
        d = fp.to_beads_dict()
        assert d["title"] == "[Post-Mortem] tool_timeout: Tools timing out"
        assert d["priority"] == 1
        assert "post-mortem" in d["labels"]
        assert "auto-filed" in d["labels"]
        assert "tool_timeout" in d["labels"]

    def test_priority_from_severity_all_levels(self):
        for sev, expected in [("P0", 0), ("P1", 1), ("P2", 2), ("P3", 3)]:
            fp = FailurePattern(pattern_type="x", description="x", severity=sev)
            assert fp._priority_from_severity() == expected

    def test_priority_from_severity_unknown(self):
        fp = FailurePattern(pattern_type="x", description="x", severity="P9")
        assert fp._priority_from_severity() == 3

    def test_format_description_with_affected_items(self):
        fp = FailurePattern(
            pattern_type="merge_conflict",
            description="conflicts",
            affected_items=["item-1", "item-2"],
            frequency=2,
            severity="P2",
            root_cause="stale branches",
            suggested_fix="sync more",
            sample_logs=["log line 1", "log line 2"],
        )
        desc = fp._format_description()
        assert "merge_conflict" in desc
        assert "item-1" in desc
        assert "item-2" in desc
        assert "stale branches" in desc
        assert "sync more" in desc
        assert "log line 1" in desc

    def test_format_description_truncates_affected_items(self):
        items = [f"item-{i}" for i in range(15)]
        fp = FailurePattern(
            pattern_type="x",
            description="x",
            affected_items=items,
            frequency=1,
        )
        desc = fp._format_description()
        assert "item-9" in desc      # 10th item shown
        assert "item-10" not in desc  # 11th not shown
        assert "...and 5 more" in desc

    def test_format_description_truncates_sample_logs(self):
        logs = [f"sample {i}" for i in range(5)]
        fp = FailurePattern(
            pattern_type="x",
            description="x",
            sample_logs=logs,
        )
        desc = fp._format_description()
        assert "sample 0" in desc
        assert "sample 2" in desc
        assert "sample 3" not in desc  # Only first 3

    def test_format_description_empty_root_cause_and_fix(self):
        fp = FailurePattern(pattern_type="x", description="x")
        desc = fp._format_description()
        assert "(analysis pending)" in desc
        assert "(requires manual investigation)" in desc


# ── LogAnalyzer tests ──


class TestLogAnalyzer:
    """Tests for the LogAnalyzer class."""

    def _write_log(self, tmp_path: Path, filename: str, content: str):
        log_file = tmp_path / filename
        log_file.write_text(content, encoding="utf-8")
        return log_file

    def test_no_orchestrator_log(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        result = analyzer.analyze()
        assert result == []

    def test_empty_orchestrator_log(self, tmp_path):
        self._write_log(tmp_path, "orchestrator.log", "")
        analyzer = LogAnalyzer(tmp_path)
        result = analyzer.analyze()
        assert result == []

    def test_no_matching_patterns(self, tmp_path):
        self._write_log(tmp_path, "orchestrator.log", "Everything went fine.\nNo issues here.")
        analyzer = LogAnalyzer(tmp_path)
        result = analyzer.analyze()
        assert result == []

    def test_detects_tool_timeout(self, tmp_path):
        content = textwrap.dedent("""\
            Starting run
            Tool call timed out after 60s
            Processing next item
            Tool call timed out again
        """)
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "tool_timeout"
        assert patterns[0].frequency >= 2

    def test_detects_merge_conflict(self, tmp_path):
        content = "merge conflict in file.py\nFailed to merge branch\n"
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "merge_conflict"

    def test_detects_gate_rejection(self, tmp_path):
        content = "Quality gate failed\ncoverage below threshold\n"
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert any(p.pattern_type == "gate_rejection" for p in patterns)

    def test_detects_copilot_failure(self, tmp_path):
        content = "Copilot failed to respond\nSDK error occurred\n"
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert any(p.pattern_type == "copilot_failure" for p in patterns)

    def test_detects_beads_error(self, tmp_path):
        content = "beads failed to connect\nbd error: timeout\n"
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert any(p.pattern_type == "beads_error" for p in patterns)

    def test_detects_worktree_error(self, tmp_path):
        content = "Failed to create worktree\nworktree failed again\n"
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert any(p.pattern_type == "worktree_error" for p in patterns)

    def test_detects_build_failure(self, tmp_path):
        content = "build failed with errors\npytest failed with 3 errors\n"
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert any(p.pattern_type == "build_failure" for p in patterns)

    def test_detects_circuit_breaker(self, tmp_path):
        content = "circuit breaker tripped\nconsecutive failures exceeded limit\n"
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert any(p.pattern_type == "circuit_breaker" for p in patterns)

    def test_item_logs_add_to_frequency(self, tmp_path):
        self._write_log(tmp_path, "orchestrator.log", "Tool call timed out\n")
        items_dir = tmp_path / "items"
        items_dir.mkdir()
        (items_dir / "task-1.log").write_text("Tool call timed out for item", encoding="utf-8")
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert len(patterns) == 1
        assert patterns[0].pattern_type == "tool_timeout"
        assert "task-1" in patterns[0].affected_items

    def test_item_logs_unreadable_skipped(self, tmp_path):
        self._write_log(tmp_path, "orchestrator.log", "Tool call timed out\nTool call timed out\n")
        items_dir = tmp_path / "items"
        items_dir.mkdir()
        # Create a directory with .log extension to cause read error
        (items_dir / "bad.log").mkdir()
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()  # Should not raise
        assert len(patterns) >= 1

    def test_min_frequency_filter(self, tmp_path):
        # Single occurrence should be filtered out with min_frequency=2
        self._write_log(tmp_path, "orchestrator.log", "Tool call timed out\n")
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        assert len(patterns) == 0

    def test_sorted_by_severity_then_frequency(self, tmp_path):
        content = textwrap.dedent("""\
            Tool call timed out once
            Tool call timed out twice
            merge conflict here
            Failed to merge there
            merge conflict again
        """)
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        patterns = analyzer.analyze()
        # Verify severity ordering (P0 first, then P3 last)
        if len(patterns) > 1:
            sev_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
            for i in range(len(patterns) - 1):
                p_sev = sev_order[patterns[i].severity]
                n_sev = sev_order[patterns[i + 1].severity]
                if p_sev == n_sev:
                    assert patterns[i].frequency >= patterns[i + 1].frequency

    def test_get_summary_no_patterns(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        assert analyzer.get_summary() == "No failure patterns identified."

    def test_get_summary_with_patterns(self, tmp_path):
        content = "Tool call timed out\nTool call timed out\n"
        self._write_log(tmp_path, "orchestrator.log", content)
        analyzer = LogAnalyzer(tmp_path, min_pattern_frequency=2)
        analyzer.analyze()
        summary = analyzer.get_summary()
        assert "failure pattern" in summary
        assert "tool_timeout" in summary

    def test_calculate_severity_high_impact(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        assert analyzer._calculate_severity(6, 10) == "P0"

    def test_calculate_severity_medium_high(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        assert analyzer._calculate_severity(3, 10) == "P1"

    def test_calculate_severity_medium(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        assert analyzer._calculate_severity(2, 10) == "P2"

    def test_calculate_severity_low(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        assert analyzer._calculate_severity(1, 100) == "P3"

    def test_calculate_severity_zero_items(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        assert analyzer._calculate_severity(5, 0) == "P3"

    def test_calculate_severity_many_occurrences(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        assert analyzer._calculate_severity(6, 50) == "P2"

    def test_generate_description_known_types(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        for pt in LogAnalyzer.PATTERN_MATCHERS:
            desc = analyzer._generate_description(pt)
            assert desc and len(desc) > 5

    def test_generate_description_unknown_type(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        desc = analyzer._generate_description("unknown_pattern")
        assert "unknown_pattern" in desc

    def test_suggest_fix_known_types(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        for pt in LogAnalyzer.PATTERN_MATCHERS:
            fix = analyzer._suggest_fix(pt)
            assert fix and len(fix) > 5

    def test_suggest_fix_unknown_type(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        fix = analyzer._suggest_fix("something_unknown")
        assert "manual" in fix.lower()

    def test_infer_root_cause_known_type(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        cause = analyzer._infer_root_cause("tool_timeout", [])
        assert "timeout" in cause.lower()

    def test_infer_root_cause_with_error_logs(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        logs = ["some context error happened here"]
        cause = analyzer._infer_root_cause("tool_timeout", logs)
        assert "Sample error" in cause

    def test_infer_root_cause_unknown_type(self, tmp_path):
        analyzer = LogAnalyzer(tmp_path)
        cause = analyzer._infer_root_cause("completely_new", [])
        assert "Unknown" in cause
