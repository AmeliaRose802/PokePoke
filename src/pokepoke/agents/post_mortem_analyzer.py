"""Post-mortem log analysis - identifies failure patterns in orchestrator runs."""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FailurePattern:
    """A distinct failure pattern identified from logs."""
    pattern_type: str  # e.g., "tool_timeout", "merge_conflict", "gate_rejection"
    description: str
    affected_items: list[str] = field(default_factory=list)
    frequency: int = 0
    severity: str = "P3"  # P0-P3 based on impact
    sample_logs: list[str] = field(default_factory=list)
    suggested_fix: str = ""
    root_cause: str = ""

    def to_beads_dict(self) -> dict[str, Any]:
        """Convert to dictionary suitable for beads item creation."""
        return {
            "title": f"[Post-Mortem] {self.pattern_type}: {self.description}",
            "description": self._format_description(),
            "priority": self._priority_from_severity(),
            "labels": ["post-mortem", "auto-filed", self.pattern_type],
        }

    def _format_description(self) -> str:
        """Format a detailed description for the beads item."""
        lines = [
            f"**Pattern Type:** {self.pattern_type}",
            f"**Frequency:** {self.frequency} occurrence(s)",
            f"**Severity:** {self.severity}",
            "",
            "**Root Cause:**",
            self.root_cause or "(analysis pending)",
            "",
            "**Affected Items:**",
        ]
        lines.extend(f"- {item_id}" for item_id in self.affected_items[:10])
        if len(self.affected_items) > 10:
            lines.append(f"- ...and {len(self.affected_items) - 10} more")

        lines.extend([
            "",
            "**Suggested Fix:**",
            self.suggested_fix or "(requires manual investigation)",
            "",
            "**Sample Log Excerpts:**",
        ])
        for i, log in enumerate(self.sample_logs[:3], 1):  # Limit to 3 samples
            lines.append(f"{i}. {log}")

        return "\n".join(lines)

    def _priority_from_severity(self) -> int:
        """Convert severity to beads priority (0-3)."""
        severity_map = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        return severity_map.get(self.severity, 3)


class LogAnalyzer:
    """Analyzes orchestrator and item logs to identify failure patterns."""

    # Pattern matchers for common failures
    PATTERN_MATCHERS = {
        "tool_timeout": re.compile(r"Tool call timed out|timeout.*tool|TimeoutError", re.IGNORECASE),
        "merge_conflict": re.compile(r"merge conflict|CONFLICT.*content|Failed to merge", re.IGNORECASE),
        "gate_rejection": re.compile(r"Quality gate.*failed|Gate rejection|coverage.*below", re.IGNORECASE),
        "copilot_failure": re.compile(r"Copilot.*failed|SDK.*error|Session.*crashed", re.IGNORECASE),
        "beads_error": re.compile(r"beads.*failed|bd.*error|br.*error", re.IGNORECASE),
        "worktree_error": re.compile(r"worktree.*failed|Failed to create worktree", re.IGNORECASE),
        "build_failure": re.compile(r"build failed|compilation error|pytest.*failed", re.IGNORECASE),
        "circuit_breaker": re.compile(r"circuit breaker.*tripped|consecutive failures", re.IGNORECASE),
    }

    def __init__(self, run_logs_dir: Path, min_pattern_frequency: int = 2):
        """Initialize the analyzer with a run logs directory."""
        self.run_logs_dir = run_logs_dir
        self.min_pattern_frequency = min_pattern_frequency
        self.patterns: list[FailurePattern] = []

    def analyze(self) -> list[FailurePattern]:
        """Analyze logs and return identified failure patterns."""
        logger.info(f"Analyzing logs in {self.run_logs_dir}")

        # Read orchestrator log
        orchestrator_log = self.run_logs_dir / "orchestrator.log"
        if not orchestrator_log.exists():
            logger.warning(f"Orchestrator log not found: {orchestrator_log}")
            return []

        orchestrator_content = orchestrator_log.read_text(encoding="utf-8", errors="replace")

        # Read item logs
        items_dir = self.run_logs_dir / "items"
        item_logs = {}
        if items_dir.exists():
            for item_log in items_dir.glob("*.log"):
                item_id = item_log.stem
                try:
                    item_logs[item_id] = item_log.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    logger.warning(f"Failed to read item log {item_log}: {e}")

        # Analyze patterns
        pattern_occurrences = defaultdict(list)
        pattern_items = defaultdict(set)
        pattern_logs = defaultdict(list)

        # Check orchestrator log for patterns
        for pattern_type, regex in self.PATTERN_MATCHERS.items():
            matches = list(regex.finditer(orchestrator_content))
            for match in matches:
                # Get context around the match (100 chars before and after)
                start = max(0, match.start() - 100)
                end = min(len(orchestrator_content), match.end() + 100)
                context = orchestrator_content[start:end].strip()
                pattern_occurrences[pattern_type].append(match.group())
                pattern_logs[pattern_type].append(context)

        # Check item logs for patterns
        for item_id, content in item_logs.items():
            for pattern_type, regex in self.PATTERN_MATCHERS.items():
                item_match = regex.search(content)
                if item_match:
                    pattern_items[pattern_type].add(item_id)
                    start = max(0, item_match.start() - 100)
                    end = min(len(content), item_match.end() + 100)
                    context = content[start:end].strip()
                    pattern_logs[pattern_type].append(f"[{item_id}] {context}")

        # Create FailurePattern objects for patterns meeting frequency threshold
        patterns = []
        for pattern_type in pattern_occurrences:
            frequency = len(pattern_occurrences[pattern_type]) + len(pattern_items[pattern_type])
            if frequency >= self.min_pattern_frequency:
                pattern = FailurePattern(
                    pattern_type=pattern_type,
                    description=self._generate_description(pattern_type),
                    affected_items=sorted(pattern_items[pattern_type]),
                    frequency=frequency,
                    severity=self._calculate_severity(frequency, len(item_logs)),
                    sample_logs=pattern_logs[pattern_type][:3],  # Keep first 3 samples
                    root_cause=self._infer_root_cause(pattern_type, pattern_logs[pattern_type]),
                    suggested_fix=self._suggest_fix(pattern_type),
                )
                patterns.append(pattern)

        # Sort by severity (P0 first) and frequency (higher first)
        severity_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        patterns.sort(key=lambda p: (severity_order[p.severity], -p.frequency))

        self.patterns = patterns
        return patterns

    def _generate_description(self, pattern_type: str) -> str:
        """Generate a human-readable description for the pattern type."""
        descriptions = {
            "tool_timeout": "Tools timing out during execution",
            "merge_conflict": "Merge conflicts preventing integration",
            "gate_rejection": "Quality gate rejections blocking completion",
            "copilot_failure": "Copilot SDK or session failures",
            "beads_error": "Beads database or CLI errors",
            "worktree_error": "Worktree creation or management failures",
            "build_failure": "Build or test execution failures",
            "circuit_breaker": "Circuit breaker triggered due to consecutive failures",
        }
        return descriptions.get(pattern_type, f"Unclassified pattern: {pattern_type}")

    def _calculate_severity(self, frequency: int, total_items: int) -> str:
        """Calculate severity based on frequency and impact."""
        if total_items == 0:
            return "P3"

        impact_ratio = frequency / max(total_items, 1)

        # High impact: affects > 50% of items or critical pattern type
        if impact_ratio > 0.5:
            return "P0"
        # Medium-high: affects 25-50% of items
        elif impact_ratio > 0.25:
            return "P1"
        # Medium: affects 10-25% or frequent (>5 occurrences)
        elif impact_ratio > 0.1 or frequency > 5:
            return "P2"
        # Low impact
        else:
            return "P3"

    def _infer_root_cause(self, pattern_type: str, sample_logs: list[str]) -> str:
        """Infer root cause from pattern type and sample logs."""
        root_causes = {
            "tool_timeout": "Tool execution exceeding configured timeout limits. May indicate infrastructure issues, long-running operations, or inadequate timeout settings.",
            "merge_conflict": "Conflicting changes between work item branch and main. Often caused by concurrent modifications to same files or stale branches.",
            "gate_rejection": "Code quality or test coverage failing to meet required thresholds. Check specific gate failures in logs.",
            "copilot_failure": "GitHub Copilot CLI or SDK encountering errors. May be session crashes, authentication issues, or model API problems.",
            "beads_error": "Beads database operations failing. Could be lock contention, database corruption, or CLI version mismatch.",
            "worktree_error": "Git worktree operations failing. May be filesystem issues, permission problems, or orphaned worktrees.",
            "build_failure": "Build or test suite failures. Check for dependency issues, environment configuration, or actual code defects.",
            "circuit_breaker": "System experiencing too many consecutive failures and halting to prevent cascading issues. Investigate underlying failure causes.",
        }

        base_cause = root_causes.get(pattern_type, "Unknown root cause - manual analysis required.")

        # Try to extract additional context from logs
        if sample_logs:
            # Look for specific error messages
            error_keywords = ["error", "exception", "failed", "timeout"]
            for log in sample_logs[:2]:  # Check first 2 samples
                for keyword in error_keywords:
                    if keyword.lower() in log.lower():
                        # Extract the line with the error
                        lines = log.split('\n')
                        error_lines = [line.strip() for line in lines if keyword.lower() in line.lower()]
                        if error_lines:
                            base_cause += f"\n\nSample error: {error_lines[0][:200]}"
                            break
                        break

        return base_cause

    def _suggest_fix(self, pattern_type: str) -> str:
        """Suggest potential fixes based on pattern type."""
        suggestions = {
            "tool_timeout": "1. Increase timeout settings in config\n2. Optimize tool performance\n3. Check for infrastructure bottlenecks\n4. Consider splitting long-running operations",
            "merge_conflict": "1. Implement more frequent syncing with main branch\n2. Review and resolve conflicts in affected files\n3. Consider smaller, more focused work items\n4. Add automated conflict detection before merge",
            "gate_rejection": "1. Review failing quality gates (coverage, linting, tests)\n2. Add missing test coverage\n3. Fix code quality issues\n4. Consider adjusting gate thresholds if appropriate",
            "copilot_failure": "1. Check Copilot CLI logs for specific errors\n2. Verify authentication and API connectivity\n3. Update Copilot CLI to latest version\n4. Restart MCP server if applicable\n5. Check for model API rate limiting",
            "beads_error": "1. Verify beads CLI installation and version\n2. Check database integrity with `bd check`\n3. Clear database locks if present\n4. Sync beads state with `bd sync`",
            "worktree_error": "1. Run worktree cleanup agent\n2. Check filesystem permissions and disk space\n3. Remove orphaned worktrees manually\n4. Verify git repository health",
            "build_failure": "1. Check build logs for specific failures\n2. Verify all dependencies are installed\n3. Run tests locally to reproduce\n4. Check for environment-specific issues",
            "circuit_breaker": "1. Address underlying failure patterns first\n2. Review circuit breaker threshold settings\n3. Check system resource availability\n4. Investigate patterns causing consecutive failures",
        }
        return suggestions.get(pattern_type, "Manual investigation required - no automated fix available.")

    def get_summary(self) -> str:
        """Get a summary of identified patterns."""
        if not self.patterns:
            return "No failure patterns identified."

        lines = [
            f"Identified {len(self.patterns)} failure pattern(s):",
            ""
        ]

        for i, pattern in enumerate(self.patterns, 1):
            lines.append(
                f"{i}. [{pattern.severity}] {pattern.pattern_type}: "
                f"{pattern.frequency} occurrence(s), {len(pattern.affected_items)} item(s) affected"
            )

        return "\n".join(lines)
