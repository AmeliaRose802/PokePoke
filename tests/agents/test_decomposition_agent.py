"""Tests for the decomposition agent module."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from pokepoke.agents.decomposition_agent import (
    DECOMPOSITION_LABEL,
    DecompositionResult,
    SubTask,
    _build_subtasks_from_item,
    _create_child_item,
    _update_parent_metadata,
    run_decomposition,
    should_decompose,
)
from pokepoke.types import BeadsWorkItem

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_item(
    item_id: str = "task-1",
    title: str = "Build authentication system",
    description: str | None = None,
    priority: int = 2,
    labels: list[str] | None = None,
    issue_type: str = "task",
) -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id,
        title=title,
        description=description or "",
        status="open",
        priority=priority,
        issue_type=issue_type,
        labels=labels,
    )


# ---------------------------------------------------------------------------
# should_decompose
# ---------------------------------------------------------------------------


class TestShouldDecompose:
    """Tests for the should_decompose gating function."""

    def test_returns_false_when_disabled(self) -> None:
        item = _make_item()
        assert should_decompose(item, failure_count=5, threshold=3, enabled=False) is False

    def test_returns_false_below_threshold(self) -> None:
        item = _make_item()
        assert should_decompose(item, failure_count=2, threshold=3, enabled=True) is False

    def test_returns_true_at_threshold(self) -> None:
        item = _make_item()
        assert should_decompose(item, failure_count=3, threshold=3, enabled=True) is True

    def test_returns_true_above_threshold(self) -> None:
        item = _make_item()
        assert should_decompose(item, failure_count=5, threshold=3, enabled=True) is True

    def test_skips_already_decomposed_items(self) -> None:
        item = _make_item(labels=[DECOMPOSITION_LABEL])
        assert should_decompose(item, failure_count=5, threshold=3, enabled=True) is False

    def test_allows_items_with_other_labels(self) -> None:
        item = _make_item(labels=["bug", "high-priority"])
        assert should_decompose(item, failure_count=3, threshold=3, enabled=True) is True

    def test_allows_items_with_none_labels(self) -> None:
        item = _make_item(labels=None)
        assert should_decompose(item, failure_count=3, threshold=3, enabled=True) is True

    def test_threshold_of_one(self) -> None:
        item = _make_item()
        assert should_decompose(item, failure_count=1, threshold=1, enabled=True) is True


# ---------------------------------------------------------------------------
# _build_subtasks_from_item
# ---------------------------------------------------------------------------


class TestBuildSubtasksFromItem:
    """Tests for description-based subtask extraction."""

    def test_empty_description_produces_two_generic_subtasks(self) -> None:
        item = _make_item(description="")
        subtasks = _build_subtasks_from_item(item)
        assert len(subtasks) == 2
        assert "core logic" in subtasks[0].title.lower()
        assert "tests" in subtasks[1].title.lower()

    def test_none_description_produces_two_generic_subtasks(self) -> None:
        item = _make_item(description=None)
        subtasks = _build_subtasks_from_item(item)
        assert len(subtasks) == 2

    def test_bullet_list_produces_one_subtask_per_bullet(self) -> None:
        item = _make_item(description="- Add login endpoint\n- Add signup endpoint\n- Add password reset")
        subtasks = _build_subtasks_from_item(item)
        assert len(subtasks) == 3
        assert "login" in subtasks[0].title.lower()
        assert "signup" in subtasks[1].title.lower()
        assert "password" in subtasks[2].title.lower()

    def test_numbered_list_produces_subtasks(self) -> None:
        item = _make_item(description="1. Create database schema\n2. Add API routes\n3. Write tests")
        subtasks = _build_subtasks_from_item(item)
        assert len(subtasks) == 3

    def test_markdown_headers_produce_subtasks(self) -> None:
        item = _make_item(description="## Setup\nDo setup\n## Implementation\nDo work\n## Testing\nDo tests")
        subtasks = _build_subtasks_from_item(item)
        assert len(subtasks) == 3

    def test_preserves_parent_priority(self) -> None:
        item = _make_item(priority=1, description="- Task A\n- Task B")
        subtasks = _build_subtasks_from_item(item)
        assert all(s.priority == 1 for s in subtasks)

    def test_subtask_descriptions_reference_parent_title(self) -> None:
        item = _make_item(title="Auth System", description="- Login\n- Logout")
        subtasks = _build_subtasks_from_item(item)
        assert all("Auth System" in s.description for s in subtasks)

    def test_long_title_is_truncated(self) -> None:
        long_line = "- " + "A" * 200
        item = _make_item(description=long_line)
        subtasks = _build_subtasks_from_item(item)
        assert len(subtasks[0].title) <= 80

    def test_blank_line_separated_paragraphs(self) -> None:
        desc = "First paragraph about setup.\n\nSecond paragraph about implementation."
        item = _make_item(description=desc)
        subtasks = _build_subtasks_from_item(item)
        assert len(subtasks) == 2

    def test_asterisk_bullets(self) -> None:
        item = _make_item(description="* Item one\n* Item two")
        subtasks = _build_subtasks_from_item(item)
        assert len(subtasks) == 2

    def test_default_issue_type_is_task(self) -> None:
        item = _make_item(description="- One\n- Two")
        subtasks = _build_subtasks_from_item(item)
        assert all(s.issue_type == "task" for s in subtasks)


# ---------------------------------------------------------------------------
# _create_child_item
# ---------------------------------------------------------------------------


class TestCreateChildItem:
    """Tests for beads child item creation."""

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_creates_item_with_parent_dep(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd", "create"], 0, stdout='{"id": "child-1"}', stderr=""
        )
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result == "child-1"
        args = mock_run.call_args[0][0]
        assert "create" in args
        assert "parent:parent-1" in args
        assert DECOMPOSITION_LABEL in args

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_returns_none_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd", "create"], 1, stdout="", stderr="error"
        )
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result is None

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_returns_none_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("bd", 30)
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result is None

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_handles_list_response(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd", "create"], 0, stdout='[{"id": "child-2"}]', stderr=""
        )
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result == "child-2"

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_handles_empty_json_response(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd", "create"], 0, stdout="", stderr=""
        )
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result is None

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_handles_called_process_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd", stderr="failed")
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result is None


# ---------------------------------------------------------------------------
# _update_parent_metadata
# ---------------------------------------------------------------------------


class TestUpdateParentMetadata:
    """Tests for parent metadata updates after decomposition."""

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_sets_decomposed_flag_and_child_ids(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd"], 0,
            stdout='[{"id": "parent-1", "metadata": {}}]',
            stderr="",
        )
        result = _update_parent_metadata("parent-1", ["child-1", "child-2"])
        assert result is True
        # Second call should be the update
        update_call = mock_run.call_args_list[1]
        update_args = update_call[0][0]
        assert "update" in update_args
        assert "parent-1" in update_args
        # Verify metadata content
        meta_idx = update_args.index("--metadata") + 1
        metadata = json.loads(update_args[meta_idx])
        assert metadata["decomposed"] is True
        assert metadata["decomposition_child_ids"] == ["child-1", "child-2"]

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_preserves_existing_metadata(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd"], 0,
            stdout='[{"id": "parent-1", "metadata": {"existing_key": "val"}}]',
            stderr="",
        )
        _update_parent_metadata("parent-1", ["child-1"])
        update_call = mock_run.call_args_list[1]
        update_args = update_call[0][0]
        meta_idx = update_args.index("--metadata") + 1
        metadata = json.loads(update_args[meta_idx])
        assert metadata["existing_key"] == "val"
        assert metadata["decomposed"] is True

    @patch("pokepoke.agents.decomposition_agent._run_bd")
    def test_returns_false_on_show_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd"], 0, stdout="", stderr=""
        )
        result = _update_parent_metadata("parent-1", ["child-1"])
        assert result is False


# ---------------------------------------------------------------------------
# run_decomposition (integration-style unit test)
# ---------------------------------------------------------------------------


class TestRunDecomposition:
    """Tests for the main run_decomposition entry point."""

    @patch("pokepoke.beads.beads_management.add_comment")
    @patch("pokepoke.agents.decomposition_agent._update_parent_metadata")
    @patch("pokepoke.agents.decomposition_agent._create_child_item")
    def test_success_creates_children_and_updates_parent(
        self, mock_create: MagicMock, mock_update: MagicMock, mock_comment: MagicMock
    ) -> None:
        item = _make_item(description="- Task A\n- Task B\n- Task C")
        mock_create.side_effect = ["child-1", "child-2", "child-3"]
        mock_update.return_value = True

        result = run_decomposition(item, failure_count=3)

        assert result.success is True
        assert result.parent_id == "task-1"
        assert len(result.child_ids) == 3
        assert mock_create.call_count == 3
        mock_update.assert_called_once_with("task-1", ["child-1", "child-2", "child-3"])
        mock_comment.assert_called_once()

    @patch("pokepoke.beads.beads_management.add_comment")
    @patch("pokepoke.agents.decomposition_agent._update_parent_metadata")
    @patch("pokepoke.agents.decomposition_agent._create_child_item")
    def test_partial_creation_still_succeeds(
        self, mock_create: MagicMock, mock_update: MagicMock, mock_comment: MagicMock
    ) -> None:
        item = _make_item(description="- Task A\n- Task B\n- Task C")
        mock_create.side_effect = ["child-1", None, "child-3"]
        mock_update.return_value = True

        result = run_decomposition(item, failure_count=3)

        assert result.success is True
        assert len(result.child_ids) == 2
        assert "child-1" in result.child_ids
        assert "child-3" in result.child_ids

    @patch("pokepoke.agents.decomposition_agent._create_child_item")
    def test_fails_when_no_children_created(self, mock_create: MagicMock) -> None:
        item = _make_item(description="- Task A\n- Task B")
        mock_create.return_value = None

        result = run_decomposition(item, failure_count=3)

        assert result.success is False
        assert result.child_ids == []

    @patch("pokepoke.beads.beads_management.add_comment")
    @patch("pokepoke.agents.decomposition_agent._update_parent_metadata")
    @patch("pokepoke.agents.decomposition_agent._create_child_item")
    def test_empty_description_uses_generic_subtasks(
        self, mock_create: MagicMock, mock_update: MagicMock, mock_comment: MagicMock
    ) -> None:
        item = _make_item(description="")
        mock_create.side_effect = ["child-1", "child-2"]
        mock_update.return_value = True

        result = run_decomposition(item, failure_count=5)

        assert result.success is True
        assert len(result.child_ids) == 2

    @patch("pokepoke.beads.beads_management.add_comment")
    @patch("pokepoke.agents.decomposition_agent._update_parent_metadata")
    @patch("pokepoke.agents.decomposition_agent._create_child_item")
    def test_comment_mentions_failure_count(
        self, mock_create: MagicMock, mock_update: MagicMock, mock_comment: MagicMock
    ) -> None:
        item = _make_item(description="- A\n- B")
        mock_create.side_effect = ["c-1", "c-2"]
        mock_update.return_value = True

        run_decomposition(item, failure_count=4)

        comment_text = mock_comment.call_args[0][1]
        assert "4 consecutive failures" in comment_text
        assert "c-1" in comment_text
        assert "c-2" in comment_text


# ---------------------------------------------------------------------------
# DecompositionResult dataclass
# ---------------------------------------------------------------------------


class TestDecompositionResult:
    """Tests for the DecompositionResult dataclass."""

    def test_construction(self) -> None:
        result = DecompositionResult(
            success=True, parent_id="p-1", child_ids=["c-1", "c-2"], reason="ok"
        )
        assert result.success is True
        assert result.parent_id == "p-1"
        assert len(result.child_ids) == 2
        assert result.reason == "ok"


# ---------------------------------------------------------------------------
# SubTask dataclass
# ---------------------------------------------------------------------------


class TestSubTask:
    """Tests for the SubTask dataclass."""

    def test_default_issue_type(self) -> None:
        st = SubTask(title="T", description="D", priority=1)
        assert st.issue_type == "task"

    def test_custom_issue_type(self) -> None:
        st = SubTask(title="T", description="D", priority=1, issue_type="bug")
        assert st.issue_type == "bug"
