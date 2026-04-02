"""Tests for the decomposition agent module."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from pokepoke.agents.decomposition_agent import (
    DECOMPOSITION_LABEL,
    DecompositionResult,
    SubTask,
    _add_blocking_dependency,
    _create_child_item,
    _get_existing_child_titles,
    _is_valid_title,
    _parse_subtasks_from_output,
    _update_parent_metadata,
    run_decomposition,
    should_decompose,
)
from pokepoke.types import BeadsWorkItem

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DECOMP = "pokepoke.agents.decomposition_agent"


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
# _is_valid_title
# ---------------------------------------------------------------------------


class TestIsValidTitle:
    """Tests for title validation."""

    def test_rejects_short_title(self) -> None:
        assert _is_valid_title("abc") is False

    def test_rejects_placeholder_desc(self) -> None:
        assert _is_valid_title("desc") is False

    def test_rejects_placeholder_test_desc(self) -> None:
        assert _is_valid_title("test desc") is False

    def test_rejects_placeholder_implement(self) -> None:
        assert _is_valid_title("implement") is False

    def test_rejects_placeholder_add_tests(self) -> None:
        assert _is_valid_title("add tests") is False

    def test_rejects_implement_core_logic(self) -> None:
        assert _is_valid_title("Implement core logic") is False

    def test_rejects_tbd(self) -> None:
        assert _is_valid_title("TBD") is False

    def test_accepts_meaningful_title(self) -> None:
        assert _is_valid_title("Add retry logic to BeadsQueryClient") is True

    def test_accepts_title_at_min_length(self) -> None:
        assert _is_valid_title("1234567890") is True

    def test_rejects_below_min_length(self) -> None:
        assert _is_valid_title("123456789") is False


# ---------------------------------------------------------------------------
# _parse_subtasks_from_output
# ---------------------------------------------------------------------------


class TestParseSubtasksFromOutput:
    """Tests for parsing SDK output into SubTask objects."""

    def test_parses_json_array(self) -> None:
        output = '```json\n[{"title": "Add input validation to parser", "description": "Fix parser.py"}]\n```'
        subtasks = _parse_subtasks_from_output(output, default_priority=2)
        assert len(subtasks) == 1
        assert subtasks[0].title == "Add input validation to parser"
        assert subtasks[0].description == "Fix parser.py"
        assert subtasks[0].priority == 2

    def test_parses_bare_json_array(self) -> None:
        output = '[{"title": "Refactor the config loader module", "description": "desc"}]'
        subtasks = _parse_subtasks_from_output(output, default_priority=1)
        assert len(subtasks) == 1
        assert subtasks[0].priority == 1

    def test_returns_empty_on_no_json(self) -> None:
        assert _parse_subtasks_from_output("No JSON here", default_priority=2) == []

    def test_returns_empty_on_invalid_json(self) -> None:
        assert _parse_subtasks_from_output("[invalid json}", default_priority=2) == []

    def test_filters_invalid_titles(self) -> None:
        output = json.dumps([
            {"title": "desc", "description": "bad"},
            {"title": "Add proper error handling to the CLI module", "description": "good"},
        ])
        subtasks = _parse_subtasks_from_output(output, default_priority=2)
        assert len(subtasks) == 1
        assert "error handling" in subtasks[0].title.lower()

    def test_truncates_long_titles(self) -> None:
        output = json.dumps([{"title": "A" * 200, "description": "d"}])
        subtasks = _parse_subtasks_from_output(output, default_priority=2)
        assert len(subtasks) == 1
        assert len(subtasks[0].title) <= 80

    def test_skips_non_dict_entries(self) -> None:
        output = json.dumps(["not a dict", {"title": "Refactor authentication module", "description": "d"}])
        subtasks = _parse_subtasks_from_output(output, default_priority=2)
        assert len(subtasks) == 1

    def test_multiple_valid_subtasks(self) -> None:
        output = json.dumps([
            {"title": "Add retry logic to the query client", "description": "d1"},
            {"title": "Extract filter class from selection module", "description": "d2"},
            {"title": "Add integration tests for the pipeline", "description": "d3"},
        ])
        subtasks = _parse_subtasks_from_output(output, default_priority=0)
        assert len(subtasks) == 3
        assert all(s.priority == 0 for s in subtasks)


# ---------------------------------------------------------------------------
# _create_child_item
# ---------------------------------------------------------------------------


class TestCreateChildItem:
    """Tests for beads child item creation."""

    @patch(f"{_DECOMP}._run_bd")
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
        # Labels should contain DECOMPOSITION_LABEL
        labels_idx = args.index("--labels") + 1
        assert DECOMPOSITION_LABEL in args[labels_idx]

    @patch(f"{_DECOMP}._run_bd")
    def test_propagates_extra_labels(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd", "create"], 0, stdout='{"id": "child-1"}', stderr=""
        )
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        _create_child_item(subtask, parent_id="parent-1", extra_labels=["orchestrator", "config"])
        args = mock_run.call_args[0][0]
        labels_idx = args.index("--labels") + 1
        labels_val = args[labels_idx]
        assert "orchestrator" in labels_val
        assert "config" in labels_val
        assert DECOMPOSITION_LABEL in labels_val

    @patch(f"{_DECOMP}._run_bd")
    def test_returns_none_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd", "create"], 1, stdout="", stderr="error"
        )
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result is None

    @patch(f"{_DECOMP}._run_bd")
    def test_returns_none_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("bd", 30)
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result is None

    @patch(f"{_DECOMP}._run_bd")
    def test_handles_list_response(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd", "create"], 0, stdout='[{"id": "child-2"}]', stderr=""
        )
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result == "child-2"

    @patch(f"{_DECOMP}._run_bd")
    def test_handles_empty_json_response(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd", "create"], 0, stdout="", stderr=""
        )
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result is None

    @patch(f"{_DECOMP}._run_bd")
    def test_handles_called_process_error(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd", stderr="failed")
        subtask = SubTask(title="Sub A", description="Desc", priority=2)
        result = _create_child_item(subtask, parent_id="parent-1")
        assert result is None


# ---------------------------------------------------------------------------
# _add_blocking_dependency
# ---------------------------------------------------------------------------


class TestAddBlockingDependency:
    """Tests for sibling blocking relationship creation."""

    @patch(f"{_DECOMP}._run_bd")
    def test_adds_blocks_dep(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(["bd"], 0, stdout="", stderr="")
        assert _add_blocking_dependency("child-1", "child-2") is True
        args = mock_run.call_args[0][0]
        assert "update" in args
        assert "child-2" in args
        assert "blocks:child-1" in args

    @patch(f"{_DECOMP}._run_bd")
    def test_returns_false_on_failure(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd")
        assert _add_blocking_dependency("child-1", "child-2") is False

    @patch(f"{_DECOMP}._run_bd")
    def test_returns_false_on_timeout(self, mock_run: MagicMock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("bd", 15)
        assert _add_blocking_dependency("child-1", "child-2") is False


# ---------------------------------------------------------------------------
# _get_existing_child_titles
# ---------------------------------------------------------------------------


class TestGetExistingChildTitles:
    """Tests for dedup checking."""

    def test_returns_lowercased_titles(self) -> None:
        children = [
            _make_item(title="Add Login Endpoint"),
            _make_item(title="Add Signup"),
        ]
        with patch("pokepoke.beads.beads_hierarchy.get_children", return_value=children):
            titles = _get_existing_child_titles("parent-1")
        assert "add login endpoint" in titles
        assert "add signup" in titles

    def test_returns_empty_set_on_no_children(self) -> None:
        with patch("pokepoke.beads.beads_hierarchy.get_children", return_value=[]):
            titles = _get_existing_child_titles("parent-1")
        assert titles == set()

    def test_returns_empty_set_on_exception(self) -> None:
        with patch("pokepoke.beads.beads_hierarchy.get_children", side_effect=RuntimeError("boom")):
            titles = _get_existing_child_titles("parent-1")
        assert titles == set()


# ---------------------------------------------------------------------------
# _update_parent_metadata
# ---------------------------------------------------------------------------


class TestUpdateParentMetadata:
    """Tests for parent metadata updates after decomposition."""

    @patch(f"{_DECOMP}._run_bd")
    def test_sets_decomposed_flag_and_child_ids(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd"], 0,
            stdout='[{"id": "parent-1", "metadata": {}}]',
            stderr="",
        )
        result = _update_parent_metadata("parent-1", ["child-1", "child-2"])
        assert result is True
        update_call = mock_run.call_args_list[1]
        update_args = update_call[0][0]
        assert "update" in update_args
        assert "parent-1" in update_args
        meta_idx = update_args.index("--metadata") + 1
        metadata = json.loads(update_args[meta_idx])
        assert metadata["decomposed"] is True
        assert metadata["decomposition_child_ids"] == ["child-1", "child-2"]

    @patch(f"{_DECOMP}._run_bd")
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

    @patch(f"{_DECOMP}._run_bd")
    def test_adds_decomposition_label_when_missing(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd"], 0,
            stdout='[{"id": "parent-1", "labels": ["priority:1"], "metadata": {}}]',
            stderr="",
        )
        _update_parent_metadata("parent-1", ["child-1"])
        update_call = mock_run.call_args_list[1]
        update_args = update_call[0][0]
        assert "--add-label" in update_args
        label_idx = update_args.index("--add-label") + 1
        assert update_args[label_idx] == "auto-decomposed"

    @patch(f"{_DECOMP}._run_bd")
    def test_skips_label_add_when_already_present(self, mock_run: MagicMock) -> None:
        mock_run.return_value = subprocess.CompletedProcess(
            ["bd"], 0,
            stdout='[{"id": "parent-1", "labels": ["auto-decomposed"], "metadata": {}}]',
            stderr="",
        )
        _update_parent_metadata("parent-1", ["child-1"])
        update_call = mock_run.call_args_list[1]
        update_args = update_call[0][0]
        assert "--add-label" not in update_args

    @patch(f"{_DECOMP}._run_bd")
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

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.beads_management.add_comment")
    @patch(f"{_DECOMP}._update_parent_metadata")
    @patch(f"{_DECOMP}._add_blocking_dependency")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_success_creates_children_and_updates_parent(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_block: MagicMock,
        mock_update: MagicMock,
        mock_comment: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="Subtask A from SDK analysis", description="d1", priority=2),
            SubTask(title="Subtask B from SDK analysis", description="d2", priority=2),
            SubTask(title="Subtask C from SDK analysis", description="d3", priority=2),
        ]
        mock_create.side_effect = ["child-1", "child-2", "child-3"]
        mock_update.return_value = True

        result = run_decomposition(item, failure_count=3)

        assert result.success is True
        assert result.parent_id == "task-1"
        assert len(result.child_ids) == 3
        assert mock_create.call_count == 3
        mock_update.assert_called_once_with("task-1", ["child-1", "child-2", "child-3"])
        mock_comment.assert_called_once()

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.beads_management.add_comment")
    @patch(f"{_DECOMP}._update_parent_metadata")
    @patch(f"{_DECOMP}._add_blocking_dependency")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_creates_blocking_deps_between_siblings(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_block: MagicMock,
        mock_update: MagicMock,
        mock_comment: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="First subtask from analysis", description="d1", priority=2),
            SubTask(title="Second subtask from analysis", description="d2", priority=2),
            SubTask(title="Third subtask from analysis", description="d3", priority=2),
        ]
        mock_create.side_effect = ["child-1", "child-2", "child-3"]
        mock_update.return_value = True

        run_decomposition(item, failure_count=3)

        # child-1 blocks child-2, child-2 blocks child-3
        assert mock_block.call_count == 2
        mock_block.assert_any_call("child-1", "child-2")
        mock_block.assert_any_call("child-2", "child-3")

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.beads_management.add_comment")
    @patch(f"{_DECOMP}._update_parent_metadata")
    @patch(f"{_DECOMP}._add_blocking_dependency")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_partial_creation_still_succeeds(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_block: MagicMock,
        mock_update: MagicMock,
        mock_comment: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="Subtask Alpha from analysis", description="d1", priority=2),
            SubTask(title="Subtask Bravo from analysis", description="d2", priority=2),
            SubTask(title="Subtask Charlie from analysis", description="d3", priority=2),
        ]
        mock_create.side_effect = ["child-1", None, "child-3"]
        mock_update.return_value = True

        result = run_decomposition(item, failure_count=3)

        assert result.success is True
        assert len(result.child_ids) == 2
        assert "child-1" in result.child_ids
        assert "child-3" in result.child_ids

    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_fails_when_no_children_created(
        self, mock_sdk: MagicMock, mock_existing: MagicMock, mock_create: MagicMock,
    ) -> None:
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="Subtask A from SDK invocation", description="d1", priority=2),
        ]
        mock_create.return_value = None

        result = run_decomposition(item, failure_count=3)

        assert result.success is False
        assert result.child_ids == []

    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_fails_when_sdk_returns_no_subtasks(self, mock_sdk: MagicMock) -> None:
        item = _make_item()
        mock_sdk.return_value = []

        result = run_decomposition(item, failure_count=5)

        assert result.success is False
        assert "no valid subtasks" in result.reason.lower()

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.beads_management.add_comment")
    @patch(f"{_DECOMP}._update_parent_metadata")
    @patch(f"{_DECOMP}._add_blocking_dependency")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles")
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_dedup_drops_existing_children(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_block: MagicMock,
        mock_update: MagicMock,
        mock_comment: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="Add login endpoint to the API", description="d1", priority=2),
            SubTask(title="Add signup endpoint to the API", description="d2", priority=2),
        ]
        mock_existing.return_value = {"add login endpoint to the api"}
        mock_create.return_value = "child-1"
        mock_update.return_value = True

        result = run_decomposition(item, failure_count=3)

        assert result.success is True
        assert mock_create.call_count == 1  # only signup created

    @patch(f"{_DECOMP}._get_existing_child_titles")
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_dedup_skips_all_returns_failure(
        self, mock_sdk: MagicMock, mock_existing: MagicMock,
    ) -> None:
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="Already existing subtask title", description="d", priority=2),
        ]
        mock_existing.return_value = {"already existing subtask title"}

        result = run_decomposition(item, failure_count=3)

        assert result.success is False
        assert "already exist" in result.reason.lower()

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.beads_management.add_comment")
    @patch(f"{_DECOMP}._update_parent_metadata")
    @patch(f"{_DECOMP}._add_blocking_dependency")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_propagates_parent_labels(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_block: MagicMock,
        mock_update: MagicMock,
        mock_comment: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        item = _make_item(labels=["orchestrator", "config"])
        mock_sdk.return_value = [
            SubTask(title="Subtask with parent labels propagated", description="d", priority=2),
        ]
        mock_create.return_value = "child-1"
        mock_update.return_value = True

        run_decomposition(item, failure_count=3)

        call_kwargs = mock_create.call_args
        extra_labels = call_kwargs[1]["extra_labels"] if "extra_labels" in (call_kwargs[1] or {}) else call_kwargs[0][2] if len(call_kwargs[0]) > 2 else None
        # The call should pass parent labels (excluding auto-decomposed)
        assert extra_labels is not None
        assert "orchestrator" in extra_labels
        assert "config" in extra_labels

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.beads_management.add_comment")
    @patch(f"{_DECOMP}._update_parent_metadata")
    @patch(f"{_DECOMP}._add_blocking_dependency")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_comment_mentions_failure_count(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_block: MagicMock,
        mock_update: MagicMock,
        mock_comment: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="Add proper error handling module", description="d1", priority=2),
            SubTask(title="Fix validation in config loader", description="d2", priority=2),
        ]
        mock_create.side_effect = ["c-1", "c-2"]
        mock_update.return_value = True

        run_decomposition(item, failure_count=4)

        comment_text = mock_comment.call_args[0][1]
        assert "4 consecutive failures" in comment_text
        assert "c-1" in comment_text
        assert "c-2" in comment_text

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.beads_management.add_comment")
    @patch(f"{_DECOMP}._update_parent_metadata")
    @patch(f"{_DECOMP}._add_blocking_dependency")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_records_created_items_in_session_stats(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_block: MagicMock,
        mock_update: MagicMock,
        mock_comment: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        """Decomposed children must be reported so the dashboard ADDED counter updates."""
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="Implement user login flow", description="d1", priority=2),
            SubTask(title="Add password validation logic", description="d2", priority=2),
        ]
        mock_create.side_effect = ["child-1", "child-2"]
        mock_update.return_value = True

        run_decomposition(item, failure_count=3)

        mock_record.assert_called_once_with([
            ("child-1", "Implement user login flow"),
            ("child-2", "Add password validation logic"),
        ])

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_does_not_record_when_no_children_created(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        """When all child creation attempts fail, record_items_created is not called."""
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="A subtask that will fail creation", description="d1", priority=2),
        ]
        mock_create.return_value = None

        run_decomposition(item, failure_count=3)

        mock_record.assert_not_called()

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.beads_management.add_comment")
    @patch(f"{_DECOMP}._update_parent_metadata")
    @patch(f"{_DECOMP}._add_blocking_dependency")
    @patch(f"{_DECOMP}._create_child_item")
    @patch(f"{_DECOMP}._get_existing_child_titles", return_value=set())
    @patch(f"{_DECOMP}._invoke_sdk_for_decomposition")
    def test_records_only_successfully_created_items(
        self,
        mock_sdk: MagicMock,
        mock_existing: MagicMock,
        mock_create: MagicMock,
        mock_block: MagicMock,
        mock_update: MagicMock,
        mock_comment: MagicMock,
        mock_record: MagicMock,
    ) -> None:
        """Partial creation: only successfully created children are recorded."""
        item = _make_item()
        mock_sdk.return_value = [
            SubTask(title="Subtask that succeeds first", description="d1", priority=2),
            SubTask(title="Subtask that fails in middle", description="d2", priority=2),
            SubTask(title="Subtask that succeeds at end", description="d3", priority=2),
        ]
        mock_create.side_effect = ["child-1", None, "child-3"]
        mock_update.return_value = True

        run_decomposition(item, failure_count=3)

        mock_record.assert_called_once_with([
            ("child-1", "Subtask that succeeds first"),
            ("child-3", "Subtask that succeeds at end"),
        ])


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
