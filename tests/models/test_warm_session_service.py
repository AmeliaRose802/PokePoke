"""Tests for warm_session_service module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pokepoke.models.warm_session_service import (
    _build_exploration_prompt,
    _generate_warm_session_id,
    refresh_pool_after_merge,
    warm_session_for_label,
    warm_up_pool,
)


class TestGenerateWarmSessionId:
    def test_returns_prefixed_string(self):
        result = _generate_warm_session_id("orchestrator")
        assert result.startswith("warm-orchestrator-")

    def test_lowercases_label(self):
        result = _generate_warm_session_id("Orchestrator")
        assert "orchestrator" in result

    def test_unique_ids(self):
        a = _generate_warm_session_id("x")
        b = _generate_warm_session_id("x")
        # Timestamps are int seconds, so may be equal in fast tests
        assert a.startswith("warm-x-")
        assert b.startswith("warm-x-")

class TestBuildExplorationPrompt:
    @patch("pokepoke.models.warm_session_service.PromptService")
    def test_returns_rendered_prompt(self, mock_cls):
        svc = MagicMock()
        svc.load_and_render.return_value = "rendered"
        mock_cls.return_value = svc

        result = _build_exploration_prompt("orchestrator", "explore-tpl")

        assert result == "rendered"
        svc.load_and_render.assert_called_once_with("explore-tpl", {"label": "orchestrator"})

@pytest.mark.asyncio
class TestWarmSessionForLabel:

    @patch("pokepoke.models.warm_session_service.get_config")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_returns_none_when_disabled(self, mock_pool_getter, mock_cfg):
        pool = MagicMock()
        pool.enabled = False
        mock_pool_getter.return_value = pool

        result = await warm_session_for_label("test-label")

        assert result is None

    @patch("pokepoke.models.warm_session_service.get_config")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_returns_none_when_warming_in_progress(self, mock_pool_getter, mock_cfg):
        pool = MagicMock()
        pool.enabled = True
        pool.mark_warming_in_progress.return_value = False
        mock_pool_getter.return_value = pool

        result = await warm_session_for_label("test-label")

        assert result is None

    @patch("pokepoke.models.warm_session_service._build_exploration_prompt", return_value="explore prompt")
    @patch("pokepoke.models.warm_session_service.get_config")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_success_registers_session(self, mock_pool_getter, mock_cfg, mock_build):
        pool = MagicMock()
        pool.enabled = True
        pool.mark_warming_in_progress.return_value = True
        warm_session = MagicMock()
        warm_session.session_id = "warm-test-123"
        pool.register_session.return_value = warm_session
        mock_pool_getter.return_value = pool

        cfg = MagicMock()
        cfg.warm_sessions.exploration_prompt_template = "explore-tpl"
        mock_cfg.return_value = cfg

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.stats = MagicMock(input_tokens=100, output_tokens=50)

        with patch("pokepoke.models.copilot_sdk.invoke_copilot_sdk", new_callable=AsyncMock, return_value=mock_result):
            result = await warm_session_for_label("test-label", cwd="/tmp", timeout=30.0)

        assert result == warm_session
        pool.register_session.assert_called_once()

    @patch("pokepoke.models.warm_session_service._build_exploration_prompt", return_value="explore prompt")
    @patch("pokepoke.models.warm_session_service.get_config")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_failure_clears_warming(self, mock_pool_getter, mock_cfg, mock_build):
        pool = MagicMock()
        pool.enabled = True
        pool.mark_warming_in_progress.return_value = True
        mock_pool_getter.return_value = pool

        cfg = MagicMock()
        cfg.warm_sessions.exploration_prompt_template = "explore-tpl"
        mock_cfg.return_value = cfg

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "exploration failed"

        with patch("pokepoke.models.copilot_sdk.invoke_copilot_sdk", new_callable=AsyncMock, return_value=mock_result):
            result = await warm_session_for_label("test-label")

        assert result is None
        pool.clear_warming_in_progress.assert_called_once_with("test-label")

    @patch("pokepoke.models.warm_session_service._build_exploration_prompt", side_effect=Exception("boom"))
    @patch("pokepoke.models.warm_session_service.get_config")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_exception_clears_warming(self, mock_pool_getter, mock_cfg, mock_build):
        pool = MagicMock()
        pool.enabled = True
        pool.mark_warming_in_progress.return_value = True
        mock_pool_getter.return_value = pool

        cfg = MagicMock()
        cfg.warm_sessions.exploration_prompt_template = "explore-tpl"
        mock_cfg.return_value = cfg

        result = await warm_session_for_label("test-label")

        assert result is None
        pool.clear_warming_in_progress.assert_called_once_with("test-label")

@pytest.mark.asyncio
class TestWarmUpPool:

    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_returns_empty_when_disabled(self, mock_pool_getter):
        pool = MagicMock()
        pool.enabled = False
        mock_pool_getter.return_value = pool

        result = await warm_up_pool()

        assert result == {}

    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_returns_empty_when_all_valid(self, mock_pool_getter):
        pool = MagicMock()
        pool.enabled = True
        pool.get_labels_needing_warmup.return_value = []
        mock_pool_getter.return_value = pool

        result = await warm_up_pool()

        assert result == {}

    @patch("pokepoke.models.warm_session_service.warm_session_for_label")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_warms_labels(self, mock_pool_getter, mock_warm):
        pool = MagicMock()
        pool.enabled = True
        pool.get_labels_needing_warmup.return_value = ["label-a"]
        mock_pool_getter.return_value = pool

        warm_session = MagicMock()
        mock_warm.return_value = warm_session

        result = await warm_up_pool(cwd="/cwd", timeout_per_label=60.0)

        assert result == {"label-a": warm_session}
        mock_warm.assert_called_once_with("label-a", cwd="/cwd", timeout=60.0)

    @patch("pokepoke.models.warm_session_service.warm_session_for_label", side_effect=Exception("fail"))
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    async def test_handles_label_failure(self, mock_pool_getter, mock_warm):
        pool = MagicMock()
        pool.enabled = True
        pool.get_labels_needing_warmup.return_value = ["label-a"]
        mock_pool_getter.return_value = pool

        result = await warm_up_pool()

        assert result == {"label-a": None}

class TestRefreshPoolAfterMerge:
    @patch("pokepoke.models.warm_session_service.get_config")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    def test_noop_when_disabled(self, mock_pool_getter, mock_cfg):
        pool = MagicMock()
        pool.enabled = False
        mock_pool_getter.return_value = pool

        refresh_pool_after_merge()

        pool.invalidate_all.assert_not_called()

    @patch("pokepoke.models.warm_session_service.get_config")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    def test_noop_when_refresh_disabled(self, mock_pool_getter, mock_cfg):
        pool = MagicMock()
        pool.enabled = True
        mock_pool_getter.return_value = pool
        cfg = MagicMock()
        cfg.warm_sessions.refresh_on_merge = False
        mock_cfg.return_value = cfg

        refresh_pool_after_merge()

        pool.invalidate_all.assert_not_called()

    @patch("pokepoke.models.warm_session_service.get_config")
    @patch("pokepoke.models.warm_session_service.get_warm_session_pool")
    def test_invalidates_when_enabled(self, mock_pool_getter, mock_cfg):
        pool = MagicMock()
        pool.enabled = True
        pool.invalidate_all.return_value = 3
        mock_pool_getter.return_value = pool
        cfg = MagicMock()
        cfg.warm_sessions.refresh_on_merge = True
        mock_cfg.return_value = cfg

        refresh_pool_after_merge()

        pool.invalidate_all.assert_called_once()

