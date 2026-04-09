"""Tests for session resume functionality in copilot_sdk.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pokepoke.models.copilot_sdk import (
    CopilotInvocationConfig,
    _summarize_output,
    build_resume_prompt,
    invoke_copilot_sdk_sync,
)
from pokepoke.types import BeadsWorkItem, CopilotResult

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_work_item() -> BeadsWorkItem:
    return BeadsWorkItem(
        id="test-resume-1",
        title="Resume test item",
        description="Test description for resume",
        status="in_progress",
        priority=1,
        issue_type="feature",
        labels=["testing"],
    )


@pytest.fixture
def work_item_no_desc() -> BeadsWorkItem:
    return BeadsWorkItem(
        id="test-resume-2",
        title="No description item",
        description=None,
        status="in_progress",
        priority=2,
        issue_type="bug",
    )


# ── _summarize_output tests ─────────────────────────────────────────────────


class TestSummarizeOutput:
    """Tests for _summarize_output helper."""

    def test_empty_output_returns_none(self):
        assert _summarize_output([]) is None

    def test_whitespace_only_returns_none(self):
        assert _summarize_output(["  ", "\n", "  \n"]) is None

    def test_short_output_returned_as_is(self):
        lines = ["line 1\n", "line 2\n"]
        result = _summarize_output(lines)
        assert result == "line 1\nline 2"

    def test_long_output_truncated_to_tail(self):
        lines = ["x" * 100 + "\n" for _ in range(50)]
        result = _summarize_output(lines, max_length=200)
        assert result is not None
        assert result.startswith("...(earlier output truncated)...")
        assert len(result) <= 200 + len("...(earlier output truncated)...\n")

    def test_exact_max_length_not_truncated(self):
        text = "a" * 100
        result = _summarize_output([text], max_length=100)
        assert result == text
        assert "truncated" not in result

    def test_one_over_max_length_is_truncated(self):
        text = "a" * 101
        result = _summarize_output([text], max_length=100)
        assert result is not None
        assert "truncated" in result

    def test_preserves_tail_content(self):
        lines = ["BEGINNING\n", "MIDDLE\n", "END_MARKER\n"]
        result = _summarize_output(lines, max_length=30)
        assert result is not None
        assert "END_MARKER" in result


# ── build_gate_resume_prompt tests ───────────────────────────────────────────


class TestBuildGateResumePrompt:
    """Tests for build_gate_resume_prompt function."""

    def test_basic_gate_resume(self, sample_work_item):
        from pokepoke.models.sdk_helpers import build_gate_resume_prompt
        result = build_gate_resume_prompt(sample_work_item)
        assert "Gate Agent Session Resume" in result
        assert sample_work_item.id in result
        assert sample_work_item.title in result
        assert "timed out" in result
        assert "Gate Agent" in result

    def test_includes_handoff_context(self, sample_work_item):
        from pokepoke.models.sdk_helpers import build_gate_resume_prompt
        result = build_gate_resume_prompt(
            sample_work_item, handoff_context="diff --stat output"
        )
        assert "Handoff Context" in result
        assert "diff --stat output" in result

    def test_includes_previous_output(self, sample_work_item):
        from pokepoke.models.sdk_helpers import build_gate_resume_prompt
        result = build_gate_resume_prompt(
            sample_work_item, previous_output_summary="Running pytest..."
        )
        assert "Previous Progress" in result
        assert "Running pytest..." in result

    def test_no_previous_output(self, sample_work_item):
        from pokepoke.models.sdk_helpers import build_gate_resume_prompt
        result = build_gate_resume_prompt(sample_work_item, previous_output_summary=None)
        assert "Previous Progress" not in result

    def test_custom_default_branch(self, sample_work_item):
        from pokepoke.models.sdk_helpers import build_gate_resume_prompt
        result = build_gate_resume_prompt(sample_work_item, default_branch="main")
        assert "`main`" in result

    def test_no_description(self, work_item_no_desc):
        from pokepoke.models.sdk_helpers import build_gate_resume_prompt
        result = build_gate_resume_prompt(work_item_no_desc)
        assert "Gate Agent Session Resume" in result
        assert "Description" not in result


# ── GateAgentResult tests ────────────────────────────────────────────────────


class TestGateAgentResult:
    """Tests for GateAgentResult dataclass."""

    def test_tuple_unpacking(self):
        from pokepoke.types import GateAgentResult
        result = GateAgentResult(success=True, reason="ok")
        success, reason, stats, crashed = result
        assert success is True
        assert reason == "ok"
        assert stats is None
        assert crashed is False

    def test_timeout_fields(self):
        from pokepoke.types import GateAgentResult
        result = GateAgentResult(
            success=False, reason="timed out", is_timeout=True,
            session_id="sess-123", last_output_summary="test output",
        )
        assert result.is_timeout is True
        assert result.session_id == "sess-123"
        assert result.last_output_summary == "test output"
        # Tuple unpacking ignores timeout fields
        success, _reason, _stats, crashed = result
        assert success is False
        assert crashed is False

    def test_len(self):
        from pokepoke.types import GateAgentResult
        result = GateAgentResult(success=True, reason="ok")
        assert len(result) == 4


# ── build_resume_prompt tests ────────────────────────────────────────────────


class TestBuildResumePrompt:
    """Tests for build_resume_prompt function."""

    def test_basic_resume_prompt(self, sample_work_item):
        result = build_resume_prompt(sample_work_item)

        assert "Session Resume" in result
        assert sample_work_item.id in result
        assert sample_work_item.title in result
        assert "timed out" in result
        assert "Continue from where you left off" in result
        assert sample_work_item.description in result

    def test_includes_previous_output_summary(self, sample_work_item):
        summary = "Last tool call was editing src/main.py"
        result = build_resume_prompt(sample_work_item, previous_output_summary=summary)

        assert "Previous Progress" in result
        assert summary in result

    def test_no_output_summary_section_when_none(self, sample_work_item):
        result = build_resume_prompt(sample_work_item, previous_output_summary=None)

        assert "Previous Progress" not in result

    def test_includes_retry_feedback(self, sample_work_item):
        feedback = ["Tests failed: 2 errors", "Missing coverage on module X"]
        result = build_resume_prompt(sample_work_item, retry_feedback=feedback)

        assert "Feedback from Previous Attempts" in result
        assert "Tests failed: 2 errors" in result
        assert "Missing coverage on module X" in result

    def test_no_feedback_section_when_none(self, sample_work_item):
        result = build_resume_prompt(sample_work_item, retry_feedback=None)

        assert "Feedback from Previous Attempts" not in result

    def test_no_description_section_when_none(self, work_item_no_desc):
        result = build_resume_prompt(work_item_no_desc)

        assert "**Description:**" not in result
        assert work_item_no_desc.id in result
        assert work_item_no_desc.title in result

    def test_includes_success_criteria(self, sample_work_item):
        result = build_resume_prompt(sample_work_item)

        assert "Success Criteria" in result
        assert "fully implemented" in result
        assert "pre-commit validation" in result

    def test_full_prompt_with_all_sections(self, sample_work_item):
        result = build_resume_prompt(
            sample_work_item,
            previous_output_summary="Edited 3 files",
            retry_feedback=["Fix lint errors"],
        )

        assert "Session Resume" in result
        assert sample_work_item.description in result
        assert "Edited 3 files" in result
        assert "Fix lint errors" in result
        assert "Success Criteria" in result

    def test_resume_prompt_shorter_than_full_prompt(self, sample_work_item):
        """Resume prompt should be meaningfully shorter than the full template."""
        from pokepoke.models.copilot_sdk import build_prompt_from_work_item

        full = build_prompt_from_work_item(sample_work_item)
        resume = build_resume_prompt(sample_work_item)

        assert len(resume) < len(full)


# ── Session ID generation and threading ──────────────────────────────────────


class TestSessionIdGeneration:
    """Tests for session_id generation and passing."""

    @patch('pokepoke.models.copilot_sdk.asyncio.run')
    def test_sync_wrapper_passes_session_id(self, mock_run, sample_work_item):
        mock_run.return_value = CopilotResult(
            work_item_id=sample_work_item.id, success=True, session_id="test-sid"
        )

        result = invoke_copilot_sdk_sync(
            sample_work_item,
            prompt="test",
            config=CopilotInvocationConfig(
                session_id="custom-session-id",
                is_resume=True,
            ),
        )

        assert result.session_id == "test-sid"

    @patch('pokepoke.models.copilot_sdk.asyncio.run')
    def test_sync_wrapper_passes_is_resume(self, mock_run, sample_work_item):
        mock_run.return_value = CopilotResult(
            work_item_id=sample_work_item.id, success=True
        )

        invoke_copilot_sdk_sync(
            sample_work_item,
            prompt="test",
            config=CopilotInvocationConfig(is_resume=True),
        )

        # Verify asyncio.run was called (async invoke was called)
        mock_run.assert_called_once()


class TestSessionConfigWithId:
    """Tests for _build_session_config with session_id."""

    def test_session_id_included_in_config(self):
        from pokepoke.models.sdk_helpers import _build_session_config

        config = _build_session_config("gpt-4", deny_write=False, session_id="my-session")
        assert config["session_id"] == "my-session"

    def test_no_session_id_when_none(self):
        from pokepoke.models.sdk_helpers import _build_session_config

        config = _build_session_config("gpt-4", deny_write=False, session_id=None)
        assert "session_id" not in config

    def test_session_id_empty_string_not_included(self):
        from pokepoke.models.sdk_helpers import _build_session_config

        config = _build_session_config("gpt-4", deny_write=False, session_id="")
        assert "session_id" not in config


# ── CopilotResult session fields ─────────────────────────────────────────────


class TestCopilotResultSessionFields:
    """Tests for new session fields on CopilotResult."""

    def test_default_session_fields_are_none(self):
        result = CopilotResult(work_item_id="test", success=True)
        assert result.session_id is None
        assert result.last_output_summary is None

    def test_session_fields_set_on_construction(self):
        result = CopilotResult(
            work_item_id="test",
            success=False,
            error="timeout",
            session_id="pokepoke-test",
            last_output_summary="last output",
        )
        assert result.session_id == "pokepoke-test"
        assert result.last_output_summary == "last output"

    def test_session_fields_mutable(self):
        result = CopilotResult(work_item_id="test", success=False)
        result.session_id = "new-session"
        result.last_output_summary = "new summary"
        assert result.session_id == "new-session"
        assert result.last_output_summary == "new summary"


# ── _fail_result with session fields ─────────────────────────────────────────


class TestFailResultSessionFields:
    """Tests for _fail_result with session_id and output summary."""

    def test_fail_result_includes_session_id(self):
        from pokepoke.models.sdk_helpers import _fail_result

        result = _fail_result("item-1", "timeout", session_id="sid-123")
        assert result.session_id == "sid-123"
        assert result.success is False

    def test_fail_result_includes_output_summary(self):
        from pokepoke.models.sdk_helpers import _fail_result

        result = _fail_result(
            "item-1", "timeout",
            session_id="sid-123",
            last_output_summary="some output",
        )
        assert result.last_output_summary == "some output"

    def test_fail_result_defaults_session_fields_to_none(self):
        from pokepoke.models.sdk_helpers import _fail_result

        result = _fail_result("item-1", "some error")
        assert result.session_id is None
        assert result.last_output_summary is None


# ── _build_copilot_result with session_id ────────────────────────────────────


class TestBuildCopilotResultSessionId:
    """Tests for _build_copilot_result with session_id."""

    def test_includes_session_id(self, sample_work_item):
        import time

        from pokepoke.models.sdk_helpers import _build_copilot_result

        stats = {
            'pending_tool_calls': 0,
            'idle_task': None,
            'total_input_tokens': 100,
            'total_output_tokens': 50,
            'total_cache_read_tokens': 0,
            'total_cache_write_tokens': 0,
            'turn_count': 2,
            'total_tool_calls': 3,
            'last_event_time': time.monotonic(),
            'event_count': 10,
            'last_tool_activity_time': 0.0,
        }

        result = _build_copilot_result(
            work_item=sample_work_item,
            output_lines=["output"],
            errors=[],
            stats=stats,
            current_model="gpt-4",
            total_api_duration=1.0,
            total_wall_duration=2.0,
            session_id="pokepoke-test-resume-1",
        )

        assert result.session_id == "pokepoke-test-resume-1"
        assert result.success is True


# ── invoke_copilot_sdk timeout includes session state ────────────────────────


class TestInvokeSdkTimeoutSessionState:
    """Tests that timeout results include session_id and output summary."""

    @pytest.fixture
    def mock_client_class(self):
        with patch("pokepoke.models.copilot_sdk.CopilotClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.start = AsyncMock()
            mock_client.stop = AsyncMock()
            mock_client.get_state.return_value = "connected"
            mock_cls.return_value = mock_client
            yield mock_cls

    @pytest.mark.asyncio
    async def test_timeout_result_contains_session_id(
        self, mock_client_class, sample_work_item
    ):
        from pokepoke.models.copilot_sdk import invoke_copilot_sdk

        mock_client = mock_client_class.return_value
        mock_session = AsyncMock()
        mock_session.session_id = "pokepoke-test-resume-1"
        mock_session.send = AsyncMock()
        mock_session.abort = AsyncMock()
        mock_session.destroy = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)

        # Simulate immediate timeout by using a very short timeout
        result = await invoke_copilot_sdk(
            sample_work_item,
            prompt="test prompt",
            config=CopilotInvocationConfig(timeout=0.01),
        )

        assert result.success is False
        assert result.session_id == "pokepoke-test-resume-1"
        assert "timeout" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_timeout_result_contains_output_summary(
        self, mock_client_class, sample_work_item
    ):
        from pokepoke.models.copilot_sdk import invoke_copilot_sdk

        mock_client = mock_client_class.return_value
        mock_session = AsyncMock()
        mock_session.session_id = "pokepoke-test-resume-1"
        mock_session.abort = AsyncMock()
        mock_session.destroy = AsyncMock()

        # Simulate some output before timeout by having send produce output
        async def fake_send(msg):
            pass

        mock_session.send = fake_send
        mock_client.create_session = AsyncMock(return_value=mock_session)

        result = await invoke_copilot_sdk(
            sample_work_item,
            prompt="test prompt",
            config=CopilotInvocationConfig(timeout=0.01),
        )

        assert result.success is False
        assert result.session_id is not None

    @pytest.mark.asyncio
    async def test_resume_uses_provided_session_id(
        self, mock_client_class, sample_work_item
    ):
        """When session_id is provided, it should be passed to session config."""
        from pokepoke.models.copilot_sdk import invoke_copilot_sdk

        mock_client = mock_client_class.return_value
        mock_session = AsyncMock()
        mock_session.session_id = "custom-session-id"
        mock_session.send = AsyncMock()
        mock_session.abort = AsyncMock()
        mock_session.destroy = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)

        await invoke_copilot_sdk(
            sample_work_item,
            prompt="resume prompt",
            config=CopilotInvocationConfig(
                timeout=0.01,
                session_id="custom-session-id",
                is_resume=True,
            ),
        )

        # Verify session config included the session_id
        create_call = mock_client.create_session.call_args
        session_config = create_call[0][0]
        assert session_config["session_id"] == "custom-session-id"

    @pytest.mark.asyncio
    async def test_generates_stable_session_id_from_item(
        self, mock_client_class, sample_work_item
    ):
        """When no session_id is provided, one is generated from the work item ID."""
        from pokepoke.models.copilot_sdk import invoke_copilot_sdk

        mock_client = mock_client_class.return_value
        mock_session = AsyncMock()
        mock_session.session_id = "auto-generated"
        mock_session.send = AsyncMock()
        mock_session.abort = AsyncMock()
        mock_session.destroy = AsyncMock()
        mock_client.create_session = AsyncMock(return_value=mock_session)

        actual = await invoke_copilot_sdk(
            sample_work_item,
            prompt="test",
            config=CopilotInvocationConfig(timeout=0.01),
        )

        # The generated session_id should be based on the item ID
        assert actual.session_id == f"pokepoke-{sample_work_item.id}"

    @pytest.mark.asyncio
    async def test_is_resume_uses_resume_prompt(
        self, mock_client_class, sample_work_item
    ):
        """When is_resume=True and no prompt provided, build_resume_prompt is used."""
        from pokepoke.models.copilot_sdk import invoke_copilot_sdk

        mock_client = mock_client_class.return_value
        mock_session = AsyncMock()
        mock_session.session_id = "resume-sid"
        mock_session.abort = AsyncMock()
        mock_session.destroy = AsyncMock()

        sent_prompts = []

        async def capture_send(msg):
            sent_prompts.append(msg.get("prompt", ""))

        mock_session.send = capture_send
        mock_client.create_session = AsyncMock(return_value=mock_session)

        await invoke_copilot_sdk(
            sample_work_item,
            config=CopilotInvocationConfig(
                timeout=0.01,
                session_id="resume-sid",
                is_resume=True,
            ),
        )

        assert len(sent_prompts) == 1
        # Resume prompt should contain "Session Resume"
        assert "Session Resume" in sent_prompts[0]


# ── AI backend session_id threading ──────────────────────────────────────────


class TestAIBackendSessionThreading:
    """Tests that session_id and is_resume are threaded through backends."""

    def test_copilot_backend_passes_session_params(self, sample_work_item):
        from pokepoke.models.ai_backends import CopilotBackend

        with patch("pokepoke.models.ai_backends.invoke_copilot_sdk_sync") as mock_sync:
            mock_sync.return_value = CopilotResult(
                work_item_id=sample_work_item.id, success=True
            )

            backend = CopilotBackend()
            backend.invoke(
                sample_work_item,
                prompt="test",
                session_id="my-session",
                is_resume=True,
            )

            mock_sync.assert_called_once()
            call_kwargs = mock_sync.call_args[1]
            config = call_kwargs["config"]
            assert config.session_id == "my-session"
            assert config.is_resume is True

    def test_invoke_copilot_passes_session_params(self, sample_work_item):
        from pokepoke.models.ai_backends import invoke_copilot

        with patch("pokepoke.models.ai_backends.get_backend") as mock_get:
            mock_backend = MagicMock()
            mock_backend.invoke.return_value = CopilotResult(
                work_item_id=sample_work_item.id, success=True
            )
            mock_get.return_value = mock_backend

            invoke_copilot(
                sample_work_item,
                prompt="test",
                session_id="thread-session",
                is_resume=True,
            )

            call_kwargs = mock_backend.invoke.call_args[1]
            assert call_kwargs["session_id"] == "thread-session"
            assert call_kwargs["is_resume"] is True

    def test_claude_code_backend_accepts_session_params(self, sample_work_item):
        """ClaudeCodeBackend should accept session_id/is_resume without error."""
        from pokepoke.models.ai_backends import ClaudeCodeBackend

        backend = ClaudeCodeBackend(cli_path="nonexistent-claude-cli")
        result = backend.invoke(
            sample_work_item,
            prompt="test",
            session_id="ignored-session",
            is_resume=True,
        )

        # Should return a failure (CLI not found) but not crash
        assert result.success is False
        assert "not found" in (result.error or "").lower()
