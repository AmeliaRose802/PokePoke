"""Tests for pokepoke.models.model_sync_beads module."""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from pokepoke.models.model_sync_beads import (
    _build_issue_description,
    _build_issue_title,
    _build_model_metadata,
    _find_model_items,
    _list_existing_model_items,
    _prune_unavailable_models,
    _sync_beads_items,
)
from pokepoke.models.model_sync_parsing import CopilotModelSnapshot


def _make_model(name="gpt-5", **kwargs):
    defaults = {
        "name": name, "status": "beta", "version": "1.0",
        "context_window": 128000, "capabilities": ["chat"],
        "tags": ["preview"], "pricing": {"input": 0.01},
    }
    defaults.update(kwargs)
    return CopilotModelSnapshot(**defaults)


class TestBuildIssueTitle:
    def test_basic(self):
        assert _build_issue_title("gpt-5") == "Beta test Copilot model: gpt-5"


class TestBuildIssueDescription:
    def test_all_fields(self):
        model = _make_model()
        desc = _build_issue_description(model, "2026-01-01T00:00:00")
        assert "gpt-5" in desc
        assert "2026-01-01" in desc
        assert "128,000 tokens" in desc
        assert "chat" in desc
        assert "preview" in desc
        assert "0.01" in desc

    def test_minimal_fields(self):
        model = CopilotModelSnapshot(
            name="m1", status=None, version=None,
            context_window=None, capabilities=None, tags=None, pricing=None,
        )
        desc = _build_issue_description(model, "2026-01-01")
        assert "m1" in desc


class TestBuildModelMetadata:
    def test_structure(self):
        model = _make_model()
        meta = _build_model_metadata(model, "2026-01-01", "2026-01-02")
        assert meta["copilot_model"] == "gpt-5"
        assert meta["model_sync"]["discovered_at"] == "2026-01-01"
        assert meta["model_sync"]["last_seen"] == "2026-01-02"
        assert meta["model_sync"]["context_window"] == 128000


class TestListExistingModelItems:
    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_success(self, mock_bd):
        mock_bd.return_value = MagicMock(
            returncode=0, stdout=json.dumps([{"id": "x", "title": "item"}])
        )
        result = _list_existing_model_items()
        assert result == [{"id": "x", "title": "item"}]

    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_failure(self, mock_bd):
        mock_bd.return_value = MagicMock(returncode=1, stdout="")
        result = _list_existing_model_items()
        assert result == []

    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_non_list_response(self, mock_bd):
        mock_bd.return_value = MagicMock(returncode=0, stdout='{"not": "a list"}')
        result = _list_existing_model_items()
        assert result == []


class TestFindModelItems:
    def test_by_metadata(self):
        items = [{"id": "1", "title": "x", "metadata": {"copilot_model": "gpt-5"}}]
        result = _find_model_items(items)
        assert "gpt-5" in result

    def test_by_title_fallback(self):
        items = [{"id": "2", "title": "Beta test Copilot model: claude-4", "metadata": {}}]
        result = _find_model_items(items)
        assert "claude-4" in result

    def test_no_match(self):
        items = [{"id": "3", "title": "Unrelated item", "metadata": {}}]
        result = _find_model_items(items)
        assert result == {}


class TestSyncBeadsItems:
    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.sdk_beads_tracker.parse_created_items", return_value=[])
    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_creates_new_item(self, mock_bd, mock_parse, mock_record):
        mock_bd.return_value = MagicMock(returncode=0, stdout="", stderr="")
        model = _make_model()
        sync_cfg = MagicMock(beta_only=False, labels=["beta"], issue_type="task", priority=2)
        created, updated = _sync_beads_items(
            [model], sync_cfg, {}, datetime(2026, 1, 1), None, None,
        )
        assert "gpt-5" in created
        assert updated == []

    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_updates_existing_item(self, mock_bd):
        mock_bd.return_value = MagicMock(returncode=0, stdout="", stderr="")
        model = _make_model()
        existing = {"gpt-5": {"id": "item-1", "title": "Beta test Copilot model: gpt-5"}}
        sync_cfg = MagicMock(beta_only=False, labels=[], issue_type="task", priority=2)
        created, updated = _sync_beads_items(
            [model], sync_cfg, existing, datetime(2026, 1, 1), None, None,
        )
        assert created == []
        assert "gpt-5" in updated

    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_skips_non_beta_when_beta_only(self, mock_bd):
        model = _make_model(status="stable")
        sync_cfg = MagicMock(beta_only=True, include_preview=False, labels=[], issue_type="task", priority=2)
        created, _ = _sync_beads_items(
            [model], sync_cfg, {}, datetime(2026, 1, 1), None, None,
        )
        assert created == []
        mock_bd.assert_not_called()

    @patch("pokepoke.beads.sdk_beads_tracker.record_items_created")
    @patch("pokepoke.beads.sdk_beads_tracker.parse_created_items", return_value=[])
    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_logs_create_failure(self, mock_bd, mock_parse, mock_record):
        mock_bd.return_value = MagicMock(returncode=1, stdout="", stderr="error msg")
        model = _make_model()
        sync_cfg = MagicMock(beta_only=False, labels=[], issue_type="task", priority=2)
        logger = MagicMock()
        created, _updated = _sync_beads_items(
            [model], sync_cfg, {}, datetime(2026, 1, 1), None, logger,
        )
        assert created == []
        logger.log.assert_called()


class TestPruneUnavailableModels:
    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_closes_removed_models(self, mock_bd):
        mock_bd.return_value = MagicMock(returncode=0, stderr="")
        existing = {"old-model": {"id": "item-99"}}
        closed = _prune_unavailable_models({"old-model"}, existing, None, None)
        assert "old-model" in closed

    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_skips_missing_items(self, mock_bd):
        closed = _prune_unavailable_models({"ghost"}, {}, None, None)
        assert closed == []
        mock_bd.assert_not_called()

    @patch("pokepoke.models.model_sync_beads._run_bd")
    def test_skips_items_without_id(self, mock_bd):
        existing = {"no-id": {"title": "No ID item"}}
        closed = _prune_unavailable_models({"no-id"}, existing, None, None)
        assert closed == []
        mock_bd.assert_not_called()
