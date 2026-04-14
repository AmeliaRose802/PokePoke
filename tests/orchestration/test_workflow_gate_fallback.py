"""Tests for gate agent verdict fallback logic.

Tests the fallback mechanism when gate agent verdicts are unclear or corrupted.
Bug fix for PokePoke-p8tia.
"""

from unittest.mock import patch

from pokepoke.orchestration.workflow import process_work_item
from pokepoke.types_agent import CopilotResult, GateAgentResult
from tests.orchestration.conftest import (
    PATCH_WF_ADD_COMMENT,
    make_process_item_mocks,
    make_work_item,
)


class TestGateVerdictFallback:
    """Tests for gate verdict parsing fallback to worktree validation."""

    def test_gate_verdict_parse_failure_fallback_with_valid_commits(self) -> None:
        """Test that unclear gate verdicts trigger fallback when worktree has valid commits.

        When the gate agent output cannot be parsed (e.g., ProcessMonitor corruption),
        but the worktree has valid commits that passed pre-commit hooks, the orchestrator
        should accept the work via fallback instead of treating it as a rejection.

        Bug fix for PokePoke-p8tia: prevents false rejections when gate verdict JSON
        is corrupted but work is actually valid.
        """
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_handoff=True, include_cleanup_worktree=True,
            commits_ahead=1,  # Worktree has valid commits
        ) as mocks:
            # Gate agent returns unclear verdict (parse failure)
            mocks['gate'].return_value = GateAgentResult(
                success=False,
                reason="Gate Agent verdict could not be parsed (output corrupted). Check logs.",
                crashed=False,  # Not marked as infrastructure crash
            )

            # Mock worktree_branch_has_commits to return True (worktree has valid commits)
            with patch('pokepoke.beads.reconciliation.worktree_branch_has_commits', return_value=True), \
                 patch(PATCH_WF_ADD_COMMENT) as mock_add_comment:
                result = process_work_item(item, interactive=True)

                # Should succeed via fallback despite unclear verdict
                assert result.success is True
                assert result.gate_agent_runs == 1

                # Should have added a comment explaining the fallback
                assert mock_add_comment.call_count == 1
                comment_text = mock_add_comment.call_args[0][1]
                assert "Gate Agent verdict unclear" in comment_text
                assert "valid commits" in comment_text
                assert "Accepting via fallback" in comment_text

    def test_gate_verdict_parse_failure_no_commits_rejects(self) -> None:
        """Test that unclear gate verdicts without valid commits are still treated as rejections.

        When the gate agent output cannot be parsed AND the worktree has no commits,
        this is genuinely unclear and should be treated as a rejection (not a fallback accept).
        """
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_handoff=True, include_cleanup_worktree=True,
            commits_ahead=0,  # No commits ahead
        ) as mocks:
            # Gate agent returns unclear verdict (parse failure)
            mocks['gate'].return_value = GateAgentResult(
                success=False,
                reason="Gate Agent did not explicitly approve the fix. Check logs.",
                crashed=False,
            )

            # Mock worktree_branch_has_commits to return False (no valid commits)
            with patch('pokepoke.beads.reconciliation.worktree_branch_has_commits', return_value=False), \
                 patch('pokepoke.beads.beads_management.increment_gate_rejection_count', return_value=1), \
                 patch(PATCH_WF_ADD_COMMENT) as mock_add_comment, \
                 patch('pokepoke.orchestration.workflow.get_config') as mock_config:
                # Configure max gate rejections to allow at least one rejection
                mock_config.return_value.max_gate_rejections_per_item = 3

                # Work agent will be called twice (initial + retry after gate rejection)
                mocks['invoke'].side_effect = [
                    CopilotResult(work_item_id="task-1", success=True, output="Try 1", attempt_count=1),
                    CopilotResult(work_item_id="task-1", success=True, output="Try 2", attempt_count=1),
                ]
                # Gate agent rejects both times
                mocks['gate'].side_effect = [
                    GateAgentResult(
                        success=False,
                        reason="Gate Agent did not explicitly approve the fix. Check logs.",
                        crashed=False,
                    ),
                    GateAgentResult(success=True, reason="Pass"),  # Passes on retry
                ]

                result = process_work_item(item, interactive=True)

                # Should eventually succeed after retry
                assert result.success is True
                assert result.gate_agent_runs == 2
                assert result.request_count == 2

                # Should have added a rejection comment for first gate failure
                assert mock_add_comment.call_count >= 1
