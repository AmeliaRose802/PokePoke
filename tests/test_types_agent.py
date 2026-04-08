"""Unit tests for types_agent module (CopilotResult, GateAgentResult)."""

from pokepoke.types_agent import CopilotResult, GateAgentResult


class TestCopilotResultDirect:
    """Test CopilotResult imported directly from types_agent."""

    def test_create_with_required_fields(self) -> None:
        result = CopilotResult(work_item_id="item-1", success=True)
        assert result.work_item_id == "item-1"
        assert result.success is True

    def test_defaults(self) -> None:
        result = CopilotResult(work_item_id="item-1", success=False)
        assert result.output is None
        assert result.error is None
        assert result.validation_errors is None
        assert result.attempt_count == 1
        assert result.is_rate_limited is False
        assert result.stats is None
        assert result.model is None
        assert result.session_id is None
        assert result.last_output_summary is None
        assert result.work_agent_outcome is None

    def test_all_fields(self) -> None:
        result = CopilotResult(
            work_item_id="item-2",
            success=True,
            output="done",
            error=None,
            validation_errors=["warn"],
            attempt_count=3,
            is_rate_limited=True,
            model="gpt-4",
            session_id="sess-1",
            last_output_summary="summary",
        )
        assert result.validation_errors == ["warn"]
        assert result.attempt_count == 3
        assert result.is_rate_limited is True
        assert result.model == "gpt-4"
        assert result.session_id == "sess-1"
        assert result.last_output_summary == "summary"


class TestGateAgentResultDirect:
    """Test GateAgentResult imported directly from types_agent."""

    def test_create_with_required_fields(self) -> None:
        result = GateAgentResult(success=True, reason="all checks passed")
        assert result.success is True
        assert result.reason == "all checks passed"

    def test_defaults(self) -> None:
        result = GateAgentResult(success=False, reason="fail")
        assert result.stats is None
        assert result.crashed is False
        assert result.is_timeout is False
        assert result.session_id is None
        assert result.last_output_summary is None

    def test_iter_protocol(self) -> None:
        """GateAgentResult supports tuple unpacking (success, reason, stats, crashed)."""
        result = GateAgentResult(success=True, reason="ok", crashed=False)
        items = list(result)
        assert items == [True, "ok", None, False]

    def test_len_protocol(self) -> None:
        """GateAgentResult reports length 4 for unpacking."""
        result = GateAgentResult(success=True, reason="ok")
        assert len(result) == 4

    def test_tuple_unpacking(self) -> None:
        """Verify structured unpacking works end-to-end."""
        result = GateAgentResult(success=False, reason="tests failed", crashed=True)
        success, reason, stats, crashed = result
        assert success is False
        assert reason == "tests failed"
        assert stats is None
        assert crashed is True


class TestReExportFromTypes:
    """Ensure backwards-compatible re-exports from pokepoke.types work."""

    def test_copilot_result_reexported(self) -> None:
        from pokepoke.types import CopilotResult as ReExported
        assert ReExported is CopilotResult

    def test_gate_agent_result_reexported(self) -> None:
        from pokepoke.types import GateAgentResult as ReExported
        assert ReExported is GateAgentResult
