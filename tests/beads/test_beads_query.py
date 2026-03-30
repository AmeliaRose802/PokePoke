import json
import subprocess
from pathlib import Path

import pytest

from pokepoke.beads import beads_query, cli_retry
from pokepoke.beads.beads_query import BD_CONFIG, BR_CONFIG, get_active_backend, set_active_backend
from pokepoke.types import Dependency, IssueWithDependencies

# Save reference to real _run_bd before conftest replaces it with a blocker.
_real_run_bd = beads_query._run_bd


def test_parse_beads_json_filters_prefixes() -> None:
    output = "Note: info\nWarning: skip\nHint: also skip\nCreated item\n{\n  \"value\": 1\n}\n"
    parsed = beads_query._parse_beads_json(output, extra_prefixes=("Created",))
    assert parsed == {"value": 1}


def test_parse_beads_json_returns_none_when_no_json() -> None:
    assert beads_query._parse_beads_json("no json here") is None


def test_get_ready_work_items_parses_results(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {"id": "x", "title": "Task", "status": "open", "priority": 1, "issue_type": "task", "description": "d"},
    ]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    items = beads_query.get_ready_work_items()

    assert len(items) == 1
    assert items[0].id == "x"


def test_get_ready_work_items_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "bd")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_ready_work_items() == []


def test_get_issue_dependencies_returns_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "id": "A",
            "title": "Issue A",
            "status": "open",
            "priority": 1,
            "issue_type": "task",
            "dependencies": [
                {"id": "dep1", "title": "Dep", "issue_type": "task", "dependency_type": "blocks", "status": "open"}
            ],
        }
    ]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    issue = beads_query.get_issue_dependencies("A")

    assert issue is not None
    assert issue.dependencies and isinstance(issue.dependencies[0], Dependency)
    assert issue.dependencies[0].dependency_type == "blocks"


def test_has_unmet_blocking_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    deps = [Dependency(id="d1", title="", issue_type="task", dependency_type="blocks", status="open")]
    issue = IssueWithDependencies(id="A", title="", status="open", priority=1, issue_type="task", dependencies=deps)
    monkeypatch.setattr(beads_query, "get_issue_dependencies", lambda _item_id, **kwargs: issue)

    assert beads_query.has_unmet_blocking_dependencies("A") is True

    deps[0].status = "closed"
    assert beads_query.has_unmet_blocking_dependencies("A") is False


def test_get_beads_stats_parses_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    stats_json = {"summary": {"total_issues": 5, "open_issues": 2, "in_progress_issues": 1, "closed_issues": 2, "ready_issues": 3}}
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(stats_json))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)
    monkeypatch.setattr(beads_query, "_get_main_repo_root", lambda: Path("/repo"))

    stats = beads_query.get_beads_stats()

    assert stats is not None
    assert stats.total_issues == 5
    assert stats.ready_issues == 3


def test_get_beads_stats_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "bd", stderr="stats unavailable")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_beads_stats() is None


def test_get_main_repo_root_returns_none_on_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import pokepoke.git.git_operations

    def boom() -> None:
        raise RuntimeError("not a repo")

    monkeypatch.setattr(pokepoke.git.git_operations, "get_main_repo_root", boom)

    assert beads_query._get_main_repo_root() is None


def test_run_bd_uses_lock_for_mutating_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {"lock_timeout": None, "ran": False}

    class _Lock:
        def __init__(self, *, timeout: float):
            calls["lock_timeout"] = timeout

        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_lock(*, timeout: float):
        return _Lock(timeout=timeout)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["ran"] = True
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    # Restore real _run_bd (conftest blocks it for safety)
    monkeypatch.setattr(beads_query, "_run_bd", _real_run_bd)
    monkeypatch.setattr(beads_query, "beads_db_lock", fake_lock)
    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    beads_query._run_bd(["update", "x"], check=False)

    assert calls["ran"] is True
    assert calls["lock_timeout"] == 180.0


def test_run_bd_skips_lock_for_non_mutating_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_called = {"called": False}

    def fake_lock(*, timeout: float):
        lock_called["called"] = True
        raise AssertionError("should not lock")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="[]")

    monkeypatch.setattr(beads_query, "beads_db_lock", fake_lock)
    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    beads_query._run_bd(["ready", "--json"], check=False)

    assert lock_called["called"] is False


def test_filter_to_dataclass_filters_extraneous_fields() -> None:
    import dataclasses

    @dataclasses.dataclass
    class _X:
        a: int
        b: str

    inst = beads_query._filter_to_dataclass(_X, {"a": 1, "b": "ok", "extra": 2})
    assert inst == _X(a=1, b="ok")


def test_get_issue_dependencies_returns_none_on_calledprocesserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "bd")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_empty_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout="")
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_malformed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout="not valid json {{{")
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout="[]")
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_non_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout='{"id": "A"}')
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("bd", 30)

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_returns_none_on_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("unexpected")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.get_issue_dependencies("A") is None


def test_get_issue_dependencies_converts_dependents(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [
        {
            "id": "A",
            "title": "Issue A",
            "status": "open",
            "priority": 1,
            "issue_type": "task",
            "dependents": [
                {"id": "child1", "title": "Child", "issue_type": "task", "dependency_type": "parent", "status": "open"}
            ],
        }
    ]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    issue = beads_query.get_issue_dependencies("A")

    assert issue is not None
    assert issue.dependents is not None
    assert issue.dependents[0].dependency_type == "parent"


# ── is_beads_item_closed ────────────────────────────────────────────


def test_is_beads_item_closed_returns_true_for_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "x", "status": "closed", "title": "Done"}]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is True


def test_is_beads_item_closed_returns_false_for_open(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "x", "status": "open", "title": "Active"}]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_returns_false_for_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "x", "status": "in_progress", "title": "Working"}]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_returns_false_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "bd")

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_returns_false_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("bd", 30)

    monkeypatch.setattr(beads_query, "_run_bd", boom)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_returns_false_on_empty_output(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_process = subprocess.CompletedProcess("bd", 0, stdout="")
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is False


def test_is_beads_item_closed_handles_non_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"id": "x", "status": "closed", "title": "Done"}
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is True


def test_is_beads_item_closed_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = [{"id": "x", "status": "Closed", "title": "Done"}]
    mock_process = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
    monkeypatch.setattr(beads_query, "_run_bd", lambda *args, **kwargs: mock_process)

    assert beads_query.is_beads_item_closed("x") is True


# ── CLIBackendConfig ────────────────────────────────────────────────


def test_cli_backend_config_defaults() -> None:
    cfg = beads_query.CLIBackendConfig(binary="bd")
    assert cfg.binary == "bd"
    assert cfg.default_timeout == 30
    assert cfg.lock_timeout == 180.0
    assert "update" in cfg.mutating_commands
    assert "ready" not in cfg.mutating_commands


def test_cli_backend_config_custom_values() -> None:
    custom_cmds = frozenset({"push", "pull"})
    cfg = beads_query.CLIBackendConfig(
        binary="br",
        default_timeout=60,
        lock_timeout=300.0,
        mutating_commands=custom_cmds,
    )
    assert cfg.binary == "br"
    assert cfg.default_timeout == 60
    assert cfg.lock_timeout == 300.0
    assert cfg.mutating_commands == custom_cmds


def test_cli_backend_config_is_frozen() -> None:
    cfg = beads_query.CLIBackendConfig(binary="bd")
    with pytest.raises(AttributeError):
        cfg.binary = "br"  # type: ignore[misc]


@pytest.mark.parametrize("backend_config", [BD_CONFIG, BR_CONFIG], ids=["bd", "br"])
class TestBeadsQueryBothBackends:
    """Tests that run against both bd and br backends."""

    def test_get_ready_work_items_uses_correct_backend(
        self, backend_config, monkeypatch
    ):
        """Verify get_ready_work_items uses the configured backend binary."""
        original = get_active_backend()
        set_active_backend(backend_config)

        try:
            payload = [
                {
                    "id": "x",
                    "title": "Task",
                    "status": "open",
                    "priority": 1,
                    "issue_type": "task",
                    "description": "d",
                },
            ]
            mock_process = subprocess.CompletedProcess(
                backend_config.binary, 0, stdout=json.dumps(payload)
            )
            monkeypatch.setattr(
                beads_query, "_run_bd", lambda *args, **kwargs: mock_process
            )

            items = beads_query.get_ready_work_items()

            assert len(items) == 1
            assert items[0].id == "x"
        finally:
            set_active_backend(original)

    def test_get_issue_dependencies_with_backend(self, backend_config, monkeypatch):
        """Verify get_issue_dependencies works with both backends."""
        original = get_active_backend()
        set_active_backend(backend_config)

        try:
            payload = [
                {
                    "id": "A",
                    "title": "Issue A",
                    "status": "open",
                    "priority": 1,
                    "issue_type": "task",
                    "dependencies": [
                        {
                            "id": "dep1",
                            "title": "Dep",
                            "issue_type": "task",
                            "dependency_type": "blocks",
                            "status": "open",
                        }
                    ],
                }
            ]
            mock_process = subprocess.CompletedProcess(
                backend_config.binary, 0, stdout=json.dumps(payload)
            )
            monkeypatch.setattr(
                beads_query, "_run_bd", lambda *args, **kwargs: mock_process
            )

            issue = beads_query.get_issue_dependencies("A")

            assert issue is not None
            assert issue.dependencies and isinstance(issue.dependencies[0], Dependency)
            assert issue.dependencies[0].dependency_type == "blocks"
        finally:
            set_active_backend(original)

    def test_get_beads_stats_with_backend(self, backend_config, monkeypatch):
        """Verify get_beads_stats works with both backends."""
        original = get_active_backend()
        set_active_backend(backend_config)

        try:
            stats_json = {
                "summary": {
                    "total_issues": 5,
                    "open_issues": 2,
                    "in_progress_issues": 1,
                    "closed_issues": 2,
                    "ready_issues": 3,
                }
            }
            mock_process = subprocess.CompletedProcess(
                backend_config.binary, 0, stdout=json.dumps(stats_json)
            )
            monkeypatch.setattr(
                beads_query, "_run_bd", lambda *args, **kwargs: mock_process
            )
            monkeypatch.setattr(beads_query, "_get_main_repo_root", lambda: Path("/repo"))

            stats = beads_query.get_beads_stats()

            assert stats is not None
            assert stats.total_issues == 5
            assert stats.ready_issues == 3
        finally:
            set_active_backend(original)


def test_predefined_bd_config() -> None:
    assert beads_query.BD_CONFIG.binary == "bd"
    assert beads_query.BD_CONFIG.default_timeout == 30


def test_predefined_br_config() -> None:
    assert beads_query.BR_CONFIG.binary == "br"
    assert beads_query.BR_CONFIG.default_timeout == 30


# ── Active backend get/set ──────────────────────────────────────────


def test_get_active_backend_returns_bd_by_default() -> None:
    original = beads_query.get_active_backend()
    assert original.binary == "bd"


def test_set_active_backend_changes_active(monkeypatch: pytest.MonkeyPatch) -> None:
    original = beads_query.get_active_backend()
    try:
        beads_query.set_active_backend(beads_query.BR_CONFIG)
        assert beads_query.get_active_backend().binary == "br"
    finally:
        beads_query.set_active_backend(original)


# ── _run_cli backend-agnostic runner ────────────────────────────────


def test_run_cli_uses_backend_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    br_config = beads_query.CLIBackendConfig(binary="br")
    beads_query._run_cli(["ready", "--json"], backend=br_config, check=False)

    called_cmd = captured["args"][0]
    assert called_cmd[0] == "br"
    assert called_cmd[1:] == ["ready", "--json"]


def test_run_cli_uses_backend_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    cfg = beads_query.CLIBackendConfig(binary="br", default_timeout=60)
    beads_query._run_cli(["ready"], backend=cfg, check=False)

    assert captured["kwargs"]["timeout"] == 60


def test_run_cli_explicit_timeout_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    cfg = beads_query.CLIBackendConfig(binary="br", default_timeout=60)
    beads_query._run_cli(["ready"], backend=cfg, check=False, timeout=10)

    assert captured["kwargs"]["timeout"] == 10


def test_run_cli_locks_for_mutating_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {"lock_timeout": None, "ran": False}

    class _Lock:
        def __init__(self, *, timeout: float):
            calls["lock_timeout"] = timeout

        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_lock(*, timeout: float):
        return _Lock(timeout=timeout)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls["ran"] = True
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    monkeypatch.setattr(beads_query, "beads_db_lock", fake_lock)
    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    cfg = beads_query.CLIBackendConfig(binary="br", lock_timeout=200.0)
    beads_query._run_cli(["update", "x"], backend=cfg, check=False)

    assert calls["ran"] is True
    assert calls["lock_timeout"] == 200.0


def test_run_cli_skips_lock_for_non_mutating(monkeypatch: pytest.MonkeyPatch) -> None:
    lock_called = {"called": False}

    def fake_lock(*, timeout: float):
        lock_called["called"] = True
        raise AssertionError("should not lock")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="[]")

    monkeypatch.setattr(beads_query, "beads_db_lock", fake_lock)
    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    beads_query._run_cli(["show", "x", "--json"], backend=beads_query.BD_CONFIG, check=False)

    assert lock_called["called"] is False


def test_run_cli_respects_custom_mutating_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Backend with custom mutating commands should lock on those commands."""
    calls: dict[str, object] = {"locked": False}

    class _Lock:
        def __init__(self, *, timeout: float):
            pass

        def __enter__(self):
            calls["locked"] = True

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_lock(*, timeout: float):
        return _Lock(timeout=timeout)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    monkeypatch.setattr(beads_query, "beads_db_lock", fake_lock)
    monkeypatch.setattr(beads_query.subprocess, "run", fake_run)

    cfg = beads_query.CLIBackendConfig(
        binary="br",
        mutating_commands=frozenset({"push"}),
    )
    beads_query._run_cli(["push"], backend=cfg, check=False)
    assert calls["locked"] is True

    # "update" is NOT in this backend's mutating commands
    calls["locked"] = False
    beads_query._run_cli(["update", "x"], backend=cfg, check=False)
    assert calls["locked"] is False


@pytest.mark.allow_real_bd
def test_run_bd_delegates_to_active_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """_run_bd should use the active backend's binary."""
    captured: dict[str, object] = {}

    def fake_run_cli(args: list[str], *, backend: beads_query.CLIBackendConfig, **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["backend"] = backend
        captured["args"] = args
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    monkeypatch.setattr(beads_query, "_run_cli", fake_run_cli)

    original = beads_query.get_active_backend()
    try:
        beads_query.set_active_backend(beads_query.BR_CONFIG)
        beads_query._run_bd(["ready", "--json"], check=False)
        assert captured["backend"].binary == "br"
        assert captured["args"] == ["ready", "--json"]
    finally:
        beads_query.set_active_backend(original)


# ---------------------------------------------------------------------------
# _is_transient_cli_error tests
# ---------------------------------------------------------------------------


class TestIsTransientCliError:
    """Tests for the transient-error detection helper."""

    def test_timeout_expired_is_transient(self) -> None:
        exc = subprocess.TimeoutExpired(cmd="bd", timeout=30)
        assert cli_retry._is_transient_cli_error(exc) is True

    def test_os_error_is_transient(self) -> None:
        exc = OSError("Permission denied")
        assert cli_retry._is_transient_cli_error(exc) is True

    def test_jsonl_lock_error_is_transient(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="Access is denied for .jsonl file")
        assert cli_retry._is_transient_cli_error(exc) is True

    def test_jsonl_replace_error_is_transient(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="Failed to replace JSONL file")
        assert cli_retry._is_transient_cli_error(exc) is True

    def test_lock_contention_is_transient(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="could not acquire lock")
        assert cli_retry._is_transient_cli_error(exc) is True

    def test_daemon_not_ready_is_transient(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="daemon not running, cannot connect")
        assert cli_retry._is_transient_cli_error(exc) is True

    def test_connection_refused_is_transient(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="Connection refused")
        assert cli_retry._is_transient_cli_error(exc) is True

    def test_connection_timed_out_is_transient(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="Connection timed out")
        assert cli_retry._is_transient_cli_error(exc) is True

    def test_non_transient_called_process_error(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd", stderr="item not found")
        assert cli_retry._is_transient_cli_error(exc) is False

    def test_non_transient_generic_error(self) -> None:
        exc = ValueError("unexpected")
        assert cli_retry._is_transient_cli_error(exc) is False

    def test_called_process_error_with_none_output(self) -> None:
        exc = subprocess.CalledProcessError(1, "bd")
        assert cli_retry._is_transient_cli_error(exc) is False


# ---------------------------------------------------------------------------
# _run_bd_with_retry tests
# ---------------------------------------------------------------------------


class TestRunBdWithRetry:
    """Tests for the retry wrapper around _run_bd."""

    def test_succeeds_on_first_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ok = subprocess.CompletedProcess("bd", 0, stdout='{"ok": true}')
        monkeypatch.setattr(beads_query, "_run_bd", lambda *a, **kw: ok)

        result = cli_retry._run_bd_with_retry(["ready", "--json"])
        assert result.returncode == 0

    def test_retries_transient_timeout_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ok = subprocess.CompletedProcess("bd", 0, stdout='{"ok": true}')
        call_count = 0

        def flaky(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise subprocess.TimeoutExpired(cmd="bd", timeout=30)
            return ok

        monkeypatch.setattr(beads_query, "_run_bd", flaky)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda _: None)

        result = cli_retry._run_bd_with_retry(
            ["ready", "--json"], max_attempts=3, base_delay=0.01,
        )
        assert result.returncode == 0
        assert call_count == 2

    def test_retries_transient_lock_error_then_succeeds(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ok = subprocess.CompletedProcess("bd", 0, stdout='[]')
        call_count = 0

        def flaky(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise subprocess.CalledProcessError(
                    1, "bd", stderr="could not acquire lock on file"
                )
            return ok

        monkeypatch.setattr(beads_query, "_run_bd", flaky)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda _: None)

        result = cli_retry._run_bd_with_retry(
            ["show", "x", "--json"], max_attempts=3, base_delay=0.01,
        )
        assert result.returncode == 0
        assert call_count == 3

    def test_raises_after_exhausting_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = 0

        def always_timeout(*_a: object, **_kw: object) -> None:
            nonlocal call_count
            call_count += 1
            raise subprocess.TimeoutExpired(cmd="bd", timeout=30)

        monkeypatch.setattr(beads_query, "_run_bd", always_timeout)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda _: None)

        with pytest.raises(subprocess.TimeoutExpired):
            cli_retry._run_bd_with_retry(
                ["ready", "--json"], max_attempts=3, base_delay=0.01,
            )
        assert call_count == 3

    def test_non_transient_error_raises_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        call_count = 0

        def permanent_fail(*_a: object, **_kw: object) -> None:
            nonlocal call_count
            call_count += 1
            raise subprocess.CalledProcessError(1, "bd", stderr="item not found")

        monkeypatch.setattr(beads_query, "_run_bd", permanent_fail)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda _: None)

        with pytest.raises(subprocess.CalledProcessError):
            cli_retry._run_bd_with_retry(
                ["show", "x", "--json"], max_attempts=3, base_delay=0.01,
            )
        assert call_count == 1

    def test_exponential_backoff_delays(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        delays: list[float] = []
        call_count = 0

        def always_timeout(*_a: object, **_kw: object) -> None:
            nonlocal call_count
            call_count += 1
            raise subprocess.TimeoutExpired(cmd="bd", timeout=30)

        monkeypatch.setattr(beads_query, "_run_bd", always_timeout)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda d: delays.append(d))

        with pytest.raises(subprocess.TimeoutExpired):
            cli_retry._run_bd_with_retry(
                ["ready"], max_attempts=4, base_delay=0.5,
            )
        # Delays: 0.5, 1.0, 2.0 (3 retries before the 4th fails)
        assert delays == [0.5, 1.0, 2.0]


# ---------------------------------------------------------------------------
# Retry integration with public query functions
# ---------------------------------------------------------------------------


class TestRetryIntegrationWithQueryFunctions:
    """Verify that public functions survive transient errors via retry."""

    def test_get_ready_work_items_retries_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = [{"id": "x", "title": "T", "status": "open",
                     "priority": 1, "issue_type": "task", "description": "d"}]
        ok = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
        call_count = 0

        def flaky(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise subprocess.TimeoutExpired(cmd="bd", timeout=30)
            return ok

        monkeypatch.setattr(beads_query, "_run_bd", flaky)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda _: None)

        items = beads_query.get_ready_work_items()
        assert len(items) == 1
        assert items[0].id == "x"
        assert call_count == 2

    def test_get_beads_stats_retries_os_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stats_json = json.dumps({
            "summary": {
                "total_issues": 10, "open_issues": 5,
                "in_progress_issues": 2, "closed_issues": 3,
                "ready_issues": 4,
            }
        })
        ok = subprocess.CompletedProcess("bd", 0, stdout=stats_json)
        call_count = 0

        def flaky(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("Permission denied")
            return ok

        monkeypatch.setattr(beads_query, "_run_bd", flaky)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda _: None)
        monkeypatch.setattr(beads_query, "_get_main_repo_root", lambda: None)

        stats = beads_query.get_beads_stats()
        assert stats is not None
        assert stats.total_issues == 10
        assert call_count == 2

    def test_get_issue_dependencies_retries_daemon_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = [{"id": "A", "title": "Issue A", "status": "open",
                     "priority": 1, "issue_type": "task"}]
        ok = subprocess.CompletedProcess("bd", 0, stdout=json.dumps(payload))
        call_count = 0

        def flaky(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise subprocess.CalledProcessError(
                    1, "bd", stderr="daemon not ready, cannot connect"
                )
            return ok

        monkeypatch.setattr(beads_query, "_run_bd", flaky)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda _: None)

        result = beads_query.get_issue_dependencies("A")
        assert result is not None
        assert result.id == "A"
        assert call_count == 2

    def test_is_beads_item_closed_retries_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ok = subprocess.CompletedProcess(
            "bd", 0, stdout=json.dumps([{"status": "closed"}])
        )
        call_count = 0

        def flaky(*_a: object, **_kw: object) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise subprocess.TimeoutExpired(cmd="bd", timeout=30)
            return ok

        monkeypatch.setattr(beads_query, "_run_bd", flaky)
        monkeypatch.setattr(cli_retry.time, "sleep", lambda _: None)

        assert beads_query.is_beads_item_closed("x") is True
        assert call_count == 2
