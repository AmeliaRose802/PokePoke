"""Tests for beads statistics tracking."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.beads.beads import get_beads_stats


class TestGetBeadsStats:
    """Test get_beads_stats function."""

    @patch('pokepoke.beads.beads_query._get_main_repo_root', return_value=Path('/fake/repo'))
    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_beads_stats_success(self, mock_run: Mock, _mock_root: Mock) -> None:
        """Test successful beads stats retrieval."""
        mock_run.return_value = Mock(
            stdout=json.dumps({
                "summary": {
                    "total_issues": 50,
                    "open_issues": 30,
                    "in_progress_issues": 5,
                    "closed_issues": 15,
                    "ready_issues": 25
                }
            }),
            returncode=0
        )

        result = get_beads_stats()

        assert result is not None
        assert result.total_issues == 50
        assert result.open_issues == 30
        assert result.in_progress_issues == 5
        assert result.closed_issues == 15
        assert result.ready_issues == 25

    @patch('pokepoke.beads.beads_query._get_main_repo_root', return_value=Path('/fake/repo'))
    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_beads_stats_missing_fields(self, mock_run: Mock, _mock_root: Mock) -> None:
        """Test beads stats with missing fields defaults to 0."""
        mock_run.return_value = Mock(
            stdout=json.dumps({
                "summary": {
                    "total_issues": 10
                    # Other fields missing
                }
            }),
            returncode=0
        )

        result = get_beads_stats()

        assert result is not None
        assert result.total_issues == 10
        assert result.open_issues == 0
        assert result.in_progress_issues == 0
        assert result.closed_issues == 0
        assert result.ready_issues == 0

    @patch('pokepoke.beads.beads_query._get_main_repo_root', return_value=Path('/fake/repo'))
    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_beads_stats_command_failure(self, mock_run: Mock, _mock_root: Mock) -> None:
        """Test beads stats returns None on command failure."""
        mock_run.side_effect = Exception("Command failed")

        result = get_beads_stats()

        assert result is None

    @patch('pokepoke.beads.beads_query._get_main_repo_root', return_value=Path('/fake/repo'))
    @patch('pokepoke.beads.beads_query._run_bd')
    def test_get_beads_stats_invalid_json(self, mock_run: Mock, _mock_root: Mock) -> None:
        """Test beads stats returns None on invalid JSON."""
        mock_run.return_value = Mock(
            stdout="not valid json",
            returncode=0
        )

        result = get_beads_stats()

        assert result is None
