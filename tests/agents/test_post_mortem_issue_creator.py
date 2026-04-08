"""Tests for post_mortem_issue_creator module."""

import subprocess
from unittest.mock import patch

from pokepoke.agents.post_mortem_analyzer import FailurePattern
from pokepoke.agents.post_mortem_issue_creator import BeadsIssueCreator


def _make_pattern(**kwargs) -> FailurePattern:
    defaults = {
        "pattern_type": "tool_timeout",
        "description": "Tools timing out",
        "affected_items": ["task-1"],
        "frequency": 3,
        "severity": "P1",
        "sample_logs": ["log sample"],
        "suggested_fix": "increase timeout",
        "root_cause": "slow network",
    }
    defaults.update(kwargs)
    return FailurePattern(**defaults)


def _completed(stdout: str = "", stderr: str = "", rc: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


class TestBeadsIssueCreator:
    """Tests for BeadsIssueCreator."""

    def test_init_default_backend(self):
        creator = BeadsIssueCreator()
        assert creator.beads_backend == "bd"

    def test_init_custom_backend(self):
        creator = BeadsIssueCreator(beads_backend="br")
        assert creator.beads_backend == "br"

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_file_issues_empty_patterns(self, mock_bd):
        creator = BeadsIssueCreator()
        result = creator.file_issues([])
        assert result == []
        mock_bd.assert_not_called()

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_file_issues_creates_item(self, mock_bd):
        mock_bd.side_effect = [
            # _get_existing_post_mortem_items: list call returns empty
            _completed(stdout="[]"),
            # _create_beads_item: create call
            _completed(stdout="Created issue PM-001"),
            # _update_item_description: update call
            _completed(stdout="ok"),
        ]
        creator = BeadsIssueCreator()
        pattern = _make_pattern()
        result = creator.file_issues([pattern])
        assert result == ["PM-001"]

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_file_issues_skips_duplicate(self, mock_bd):
        existing = [{"id": "PM-001", "title": "tool_timeout issue", "status": "open", "description": ""}]
        import json
        mock_bd.side_effect = [
            _completed(stdout=json.dumps(existing)),
        ]
        creator = BeadsIssueCreator()
        pattern = _make_pattern(pattern_type="tool_timeout")
        result = creator.file_issues([pattern])
        assert result == []

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_file_issues_does_not_skip_closed_items(self, mock_bd):
        import json
        existing = [{"id": "PM-001", "title": "tool_timeout issue", "status": "closed", "description": ""}]
        mock_bd.side_effect = [
            _completed(stdout=json.dumps(existing)),
            _completed(stdout="Created issue PM-002"),
            _completed(stdout="ok"),
        ]
        creator = BeadsIssueCreator()
        pattern = _make_pattern(pattern_type="tool_timeout")
        result = creator.file_issues([pattern])
        assert result == ["PM-002"]

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_file_issues_handles_create_failure(self, mock_bd):
        mock_bd.side_effect = [
            _completed(stdout="[]"),
            _completed(stdout="", stderr="bd error", rc=1),
        ]
        creator = BeadsIssueCreator()
        result = creator.file_issues([_make_pattern()])
        assert result == []

    # ── _get_existing_post_mortem_items ──

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_existing_items_success(self, mock_bd):
        import json
        items = [{"id": "1", "title": "a"}]
        mock_bd.return_value = _completed(stdout=json.dumps(items))
        creator = BeadsIssueCreator()
        result = creator._get_existing_post_mortem_items()
        assert result == items

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_existing_items_empty_output(self, mock_bd):
        mock_bd.return_value = _completed(stdout="")
        creator = BeadsIssueCreator()
        assert creator._get_existing_post_mortem_items() == []

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_existing_items_filters_notes(self, mock_bd):
        import json
        output = "Note: database synced\n" + json.dumps([{"id": "1"}])
        mock_bd.return_value = _completed(stdout=output)
        creator = BeadsIssueCreator()
        result = creator._get_existing_post_mortem_items()
        assert result == [{"id": "1"}]

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_existing_items_bad_json(self, mock_bd):
        mock_bd.return_value = _completed(stdout="not json at all")
        creator = BeadsIssueCreator()
        assert creator._get_existing_post_mortem_items() == []

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_existing_items_nonzero_rc(self, mock_bd):
        mock_bd.return_value = _completed(stdout="", stderr="error", rc=1)
        creator = BeadsIssueCreator()
        assert creator._get_existing_post_mortem_items() == []

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_existing_items_exception(self, mock_bd):
        mock_bd.side_effect = Exception("network error")
        creator = BeadsIssueCreator()
        assert creator._get_existing_post_mortem_items() == []

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_existing_items_not_list(self, mock_bd):
        mock_bd.return_value = _completed(stdout='{"single": "object"}')
        creator = BeadsIssueCreator()
        assert creator._get_existing_post_mortem_items() == []

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_existing_items_all_note_lines(self, mock_bd):
        mock_bd.return_value = _completed(stdout="Note: synced\nWarning: stale\nHint: run init")
        creator = BeadsIssueCreator()
        assert creator._get_existing_post_mortem_items() == []

    # ── _is_duplicate ──

    def test_is_duplicate_no_existing(self):
        creator = BeadsIssueCreator()
        assert creator._is_duplicate(_make_pattern(), []) is False

    def test_is_duplicate_by_pattern_type_in_title(self):
        creator = BeadsIssueCreator()
        existing = [{"id": "1", "title": "tool_timeout detected", "status": "open", "description": ""}]
        assert creator._is_duplicate(_make_pattern(pattern_type="tool_timeout"), existing) is True

    def test_is_duplicate_by_affected_items(self):
        creator = BeadsIssueCreator()
        existing = [{"id": "1", "title": "some other title", "status": "open",
                      "description": "task-1 and task-2 were affected"}]
        pattern = _make_pattern(affected_items=["task-1", "task-2"])
        assert creator._is_duplicate(pattern, existing) is True

    def test_is_duplicate_low_overlap_not_duplicate(self):
        creator = BeadsIssueCreator()
        existing = [{"id": "1", "title": "other", "status": "open",
                      "description": "task-1 only"}]
        pattern = _make_pattern(affected_items=["task-1", "task-2", "task-3", "task-4"])
        assert creator._is_duplicate(pattern, existing) is False

    def test_is_duplicate_skips_closed(self):
        creator = BeadsIssueCreator()
        existing = [{"id": "1", "title": "tool_timeout issue", "status": "closed", "description": ""}]
        assert creator._is_duplicate(_make_pattern(pattern_type="tool_timeout"), existing) is False

    # ── _extract_item_id ──

    def test_extract_item_id_standard_format(self):
        creator = BeadsIssueCreator()
        assert creator._extract_item_id("Created issue PM-123") == "PM-123"

    def test_extract_item_id_item_keyword(self):
        creator = BeadsIssueCreator()
        assert creator._extract_item_id("Created item ABC-456") == "ABC-456"

    def test_extract_item_id_fallback_format(self):
        creator = BeadsIssueCreator()
        result = creator._extract_item_id("Done: someid123")
        assert result == "someid123"

    def test_extract_item_id_no_match(self):
        creator = BeadsIssueCreator()
        assert creator._extract_item_id("ok") is None

    # ── _update_item_description ──

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_update_description_success(self, mock_bd):
        mock_bd.return_value = _completed()
        creator = BeadsIssueCreator()
        assert creator._update_item_description("PM-1", "desc") is True

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_update_description_fallback_to_comment(self, mock_bd):
        mock_bd.side_effect = [
            _completed(rc=1, stderr="no --description flag"),
            _completed(rc=0),
        ]
        creator = BeadsIssueCreator()
        assert creator._update_item_description("PM-1", "desc") is True

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_update_description_both_fail(self, mock_bd):
        mock_bd.side_effect = [
            _completed(rc=1),
            _completed(rc=1),
        ]
        creator = BeadsIssueCreator()
        assert creator._update_item_description("PM-1", "desc") is False

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_update_description_exception(self, mock_bd):
        mock_bd.side_effect = Exception("boom")
        creator = BeadsIssueCreator()
        assert creator._update_item_description("PM-1", "desc") is False

    # ── _create_beads_item ──

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_create_beads_item_success(self, mock_bd):
        mock_bd.side_effect = [
            _completed(stdout="Created issue NEW-1"),
            _completed(),  # update description
        ]
        creator = BeadsIssueCreator()
        assert creator._create_beads_item(_make_pattern()) == "NEW-1"

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_create_beads_item_no_id_in_output(self, mock_bd):
        mock_bd.return_value = _completed(stdout="ok")
        creator = BeadsIssueCreator()
        assert creator._create_beads_item(_make_pattern()) is None

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_create_beads_item_exception(self, mock_bd):
        mock_bd.side_effect = Exception("connection lost")
        creator = BeadsIssueCreator()
        assert creator._create_beads_item(_make_pattern()) is None

    # ── get_created_items_info ──

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_created_items_info_empty(self, mock_bd):
        creator = BeadsIssueCreator()
        assert creator.get_created_items_info([]) == []
        mock_bd.assert_not_called()

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_created_items_info_success(self, mock_bd):
        import json
        mock_bd.return_value = _completed(stdout=json.dumps({"id": "1", "title": "t"}))
        creator = BeadsIssueCreator()
        result = creator.get_created_items_info(["1"])
        assert len(result) == 1
        assert result[0]["id"] == "1"

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_created_items_info_filters_notes(self, mock_bd):
        import json
        output = "Note: synced\n" + json.dumps({"id": "1"})
        mock_bd.return_value = _completed(stdout=output)
        creator = BeadsIssueCreator()
        result = creator.get_created_items_info(["1"])
        assert len(result) == 1

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_created_items_info_bad_json(self, mock_bd):
        mock_bd.return_value = _completed(stdout="not json")
        creator = BeadsIssueCreator()
        assert creator.get_created_items_info(["1"]) == []

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_created_items_info_nonzero_rc(self, mock_bd):
        mock_bd.return_value = _completed(rc=1)
        creator = BeadsIssueCreator()
        assert creator.get_created_items_info(["1"]) == []

    @patch("pokepoke.agents.post_mortem_issue_creator._run_bd")
    def test_get_created_items_info_exception(self, mock_bd):
        mock_bd.side_effect = Exception("fail")
        creator = BeadsIssueCreator()
        assert creator.get_created_items_info(["1"]) == []
