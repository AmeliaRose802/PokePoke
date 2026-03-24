import pytest

"""Tests for subprocess encoding edge cases and Unicode handling.

Verifies that subprocess invocations across the codebase handle non-ASCII,
emoji, and bytes invalid in cp1252 (e.g. 0x9d) gracefully via UTF-8
encoding with errors='replace'.  Prevents regressions like the
UnicodeDecodeError in _readerthread seen in production.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# 1. Subprocess pipes configured with UTF-8 encoding and errors='replace'
# ---------------------------------------------------------------------------

@pytest.mark.allow_real_bd
class TestSubprocessEncodingConfig:
    """Verify subprocess calls pass encoding='utf-8' and errors='replace'."""

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_check_copilot_processes_uses_utf8_with_replace(self, mock_run, mock_os):
        """process_utils.check_copilot_processes uses encoding='utf-8' and errors='replace'."""
        import pokepoke.utils.process_utils as mod
        mod._copilot_process_cache = None  # reset cache
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')

        from pokepoke.utils.process_utils import check_copilot_processes
        check_copilot_processes()

        _, kwargs = mock_run.call_args
        assert kwargs['encoding'] == 'utf-8'
        assert kwargs['errors'] == 'replace'

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_run_bd_uses_utf8_with_replace(self, mock_run):
        """beads_query._run_bd uses encoding='utf-8' and errors='replace'."""
        mock_run.return_value = MagicMock(stdout='[]')

        from pokepoke.beads.beads_query import _run_bd
        _run_bd(['ready', '--json'])

        _, kwargs = mock_run.call_args
        assert kwargs['encoding'] == 'utf-8'
        assert kwargs['errors'] == 'replace'

    @patch('pokepoke.beads.beads_item_stats_backfill.subprocess.run')
    def test_get_all_beads_items_uses_utf8_with_replace(self, mock_run):
        """beads_item_stats_backfill._get_all_beads_items uses encoding='utf-8' and errors='replace'."""
        mock_run.return_value = MagicMock(stdout='[]')

        from pokepoke.beads.beads_item_stats_backfill import _get_all_beads_items
        _get_all_beads_items()

        _, kwargs = mock_run.call_args
        assert kwargs['encoding'] == 'utf-8'
        assert kwargs['errors'] == 'replace'

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_run_git_status_with_retry_uses_utf8_with_replace(self, mock_run):
        """git_helpers._run_git_status_with_retry uses encoding='utf-8' and errors='replace'."""
        mock_run.return_value = MagicMock(stdout='', returncode=0)

        from pokepoke.git.git_helpers import _run_git_status_with_retry
        _run_git_status_with_retry(['git', 'status', '--porcelain'])

        _, kwargs = mock_run.call_args
        assert kwargs['encoding'] == 'utf-8'
        assert kwargs['errors'] == 'replace'


# ---------------------------------------------------------------------------
# 2. Output containing emoji, Unicode, and bytes invalid in cp1252
# ---------------------------------------------------------------------------

@pytest.mark.allow_real_bd
class TestUnicodeOutputHandling:
    """Subprocess output with emoji and extended Unicode is handled correctly."""

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_emoji_in_tasklist_output(self, mock_run, mock_os):
        """tasklist output containing emoji doesn't crash."""
        import pokepoke.utils.process_utils as mod
        mod._copilot_process_cache = None
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(
            stdout='"Image Name","PID"\n"copilot\U0001f680.exe","1234"'
        )

        from pokepoke.utils.process_utils import check_copilot_processes
        result = check_copilot_processes()
        assert result == 1

    @patch('pokepoke.beads.beads_item_stats_backfill.subprocess.run')
    def test_emoji_in_beads_output(self, mock_run):
        """beads JSON output with emoji titles parses correctly."""
        items = [{"id": "PK-1", "title": "Fix 🚀 rocket bug", "status": "open"}]
        mock_run.return_value = MagicMock(stdout=json.dumps(items))

        from pokepoke.beads.beads_item_stats_backfill import _get_all_beads_items
        result = _get_all_beads_items()
        assert len(result) == 1
        assert "\U0001f680" in result[0]["title"]

    @patch('pokepoke.beads.beads_item_stats_backfill.subprocess.run')
    def test_cjk_characters_in_beads_output(self, mock_run):
        """CJK characters in beads output parse correctly."""
        items = [{"id": "PK-2", "title": "\u4fee\u590d\u4e2d\u6587\u95ee\u9898", "status": "open"}]
        mock_run.return_value = MagicMock(stdout=json.dumps(items, ensure_ascii=False))

        from pokepoke.beads.beads_item_stats_backfill import _get_all_beads_items
        result = _get_all_beads_items()
        assert len(result) == 1
        assert result[0]["title"] == "\u4fee\u590d\u4e2d\u6587\u95ee\u9898"

    @patch('pokepoke.beads.beads_item_stats_backfill.subprocess.run')
    def test_replacement_char_in_beads_output(self, mock_run):
        """U+FFFD replacement characters (from errors='replace') in output don't crash JSON parsing."""
        # Simulate what errors='replace' produces for invalid bytes
        items = [{"id": "PK-3", "title": "item with \ufffd replaced bytes"}]
        mock_run.return_value = MagicMock(stdout=json.dumps(items, ensure_ascii=False))

        from pokepoke.beads.beads_item_stats_backfill import _get_all_beads_items
        result = _get_all_beads_items()
        assert len(result) == 1
        assert "\ufffd" in result[0]["title"]

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_beads_query_handles_emoji_json(self, mock_run):
        """_parse_beads_json handles emoji in JSON values."""
        from pokepoke.beads.beads_query import _parse_beads_json

        raw = json.dumps([{"id": "PK-4", "title": "Deploy \U0001f389 feature \u2705"}])
        result = _parse_beads_json(raw)
        assert result is not None
        assert "\U0001f389" in result[0]["title"]

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_git_status_with_unicode_filenames(self, mock_run):
        """git status output with Unicode filenames doesn't crash."""
        mock_run.return_value = MagicMock(
            stdout='M  src/donn\u00e9es.py\n?? \u30d5\u30a1\u30a4\u30eb.txt\n',
            returncode=0,
        )
        from pokepoke.git.git_helpers import _run_git_status_with_retry
        result = _run_git_status_with_retry(['git', 'status', '--porcelain'])
        assert 'donn\u00e9es' in result.stdout


# ---------------------------------------------------------------------------
# 3. errors='replace' fallback so reader threads never crash
# ---------------------------------------------------------------------------

@pytest.mark.allow_real_bd
class TestErrorsReplaceFallback:
    """Verify that errors='replace' prevents UnicodeDecodeError in _readerthread."""

    def test_subprocess_replace_mode_handles_invalid_cp1252_byte(self):
        """bytes invalid in cp1252 (0x9d) are replaced, not raised.

        This reproduces the production UnicodeDecodeError in _readerthread.
        When Python's subprocess uses cp1252 on Windows without errors='replace',
        byte 0x9d triggers UnicodeDecodeError.  With errors='replace' it becomes U+FFFD.
        """
        raw = b'hello \x9d world'
        decoded = raw.decode('utf-8', errors='replace')
        assert '\ufffd' in decoded
        assert 'hello' in decoded
        assert 'world' in decoded

    def test_subprocess_replace_mode_handles_mixed_invalid_bytes(self):
        """Multiple invalid byte sequences are all replaced."""
        raw = b'start \x80\x81\x9d\xff end'
        decoded = raw.decode('utf-8', errors='replace')
        assert 'start' in decoded
        assert 'end' in decoded
        # Each invalid byte becomes a replacement char
        assert decoded.count('\ufffd') >= 4

    def test_subprocess_replace_mode_preserves_valid_utf8(self):
        """Valid UTF-8 sequences pass through unmodified."""
        raw = 'emoji: \U0001f680 text: caf\u00e9 r\u00e9sum\u00e9'.encode()
        decoded = raw.decode('utf-8', errors='replace')
        assert '\U0001f680' in decoded
        assert 'caf\u00e9' in decoded
        assert 'r\u00e9sum\u00e9' in decoded

    def test_subprocess_replace_mode_handles_null_bytes(self):
        """Null bytes in subprocess output don't crash."""
        raw = b'before\x00after'
        decoded = raw.decode('utf-8', errors='replace')
        assert 'before' in decoded
        assert 'after' in decoded

    @patch('pokepoke.utils.process_utils.os')
    @patch('pokepoke.utils.process_utils.subprocess.run')
    def test_tasklist_with_0x9d_byte_in_output(self, mock_run, mock_os):
        """Simulates tasklist returning output with invalid cp1252 byte 0x9d.

        With errors='replace', the byte is replaced and the function returns
        a count instead of crashing with UnicodeDecodeError.
        """
        import pokepoke.utils.process_utils as mod
        mod._copilot_process_cache = None
        mock_os.name = 'nt'
        # Simulate already-decoded output (errors='replace' would have run)
        mock_run.return_value = MagicMock(
            stdout='"Image Name","PID"\n"copilot\ufffd.exe","1234"'
        )

        from pokepoke.utils.process_utils import check_copilot_processes
        result = check_copilot_processes()
        assert result == 1


# ---------------------------------------------------------------------------
# 4. Downstream consumers handle None/empty output from failed reads
# ---------------------------------------------------------------------------

@pytest.mark.allow_real_bd
class TestNoneAndEmptyOutputHandling:
    """Consumers of subprocess output handle None/empty strings without crashing."""

    def test_parse_beads_json_returns_none_for_empty_string(self):
        """_parse_beads_json returns None for empty string."""
        from pokepoke.beads.beads_query import _parse_beads_json
        assert _parse_beads_json("") is None

    def test_parse_beads_json_returns_none_for_whitespace(self):
        """_parse_beads_json returns None for whitespace-only string."""
        from pokepoke.beads.beads_query import _parse_beads_json
        assert _parse_beads_json("   \n  ") is None

    def test_parse_beads_json_returns_none_for_warning_only(self):
        """_parse_beads_json returns None when output is only warnings."""
        from pokepoke.beads.beads_query import _parse_beads_json
        assert _parse_beads_json("Warning: something went wrong\nNote: try again") is None

    @patch('pokepoke.beads.beads_item_stats_backfill.subprocess.run')
    def test_get_all_beads_items_returns_empty_on_non_list_json(self, mock_run):
        """_get_all_beads_items returns [] when JSON output is not a list."""
        mock_run.return_value = MagicMock(stdout='{"not": "a list"}')

        from pokepoke.beads.beads_item_stats_backfill import _get_all_beads_items
        result = _get_all_beads_items()
        assert result == []

    @patch('pokepoke.beads.beads_item_stats_backfill.subprocess.run')
    def test_get_all_beads_items_returns_empty_on_invalid_json(self, mock_run):
        """_get_all_beads_items returns [] when output is not valid JSON."""
        mock_run.return_value = MagicMock(stdout='not json at all \ufffd\ufffd')

        from pokepoke.beads.beads_item_stats_backfill import _get_all_beads_items
        result = _get_all_beads_items()
        assert result == []

    @patch('pokepoke.beads.beads_item_stats_backfill.subprocess.run')
    def test_get_all_beads_items_returns_empty_on_empty_stdout(self, mock_run):
        """_get_all_beads_items returns [] when stdout is empty."""
        mock_run.return_value = MagicMock(stdout='')

        from pokepoke.beads.beads_item_stats_backfill import _get_all_beads_items
        result = _get_all_beads_items()
        assert result == []

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_ready_work_items_handles_empty_stdout(self, mock_run):
        """get_ready_work_items returns [] for empty stdout."""
        mock_run.return_value = MagicMock(stdout='', returncode=0)

        from pokepoke.beads.beads_query import get_ready_work_items
        result = get_ready_work_items()
        assert result == []

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_ready_work_items_handles_replacement_chars_in_json(self, mock_run):
        """get_ready_work_items handles U+FFFD from errors='replace' in otherwise valid JSON."""
        items = [{"id": "PK-5", "title": "item \ufffd ok", "status": "ready",
                  "priority": 1, "issue_type": "task"}]
        mock_run.return_value = MagicMock(
            stdout=json.dumps(items, ensure_ascii=False),
            returncode=0,
        )

        from pokepoke.beads.beads_query import get_ready_work_items
        result = get_ready_work_items()
        assert len(result) == 1
        assert "\ufffd" in result[0].title

    def test_backfill_handles_empty_beads_db(self, tmp_path):
        """backfill_from_beads_db handles empty item list without crashing."""
        stats_file = tmp_path / "beads_item_stats.json"
        stats_file.write_text(json.dumps({
            "log": [],
            "summary": {"total_created": 0, "total_completed": 0, "net_delta": 0, "by_agent_type": {}},
        }))

        with patch("pokepoke.beads.beads_item_stats_backfill._get_all_beads_items") as mock_items:
            mock_items.return_value = []

            from pokepoke.beads.beads_item_stats_backfill import backfill_from_beads_db
            result = backfill_from_beads_db(stats_path=stats_file, silent=True)

        assert result["backfilled"] == 0
        assert result["already_complete"] is True

    def test_backfill_handles_unicode_in_created_by(self, tmp_path):
        """backfill handles Unicode characters in item created_by field."""
        stats_file = tmp_path / "beads_item_stats.json"
        stats_file.write_text(json.dumps({
            "log": [],
            "summary": {"total_created": 0, "total_completed": 0, "net_delta": 0, "by_agent_type": {}},
        }))

        with patch("pokepoke.beads.beads_item_stats_backfill._get_all_beads_items") as mock_items:
            mock_items.return_value = [
                {"id": "PK-6", "title": "Unicode test 🎉", "created_by": "用户 Amélie", "created_at": "2024-01-01T00:00:00Z"},
            ]

            from pokepoke.beads.beads_item_stats_backfill import backfill_from_beads_db
            result = backfill_from_beads_db(stats_path=stats_file, silent=True)

        assert result["backfilled"] == 1

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_ready_work_items_handles_subprocess_crash(self, mock_run):
        """get_ready_work_items returns [] when subprocess raises CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd ready', stderr='error \ufffd')

        from pokepoke.beads.beads_query import get_ready_work_items
        result = get_ready_work_items()
        assert result == []

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_ready_work_items_handles_timeout(self, mock_run):
        """get_ready_work_items returns [] on subprocess timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired('bd ready', 30)

        from pokepoke.beads.beads_query import get_ready_work_items
        result = get_ready_work_items()
        assert result == []

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_ready_work_items_handles_unexpected_error(self, mock_run):
        """get_ready_work_items returns [] on unexpected exceptions."""
        mock_run.side_effect = OSError("unexpected")

        from pokepoke.beads.beads_query import get_ready_work_items
        result = get_ready_work_items()
        assert result == []

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_ready_work_items_returns_empty_on_unparseable_json(self, mock_run):
        """get_ready_work_items returns [] when beads output is not valid JSON."""
        mock_run.return_value = MagicMock(stdout='Note: not json \ufffd')

        from pokepoke.beads.beads_query import get_ready_work_items
        result = get_ready_work_items()
        assert result == []

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_ready_work_items_returns_empty_when_parse_returns_none(self, mock_run):
        """get_ready_work_items returns [] when _parse_beads_json returns None."""
        mock_run.return_value = MagicMock(stdout='Warning: no data')

        from pokepoke.beads.beads_query import get_ready_work_items
        result = get_ready_work_items()
        assert result == []

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_issue_dependencies_returns_none_on_failure(self, mock_run):
        """get_issue_dependencies returns None on subprocess failure."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd show')

        from pokepoke.beads.beads_query import get_issue_dependencies
        result = get_issue_dependencies("PK-1")
        assert result is None

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_issue_dependencies_returns_none_on_empty_stdout(self, mock_run):
        """get_issue_dependencies returns None for empty stdout."""
        mock_run.return_value = MagicMock(stdout='')

        from pokepoke.beads.beads_query import get_issue_dependencies
        result = get_issue_dependencies("PK-1")
        assert result is None

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_issue_dependencies_returns_none_on_unparseable(self, mock_run):
        """get_issue_dependencies returns None when output can't be parsed."""
        mock_run.return_value = MagicMock(stdout='Warning: no JSON here')

        from pokepoke.beads.beads_query import get_issue_dependencies
        result = get_issue_dependencies("PK-1")
        assert result is None

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_issue_dependencies_parses_with_deps_and_dependents(self, mock_run):
        """get_issue_dependencies parses issue with dependencies and dependents."""
        issue_data = [{
            "id": "PK-1", "title": "Test \U0001f680", "status": "open",
            "priority": 1, "issue_type": "task",
            "dependencies": [
                {"id": "PK-2", "title": "Dep", "issue_type": "task",
                 "dependency_type": "blocks", "status": "open"}
            ],
            "dependents": [
                {"id": "PK-3", "title": "Dependent", "issue_type": "task",
                 "dependency_type": "blocks", "status": "closed"}
            ],
        }]
        mock_run.return_value = MagicMock(stdout=json.dumps(issue_data))

        from pokepoke.beads.beads_query import get_issue_dependencies
        result = get_issue_dependencies("PK-1")
        assert result is not None
        assert result.id == "PK-1"
        assert len(result.dependencies) == 1
        assert result.dependencies[0].dependency_type == "blocks"
        assert len(result.dependents) == 1

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_has_unmet_blocking_dependencies_true(self, mock_run):
        """has_unmet_blocking_dependencies returns True when blocking dep is open."""
        issue_data = [{
            "id": "PK-1", "title": "Test", "status": "open",
            "priority": 1, "issue_type": "task",
            "dependencies": [
                {"id": "PK-2", "title": "Blocker", "issue_type": "task",
                 "dependency_type": "blocks", "status": "open"}
            ],
        }]
        mock_run.return_value = MagicMock(stdout=json.dumps(issue_data))

        from pokepoke.beads.beads_query import has_unmet_blocking_dependencies
        assert has_unmet_blocking_dependencies("PK-1") is True

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_has_unmet_blocking_dependencies_false_when_closed(self, mock_run):
        """has_unmet_blocking_dependencies returns False when all blocking deps closed."""
        issue_data = [{
            "id": "PK-1", "title": "Test", "status": "open",
            "priority": 1, "issue_type": "task",
            "dependencies": [
                {"id": "PK-2", "title": "Done", "issue_type": "task",
                 "dependency_type": "blocks", "status": "closed"}
            ],
        }]
        mock_run.return_value = MagicMock(stdout=json.dumps(issue_data))

        from pokepoke.beads.beads_query import has_unmet_blocking_dependencies
        assert has_unmet_blocking_dependencies("PK-1") is False

    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_has_unmet_blocking_dependencies_false_when_no_deps(self, mock_run):
        """has_unmet_blocking_dependencies returns False when issue not found."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd show')

        from pokepoke.beads.beads_query import has_unmet_blocking_dependencies
        assert has_unmet_blocking_dependencies("PK-1") is False

    @patch('pokepoke.beads.beads_query._get_main_repo_root')
    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_beads_stats_success(self, mock_run, mock_root):
        """get_beads_stats returns BeadsStats on success."""
        mock_root.return_value = None
        stats_json = json.dumps({"summary": {
            "total_issues": 10, "open_issues": 3, "in_progress_issues": 2,
            "closed_issues": 5, "ready_issues": 1,
        }})
        mock_run.return_value = MagicMock(stdout=stats_json)

        from pokepoke.beads.beads_query import get_beads_stats
        result = get_beads_stats()
        assert result is not None
        assert result.total_issues == 10
        assert result.ready_issues == 1

    @patch('pokepoke.beads.beads_query._get_main_repo_root')
    @patch('pokepoke.beads.beads_query.subprocess.run')
    def test_get_beads_stats_returns_none_on_failure(self, mock_run, mock_root):
        """get_beads_stats returns None on exception."""
        mock_root.return_value = None
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd stats')

        from pokepoke.beads.beads_query import get_beads_stats
        result = get_beads_stats()
        assert result is None

    def test_get_main_repo_root_returns_none_on_runtime_error(self):
        """_get_main_repo_root returns None when not in a git repo."""
        with patch('pokepoke.git.git_operations.get_main_repo_root', side_effect=RuntimeError("not a repo")):
            from pokepoke.beads.beads_query import _get_main_repo_root
            result = _get_main_repo_root()
            assert result is None
