"""Tests for ThreadOutputRouter thread-local output routing."""

from pokepoke.desktop.thread_output_router import ThreadOutputRouter, _thread_output


class TestOrchestratorOutput:
    def test_sets_target_to_orchestrator(self) -> None:
        with ThreadOutputRouter.orchestrator_output():
            assert ThreadOutputRouter.get_thread_target() == "orchestrator"

    def test_restores_previous_target(self) -> None:
        _thread_output.target = "agent"
        with ThreadOutputRouter.orchestrator_output():
            pass
        assert ThreadOutputRouter.get_thread_target() == "agent"
        _thread_output.target = None

    def test_restores_target_on_exception(self) -> None:
        _thread_output.target = "prev"
        try:
            with ThreadOutputRouter.orchestrator_output():
                raise ValueError("boom")
        except ValueError:
            pass
        assert ThreadOutputRouter.get_thread_target() == "prev"
        _thread_output.target = None


class TestAgentOutput:
    def test_sets_target_to_agent(self) -> None:
        with ThreadOutputRouter.agent_output():
            assert ThreadOutputRouter.get_thread_target() == "agent"

    def test_restores_previous_target(self) -> None:
        _thread_output.target = "orchestrator"
        with ThreadOutputRouter.agent_output():
            pass
        assert ThreadOutputRouter.get_thread_target() == "orchestrator"
        _thread_output.target = None


class TestAgentOutputFor:
    def test_sets_agent_id(self) -> None:
        with ThreadOutputRouter.agent_output_for("agent-42"):
            assert ThreadOutputRouter.get_thread_agent_id() == "agent-42"

    def test_restores_previous_agent_id(self) -> None:
        _thread_output.agent_id = "agent-1"
        with ThreadOutputRouter.agent_output_for("agent-2"):
            assert ThreadOutputRouter.get_thread_agent_id() == "agent-2"
        assert ThreadOutputRouter.get_thread_agent_id() == "agent-1"
        _thread_output.agent_id = None


class TestGetters:
    def test_get_thread_target_default(self) -> None:
        if hasattr(_thread_output, "target"):
            del _thread_output.target
        assert ThreadOutputRouter.get_thread_target() is None

    def test_get_thread_style_default(self) -> None:
        if hasattr(_thread_output, "style"):
            del _thread_output.style
        assert ThreadOutputRouter.get_thread_style() is None

    def test_get_thread_agent_id_default(self) -> None:
        if hasattr(_thread_output, "agent_id"):
            del _thread_output.agent_id
        assert ThreadOutputRouter.get_thread_agent_id() is None

    def test_get_thread_line_buffer_default(self) -> None:
        if hasattr(_thread_output, "line_buffer"):
            del _thread_output.line_buffer
        assert ThreadOutputRouter.get_thread_line_buffer() == ""


class TestLineBuffer:
    def test_set_and_get_line_buffer(self) -> None:
        ThreadOutputRouter.set_thread_line_buffer("partial line")
        assert ThreadOutputRouter.get_thread_line_buffer() == "partial line"
        ThreadOutputRouter.set_thread_line_buffer("")

    def test_overwrite_buffer(self) -> None:
        ThreadOutputRouter.set_thread_line_buffer("first")
        ThreadOutputRouter.set_thread_line_buffer("second")
        assert ThreadOutputRouter.get_thread_line_buffer() == "second"
        ThreadOutputRouter.set_thread_line_buffer("")
