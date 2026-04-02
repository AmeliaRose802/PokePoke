"""Lightweight test fakes for GitClient and BeadsClient protocols.

These are plain classes with explicit state — no ``unittest.Mock`` magic.
Import them in tests instead of patching module-level functions.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from pokepoke.types import BeadsStats, BeadsWorkItem, IssueWithDependencies

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# FakeGitClient
# ---------------------------------------------------------------------------


@dataclass
class _GitCall:
    """Record of a single FakeGitClient method call."""

    method: str
    args: tuple
    kwargs: dict = field(default_factory=dict)


class FakeGitClient:
    """In-memory fake that satisfies the :class:`~pokepoke.protocols.GitClient` protocol.

    Attributes:
        calls: Ordered list of every method invocation for assertion.
        run_git_results: Queue of results to return from :meth:`run_git`.
            When empty, the default ``_completed()`` is returned.
        pushed_branches: Set of branch names that :meth:`verify_branch_pushed`
            will report as pushed.
        worktrees: Static list returned by :meth:`list_worktrees`.
        run_git_side_effects: Optional list of callables/exceptions.
            When provided, each :meth:`run_git` call pops the next entry:
            if it's an exception it is raised, if callable it is called with
            ``(cmd, **kwargs)`` and the return value is used.
    """

    def __init__(self) -> None:
        self.calls: list[_GitCall] = []
        self.run_git_results: list[subprocess.CompletedProcess[str]] = []
        self.run_git_side_effects: list[Exception | callable] = []
        self.pushed_branches: set[str] = set()
        self.worktrees: list[dict[str, str]] = []

    # -- protocol methods --------------------------------------------------

    def run_git(
        self,
        cmd: list[str],
        *,
        timeout: int = 30,
        cwd: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            _GitCall("run_git", (cmd,), {"timeout": timeout, "cwd": cwd, "check": check})
        )
        if self.run_git_side_effects:
            effect = self.run_git_side_effects.pop(0)
            if isinstance(effect, BaseException):
                raise effect
            return effect(cmd, timeout=timeout, cwd=cwd, check=check)
        if self.run_git_results:
            return self.run_git_results.pop(0)
        return _completed()

    def verify_branch_pushed(self, branch_name: str) -> bool:
        self.calls.append(_GitCall("verify_branch_pushed", (branch_name,)))
        return branch_name in self.pushed_branches

    def list_worktrees(self, cwd: str | None = None) -> list[dict[str, str]]:
        self.calls.append(_GitCall("list_worktrees", (), {"cwd": cwd}))
        return list(self.worktrees)

    # -- assertion helpers -------------------------------------------------

    def call_count(self, method: str) -> int:
        return sum(1 for c in self.calls if c.method == method)

    def last_call(self, method: str) -> _GitCall | None:
        for c in reversed(self.calls):
            if c.method == method:
                return c
        return None

    def reset(self) -> None:
        self.calls.clear()
        self.run_git_results.clear()
        self.run_git_side_effects.clear()


# ---------------------------------------------------------------------------
# FakeBeadsClient
# ---------------------------------------------------------------------------


@dataclass
class _BeadsCall:
    """Record of a single FakeBeadsClient method call."""

    method: str
    args: tuple
    kwargs: dict = field(default_factory=dict)


class FakeBeadsClient:
    """In-memory fake that satisfies the :class:`~pokepoke.protocols.BeadsClient` protocol.

    Core state is ``items``, a dict of ``{item_id: BeadsWorkItem}``.
    Methods mutate this dict the same way the real beads CLI would.

    Attributes:
        items: Mutable mapping of item ID → work item.
        ready_items: Explicit list returned by :meth:`get_ready_work_items`.
            When ``None``, ready items are derived from ``items`` with
            ``status == "open"`` and no assignee.
        calls: Ordered log of every method invocation.
        stats: Value returned by :meth:`get_beads_stats`.
        dependencies: Mapping of item ID → :class:`IssueWithDependencies`.
        sync_results: Queue of results for :meth:`run_bd_sync_with_retry`.
        fail_methods: Set of method names that should return failure values.
    """

    def __init__(self) -> None:
        self.items: dict[str, BeadsWorkItem] = {}
        self.ready_items: list[BeadsWorkItem] | None = None
        self.calls: list[_BeadsCall] = []
        self.stats: BeadsStats | None = BeadsStats()
        self.dependencies: dict[str, IssueWithDependencies] = {}
        self.sync_results: list[subprocess.CompletedProcess[str]] = []
        self.fail_methods: set[str] = set()
        self._comments: dict[str, list[str]] = {}
        self._attempt_counts: dict[str, int] = {}
        self._failed_unassigns: dict[str, str] = {}
        self._failure_reasons: dict[str, str] = {}

    # -- helpers -----------------------------------------------------------

    def add_item(self, item: BeadsWorkItem) -> None:
        """Convenience: insert a work item into the fake store."""
        self.items[item.id] = item

    # -- protocol methods --------------------------------------------------

    def get_ready_work_items(self) -> list[BeadsWorkItem]:
        self.calls.append(_BeadsCall("get_ready_work_items", ()))
        if self.ready_items is not None:
            return list(self.ready_items)
        return [
            item
            for item in self.items.values()
            if item.status == "open" and not item.assignee
        ]

    def assign_and_sync_item(
        self, item_id: str, agent_name: str | None = None
    ) -> bool:
        self.calls.append(
            _BeadsCall("assign_and_sync_item", (item_id,), {"agent_name": agent_name})
        )
        if "assign_and_sync_item" in self.fail_methods:
            return False
        item = self.items.get(item_id)
        if item is None or item.assignee:
            return False
        item.assignee = agent_name or "agent"
        item.status = "in_progress"
        return True

    def close_item(self, item_id: str, reason: str) -> bool:
        self.calls.append(_BeadsCall("close_item", (item_id, reason)))
        if "close_item" in self.fail_methods:
            return False
        item = self.items.get(item_id)
        if item is None:
            return False
        item.status = "closed"
        return True

    def add_comment(self, item_id: str, message: str) -> bool:
        self.calls.append(_BeadsCall("add_comment", (item_id, message)))
        if "add_comment" in self.fail_methods:
            return False
        self._comments.setdefault(item_id, []).append(message)
        return True

    def get_item_comments(self, item_id: str) -> list[dict[str, object]]:
        self.calls.append(_BeadsCall("get_item_comments", (item_id,)))
        return [
            {"text": text, "author": "agent", "created_at": "2025-01-01T00:00:00Z"}
            for text in self._comments.get(item_id, [])
        ]

    def block_item(self, item_id: str, reason: str) -> bool:
        self.calls.append(_BeadsCall("block_item", (item_id, reason)))
        if "block_item" in self.fail_methods:
            return False
        item = self.items.get(item_id)
        if item is not None:
            item.status = "blocked"
        self._comments.setdefault(item_id, []).append(f"🚫 Blocked: {reason}")
        return True

    def unassign_item(self, item_id: str) -> bool:
        self.calls.append(_BeadsCall("unassign_item", (item_id,)))
        if "unassign_item" in self.fail_methods:
            return False
        item = self.items.get(item_id)
        if item is None:
            return False
        item.assignee = None
        item.status = "open"
        return True

    def unassign_with_retry(self, item_id: str) -> bool:
        self.calls.append(_BeadsCall("unassign_with_retry", (item_id,)))
        if "unassign_with_retry" in self.fail_methods:
            self._failed_unassigns[item_id] = "fake failure"
            return False
        item = self.items.get(item_id)
        if item is None:
            return False
        item.assignee = None
        item.status = "open"
        return True

    def is_item_claimable(self, item_id: str) -> bool:
        self.calls.append(_BeadsCall("is_item_claimable", (item_id,)))
        item = self.items.get(item_id)
        if item is None:
            return False
        return not item.assignee

    def select_next_hierarchical_item(
        self, items: list[BeadsWorkItem]
    ) -> BeadsWorkItem | None:
        self.calls.append(_BeadsCall("select_next_hierarchical_item", (items,)))
        if not items:
            return None
        return min(items, key=lambda i: i.priority)

    def get_beads_stats(self) -> BeadsStats | None:
        self.calls.append(_BeadsCall("get_beads_stats", ()))
        return self.stats

    def get_issue_dependencies(
        self, issue_id: str
    ) -> IssueWithDependencies | None:
        self.calls.append(_BeadsCall("get_issue_dependencies", (issue_id,)))
        return self.dependencies.get(issue_id)

    def increment_total_attempts(self, item_id: str) -> bool:
        self.calls.append(_BeadsCall("increment_total_attempts", (item_id,)))
        if "increment_total_attempts" in self.fail_methods:
            return False
        self._attempt_counts[item_id] = self._attempt_counts.get(item_id, 0) + 1
        return True

    def fail_task(
        self, item_id: str, reason: str, agent_type: str = "work"
    ) -> bool:
        self.calls.append(_BeadsCall("fail_task", (item_id, reason), {"agent_type": agent_type}))
        if "fail_task" in self.fail_methods:
            return False
        self._comments.setdefault(item_id, []).append(f"❌ Agent failure: {reason}")
        self._failure_reasons[item_id] = reason
        return True

    def retry_failed_unassigns(self) -> int:
        self.calls.append(_BeadsCall("retry_failed_unassigns", ()))
        recovered = len(self._failed_unassigns)
        self._failed_unassigns.clear()
        return recovered

    def get_failed_unassign_count(self) -> int:
        self.calls.append(_BeadsCall("get_failed_unassign_count", ()))
        return len(self._failed_unassigns)

    def run_bd_sync_with_retry(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        timeout: int | None = 60,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            _BeadsCall(
                "run_bd_sync_with_retry",
                (),
                {"max_attempts": max_attempts, "base_delay": base_delay, "timeout": timeout},
            )
        )
        if self.sync_results:
            return self.sync_results.pop(0)
        return _completed()

    # -- assertion helpers -------------------------------------------------

    def call_count(self, method: str) -> int:
        return sum(1 for c in self.calls if c.method == method)

    def last_call(self, method: str) -> _BeadsCall | None:
        for c in reversed(self.calls):
            if c.method == method:
                return c
        return None

    def get_comments(self, item_id: str) -> list[str]:
        return list(self._comments.get(item_id, []))

    def get_attempt_count(self, item_id: str) -> int:
        return self._attempt_counts.get(item_id, 0)

    def reset(self) -> None:
        self.calls.clear()
        self.sync_results.clear()
        self.fail_methods.clear()
        self._comments.clear()
        self._attempt_counts.clear()
        self._failed_unassigns.clear()
        self._failure_reasons.clear()
