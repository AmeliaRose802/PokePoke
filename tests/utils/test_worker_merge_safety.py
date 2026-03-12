"""Tests to ensure worker prompts do not instruct merging and the SDK confines workers.

Workers must only commit in their worktree branch; the orchestrator owns all merging.
These tests guard against regression of the merge-lock bypass bug (PokePoke-tq9z).
"""

import re
from pathlib import Path

import pytest

from pokepoke.copilot_sdk import _build_worker_env
from pokepoke.prompts import PromptService


# ── Worker prompt templates that must NEVER instruct merging ──────────────


# These are the prompts used for work-agent sessions (not cleanup/maintenance agents
# that legitimately need merge access from the main repo).
WORKER_TEMPLATES = ("work-item", "beads-item", "work-item-retry", "cleanup")

# Phrases that indicate a prompt tells the worker to initiate a merge.
FORBIDDEN_MERGE_PHRASES = [
    "merge your worktree",
    "git checkout master",
    "git checkout main",
    "merge the worktree back",
    "return to main repo, and merge",
]


def _strip_prohibition_lines(content: str) -> str:
    """Remove lines that are clearly prohibitions (❌, NEVER, must NOT, do NOT) so
    that the phrase-based test only catches *instructions* to merge."""
    result = []
    for line in content.splitlines():
        lower = line.lower().strip()
        # Skip lines that are prohibition bullets or negative directives
        if lower.startswith(("- ❌", "❌", "- **never", "**never")):
            continue
        # Skip lines that are exception/clarification clauses for --abort
        if "exception:" in lower or "git merge --abort" in lower:
            continue
        result.append(line)
    return "\n".join(result)


class TestWorkerPromptsDoNotInstructMerging:
    """Ensure worker prompts explicitly forbid merging and don't instruct it."""

    @pytest.fixture()
    def prompt_service(self) -> PromptService:
        return PromptService()

    @pytest.mark.parametrize("template_name", WORKER_TEMPLATES)
    def test_no_merge_instructions(self, prompt_service: PromptService, template_name: str) -> None:
        """Worker prompt must not contain phrases that positively instruct merging.

        Prohibition lines (❌ NEVER do X) are excluded since they tell the worker
        what NOT to do, which is correct behavior.
        """
        raw = prompt_service.load_prompt(template_name)
        content = _strip_prohibition_lines(raw).lower()
        for phrase in FORBIDDEN_MERGE_PHRASES:
            assert phrase.lower() not in content, (
                f"Worker prompt '{template_name}' contains forbidden merge instruction: '{phrase}'"
            )

    @pytest.mark.parametrize("template_name", WORKER_TEMPLATES)
    def test_no_initiate_git_merge(self, prompt_service: PromptService, template_name: str) -> None:
        """Worker prompt must not instruct running 'git merge <branch>'.

        Note: 'git merge --abort' is allowed for cleanup agents resolving
        existing broken merge states (the orchestrator started the merge).
        Prohibition lines listing things NOT to do are also excluded.
        """
        raw = prompt_service.load_prompt(template_name)
        content = _strip_prohibition_lines(raw)
        # Match 'git merge' followed by a branch-like name (not --abort)
        initiate_pattern = re.compile(r'git merge\s+(?!--abort)[a-zA-Z<]', re.IGNORECASE)
        matches = initiate_pattern.findall(content)
        assert not matches, (
            f"Worker prompt '{template_name}' instructs initiating 'git merge': {matches}"
        )

    @pytest.mark.parametrize("template_name", WORKER_TEMPLATES)
    def test_contains_merge_prohibition(self, prompt_service: PromptService, template_name: str) -> None:
        """Worker prompt must contain an explicit prohibition against merging."""
        content = prompt_service.load_prompt(template_name).lower()
        has_prohibition = (
            "do not merge" in content
            or "do not initiate" in content
            or ("never" in content and "merge" in content)
        )
        assert has_prohibition, (
            f"Worker prompt '{template_name}' lacks explicit merge prohibition"
        )


# ── SDK environment guard tests ──────────────────────────────────────────


class TestBuildWorkerEnv:
    """Tests for _build_worker_env which confines workers to their worktree."""

    def test_sets_git_ceiling_when_cwd_provided(self, tmp_path: Path) -> None:
        """GIT_CEILING_DIRECTORIES must be set to the worktree's parent."""
        worktree = tmp_path / "worktrees" / "task-abc"
        worktree.mkdir(parents=True)
        env = _build_worker_env(str(worktree))
        assert env["GIT_CEILING_DIRECTORIES"] == str(worktree.parent)

    def test_no_ceiling_when_no_cwd(self) -> None:
        """When cwd is None, GIT_CEILING_DIRECTORIES should not be set."""
        env = _build_worker_env(None)
        # The env is a copy of os.environ; GIT_CEILING_DIRECTORIES should only
        # appear if it was already set in the real environment.
        import os
        if "GIT_CEILING_DIRECTORIES" not in os.environ:
            assert "GIT_CEILING_DIRECTORIES" not in env

    def test_preserves_pythonioencoding(self, tmp_path: Path) -> None:
        """PYTHONIOENCODING must always be set for UTF-8 safety."""
        env = _build_worker_env(str(tmp_path))
        assert env["PYTHONIOENCODING"] == "utf-8:replace"

    def test_inherits_os_environ(self) -> None:
        """Worker env must include the host environment variables."""
        import os
        env = _build_worker_env(None)
        # PATH should always exist in os.environ and be inherited
        if "PATH" in os.environ:
            assert "PATH" in env
