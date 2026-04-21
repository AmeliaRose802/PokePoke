"""Tests for decomposition agent integration in workflow.py."""

from unittest.mock import patch

import pytest

from pokepoke.orchestration.workflow import process_work_item
from pokepoke.orchestration.workflow_helpers import _maybe_decompose
from pokepoke.types_agent import CopilotResult, GateAgentResult
from tests.orchestration.conftest import make_process_item_mocks, make_work_item

# Patch targets for decomposition
_WF = "pokepoke.orchestration.workflow"
PATCH_MAYBE_DECOMPOSE = f"{_WF}._maybe_decompose"


def _make_failing_copilot_result(item_id: str = "task-1") -> CopilotResult:
    """Create a CopilotResult that simulates exhausted retries."""
    return CopilotResult(
        work_item_id=item_id,
        success=False,
        error="process died: consecutive ping failures",
        attempt_count=1,
        session_id="pokepoke-" + item_id,
    )


class TestWorkflowDecompositionOnCopilotFailure:
    """Decomposition triggers when Copilot retries are exhausted."""

    def test_decomposition_called_on_exhausted_retries(self) -> None:
        """When copilot_failure_count exceeds max_retries, _maybe_decompose is called."""
        item = make_work_item(item_id="task-fail")

        with make_process_item_mocks(
            copilot_success=False,
            include_config=True,
            include_session_cleanup=True,
            max_copilot_failure_retries=0,
        ) as mocks:
            mocks["invoke"].return_value = _make_failing_copilot_result("task-fail")

            with patch(PATCH_MAYBE_DECOMPOSE) as mock_decompose:
                result = process_work_item(item, interactive=False)

                assert result.success is False
                mock_decompose.assert_called_once()
                call_args = mock_decompose.call_args
                assert call_args[0][0].id == "task-fail"


class TestWorkflowDecompositionOnGateRejection:
    """Decomposition triggers when gate rejection cap is reached."""

    def test_decomposition_called_on_gate_cap(self) -> None:
        """When gate rejections hit the cap, _maybe_decompose is called."""
        item = make_work_item(item_id="task-gate")

        with make_process_item_mocks(
            copilot_success=True,
            gate_result=GateAgentResult(success=False, reason="Tests fail"),
            include_config=True,
            include_handoff=True,
            include_session_cleanup=True,
            max_copilot_failure_retries=0,
        ) as mocks:
            mocks["config"].return_value.max_gate_rejections_per_item = 1

            with (
                patch(PATCH_MAYBE_DECOMPOSE) as mock_decompose,
                patch(
                    "pokepoke.beads.beads_management.increment_gate_rejection_count",
                    return_value=1,
                ),
                patch(f"{_WF}.add_comment"),
            ):
                result = process_work_item(item, interactive=False)

                assert result.success is False
                mock_decompose.assert_called()


class TestMaybeDecomposeHelper:
    """Tests for the _maybe_decompose helper function."""

    def test_calls_decomposition_when_threshold_met(self) -> None:
        item = make_work_item(item_id="task-1")

        class FakeConfig:
            decomposition_failure_threshold = 3
            decomposition_enabled = True

        with (
            patch("pokepoke.agents.decomposition_agent.should_decompose", return_value=True) as mock_should,
            patch("pokepoke.agents.decomposition_agent.run_decomposition") as mock_run,
        ):
            from pokepoke.agents.decomposition_agent import DecompositionResult
            mock_run.return_value = DecompositionResult(
                success=True, parent_id="task-1", child_ids=["c-1"], reason="ok",
            )
            _maybe_decompose(item, copilot_failure_count=2, gate_rejection_count=1, config=FakeConfig())
            mock_should.assert_called_once_with(item, 3, 3, True, force=False)
            mock_run.assert_called_once_with(item, 3, too_large_context=None)

    def test_skips_when_should_decompose_returns_false(self) -> None:
        item = make_work_item(item_id="task-1")

        class FakeConfig:
            decomposition_failure_threshold = 3
            decomposition_enabled = True

        with (
            patch("pokepoke.agents.decomposition_agent.should_decompose", return_value=False),
            patch("pokepoke.agents.decomposition_agent.run_decomposition") as mock_run,
        ):
            _maybe_decompose(item, copilot_failure_count=1, gate_rejection_count=0, config=FakeConfig())
            mock_run.assert_not_called()

    def test_handles_missing_config_attrs_gracefully(self) -> None:
        """Config without decomposition attrs uses defaults (threshold=3, enabled=True)."""
        item = make_work_item(item_id="task-1")

        class EmptyConfig:
            pass

        with (
            patch("pokepoke.agents.decomposition_agent.should_decompose", return_value=False) as mock_should,
            patch("pokepoke.agents.decomposition_agent.run_decomposition"),
        ):
            _maybe_decompose(item, copilot_failure_count=1, gate_rejection_count=0, config=EmptyConfig())
            mock_should.assert_called_once_with(item, 1, 3, True, force=False)


class TestMaybeDecomposeWithTooLargeContext:
    """Tests for _maybe_decompose when called with too_large_context."""

    def test_too_large_context_forces_decomposition(self) -> None:
        """When too_large_context is set, force=True bypasses threshold."""
        item = make_work_item(item_id="task-big")

        class FakeConfig:
            decomposition_failure_threshold = 3
            decomposition_enabled = True

        with (
            patch("pokepoke.agents.decomposition_agent.should_decompose", return_value=True) as mock_should,
            patch("pokepoke.agents.decomposition_agent.run_decomposition") as mock_run,
        ):
            from pokepoke.agents.decomposition_agent import DecompositionResult
            mock_run.return_value = DecompositionResult(
                success=True, parent_id="task-big", child_ids=["c-1", "c-2"], reason="ok",
            )
            _maybe_decompose(
                item, copilot_failure_count=0, gate_rejection_count=0,
                config=FakeConfig(), too_large_context="Agent said it's huge",
            )
            mock_should.assert_called_once_with(item, 0, 3, True, force=True)
            mock_run.assert_called_once_with(
                item, 0, too_large_context="Agent said it's huge",
            )

    def test_too_large_context_none_does_not_force(self) -> None:
        """When too_large_context is None, force=False (normal threshold check)."""
        item = make_work_item(item_id="task-normal")

        class FakeConfig:
            decomposition_failure_threshold = 3
            decomposition_enabled = True

        with (
            patch("pokepoke.agents.decomposition_agent.should_decompose", return_value=False) as mock_should,
            patch("pokepoke.agents.decomposition_agent.run_decomposition") as mock_run,
        ):
            _maybe_decompose(
                item, copilot_failure_count=1, gate_rejection_count=0,
                config=FakeConfig(),
            )
            mock_should.assert_called_once_with(item, 1, 3, True, force=False)
            mock_run.assert_not_called()


class TestShouldDecomposeForce:
    """Tests for the force parameter on should_decompose."""

    def test_force_bypasses_threshold(self) -> None:
        from pokepoke.agents.decomposition_agent import should_decompose
        item = make_work_item(item_id="task-force")
        assert should_decompose(item, failure_count=0, threshold=3, enabled=True, force=True) is True

    def test_force_still_respects_disabled(self) -> None:
        from pokepoke.agents.decomposition_agent import should_decompose
        item = make_work_item(item_id="task-disabled")
        assert should_decompose(item, failure_count=0, threshold=3, enabled=False, force=True) is False

    def test_force_still_respects_max_depth(self) -> None:
        from pokepoke.agents.decomposition_agent import should_decompose
        item = make_work_item(item_id="task-deep")
        item.metadata = {"decomposition_depth": 3}
        assert should_decompose(
            item, failure_count=0, threshold=3, enabled=True,
            max_depth=3, force=True,
        ) is False


class TestConfigDefaults:
    """Verify config defaults for decomposition settings."""

    def test_decomposition_enabled_by_default(self) -> None:
        from pokepoke.config import ProjectConfig
        config = ProjectConfig()
        assert config.decomposition_enabled is True

    def test_decomposition_threshold_default_is_3(self) -> None:
        from pokepoke.config import ProjectConfig
        config = ProjectConfig()
        assert config.decomposition_failure_threshold == 3

    def test_threshold_clamped_to_minimum_of_1(self) -> None:
        from pokepoke.config import ProjectConfig
        config = ProjectConfig(decomposition_failure_threshold=0)
        assert config.decomposition_failure_threshold == 1

    def test_threshold_negative_raises(self) -> None:
        from pokepoke.config import ConfigError, ProjectConfig
        with pytest.raises(ConfigError, match="negative value"):
            ProjectConfig(decomposition_failure_threshold=-5)


class TestAgentTypeRegistered:
    """Verify the decomposition agent type is registered."""

    def test_decomposition_in_agent_types(self) -> None:
        from pokepoke.agents.agent_types import AGENT_TYPES
        assert "decomposition" in AGENT_TYPES

    def test_decomposition_agent_has_correct_emoji(self) -> None:
        from pokepoke.agents.agent_types import AGENT_TYPES
        assert AGENT_TYPES["decomposition"].emoji == "🔀"

    def test_decomposition_agent_resolvable(self) -> None:
        from pokepoke.agents.agent_types import resolve_agent_type
        agent = resolve_agent_type("decomposition")
        assert agent.key == "decomposition"

    def test_decomposition_agent_display_name(self) -> None:
        from pokepoke.agents.agent_types import resolve_agent_type
        agent = resolve_agent_type("Decomposition")
        assert agent.display_name == "Decomposition"
