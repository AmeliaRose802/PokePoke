"""Tests for pokepoke.utils.logging_filters."""

import json
import logging
from unittest.mock import patch

from pokepoke.utils.logging_filters import JsonFormatter, WorkItemFilter

# The WorkItemFilter imports metrics_context functions inside filter(),
# so we must patch at the metrics_context module level.
_MC = "pokepoke.stats.metrics_context"


class TestWorkItemFilter:
    """Unit tests for WorkItemFilter."""

    def test_filter_injects_work_item_id(self):
        filt = WorkItemFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None,
        )
        with patch(f"{_MC}.get_current_work_item_id", return_value="ITEM-42"), \
             patch(f"{_MC}.get_current_repo_name", return_value=""), \
             patch(f"{_MC}.get_current_agent_type", return_value=""):
            result = filt.filter(record)

        assert result is True
        assert record.work_item_id == "ITEM-42"

    def test_filter_injects_repo_name(self):
        filt = WorkItemFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None,
        )
        with patch(f"{_MC}.get_current_work_item_id", return_value=""), \
             patch(f"{_MC}.get_current_repo_name", return_value="my-repo"), \
             patch(f"{_MC}.get_current_agent_type", return_value=""):
            filt.filter(record)

        assert record.repo_name == "my-repo"

    def test_filter_injects_agent_type(self):
        filt = WorkItemFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None,
        )
        with patch(f"{_MC}.get_current_work_item_id", return_value=""), \
             patch(f"{_MC}.get_current_repo_name", return_value=""), \
             patch(f"{_MC}.get_current_agent_type", return_value="gate"):
            filt.filter(record)

        assert record.agent_type == "gate"

    def test_filter_defaults_to_empty_strings(self):
        filt = WorkItemFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None,
        )
        with patch(f"{_MC}.get_current_work_item_id", return_value=""), \
             patch(f"{_MC}.get_current_repo_name", return_value=""), \
             patch(f"{_MC}.get_current_agent_type", return_value=""):
            filt.filter(record)

        assert record.work_item_id == ""
        assert record.repo_name == ""
        assert record.agent_type == ""

    def test_filter_always_returns_true(self):
        """WorkItemFilter should never suppress records."""
        filt = WorkItemFilter()
        record = logging.LogRecord(
            "test", logging.DEBUG, "", 0, "msg", (), None,
        )
        with patch(f"{_MC}.get_current_work_item_id", return_value=""), \
             patch(f"{_MC}.get_current_repo_name", return_value=""), \
             patch(f"{_MC}.get_current_agent_type", return_value=""):
            assert filt.filter(record) is True


class TestJsonFormatter:
    """Unit tests for JsonFormatter."""

    def test_basic_format(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            "my.logger", logging.INFO, "file.py", 42, "Hello world", (), None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["logger"] == "my.logger"
        assert data["message"] == "Hello world"
        assert "timestamp" in data

    def test_includes_work_item_id_when_present(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None,
        )
        record.work_item_id = "ITEM-99"
        output = fmt.format(record)
        data = json.loads(output)
        assert data["work_item_id"] == "ITEM-99"

    def test_excludes_empty_work_item_id(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None,
        )
        record.work_item_id = ""
        output = fmt.format(record)
        data = json.loads(output)
        assert "work_item_id" not in data

    def test_includes_repo_name_when_present(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None,
        )
        record.repo_name = "my-repo"
        output = fmt.format(record)
        data = json.loads(output)
        assert data["repo_name"] == "my-repo"

    def test_includes_agent_type_when_present(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "msg", (), None,
        )
        record.agent_type = "work"
        output = fmt.format(record)
        data = json.loads(output)
        assert data["agent_type"] == "work"

    def test_includes_exception_info(self):
        fmt = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            "test", logging.ERROR, "", 0, "bad", (), exc_info,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_omits_exception_when_none(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "ok", (), None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "exception" not in data

    def test_output_is_valid_json_single_line(self):
        fmt = JsonFormatter()
        record = logging.LogRecord(
            "test", logging.WARNING, "", 0, "multiline\nmessage", (), None,
        )
        output = fmt.format(record)
        # Should be a single JSON line (no embedded newlines in the JSON envelope)
        assert "\n" not in output
        data = json.loads(output)
        assert data["message"] == "multiline\nmessage"
