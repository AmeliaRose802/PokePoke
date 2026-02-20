"""Tests for prompt_operations module."""

from unittest.mock import MagicMock, patch


class TestListPrompts:
    def test_list_prompts_delegates_to_service(self):
        """list_prompts should delegate to PromptService.list_prompts."""
        mock_service = MagicMock()
        mock_service.list_prompts.return_value = [{"name": "work-item"}]

        with patch("pokepoke.prompts.get_prompt_service", return_value=mock_service):
            from pokepoke.prompt_operations import list_prompts
            result = list_prompts()

        assert result == [{"name": "work-item"}]
        mock_service.list_prompts.assert_called_once()


class TestGetPrompt:
    def test_get_prompt_delegates_to_service(self):
        """get_prompt should delegate to PromptService.get_prompt_metadata."""
        mock_service = MagicMock()
        mock_service.get_prompt_metadata.return_value = {"name": "work-item", "content": "..."}

        with patch("pokepoke.prompts.get_prompt_service", return_value=mock_service):
            from pokepoke.prompt_operations import get_prompt
            result = get_prompt("work-item")

        assert result == {"name": "work-item", "content": "..."}
        mock_service.get_prompt_metadata.assert_called_once_with("work-item")


class TestSavePrompt:
    def test_save_prompt_delegates_to_service(self):
        """save_prompt should delegate to PromptService.save_prompt."""
        mock_service = MagicMock()
        mock_service.save_prompt.return_value = {"path": "/some/path", "saved": True}

        with patch("pokepoke.prompts.get_prompt_service", return_value=mock_service):
            from pokepoke.prompt_operations import save_prompt
            result = save_prompt("work-item", "new content")

        assert result == {"path": "/some/path", "saved": True}
        mock_service.save_prompt.assert_called_once_with("work-item", "new content")


class TestResetPrompt:
    def test_reset_prompt_delegates_to_service(self):
        """reset_prompt should delegate to PromptService.reset_prompt."""
        mock_service = MagicMock()
        mock_service.reset_prompt.return_value = {"reset": True, "had_override": True}

        with patch("pokepoke.prompts.get_prompt_service", return_value=mock_service):
            from pokepoke.prompt_operations import reset_prompt
            result = reset_prompt("work-item")

        assert result == {"reset": True, "had_override": True}
        mock_service.reset_prompt.assert_called_once_with("work-item")
