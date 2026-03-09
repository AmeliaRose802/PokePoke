"""Tests for per-repo worker pool allocation and rebalancing."""

import threading

from pokepoke.config import RepoConfig
from pokepoke.repo_worker_pool import RepoWorkerPool, _derive_repo_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _repo(path: str = "/repo/a", weight: int = 1, enabled: bool = True, max_workers: int = 0) -> RepoConfig:
    return RepoConfig(path=path, priority_weight=weight, enabled=enabled, max_workers=max_workers)


# ---------------------------------------------------------------------------
# _derive_repo_name
# ---------------------------------------------------------------------------

class TestDeriveRepoName:
    def test_simple_path(self) -> None:
        assert _derive_repo_name(RepoConfig(path="/home/user/myrepo")) == "myrepo"

    def test_empty_path(self) -> None:
        assert _derive_repo_name(RepoConfig(path="")) == ""

    def test_trailing_slash(self) -> None:
        name = _derive_repo_name(RepoConfig(path="/home/user/myrepo/"))
        # Path normalizes trailing slash
        assert name == "myrepo"


# ---------------------------------------------------------------------------
# Initial allocation
# ---------------------------------------------------------------------------

class TestInitialAllocation:
    def test_single_repo_gets_all_workers(self) -> None:
        pool = RepoWorkerPool(total_workers=4, repos=[_repo("/a", weight=1)])
        alloc = pool.get_allocation("/a")
        assert alloc is not None
        assert alloc.allocated_workers == 4
        assert alloc.base_allocation == 4

    def test_equal_weight_split(self) -> None:
        pool = RepoWorkerPool(
            total_workers=4,
            repos=[_repo("/a", weight=1), _repo("/b", weight=1)],
        )
        a = pool.get_allocation("/a")
        b = pool.get_allocation("/b")
        assert a is not None and b is not None
        assert a.allocated_workers == 2
        assert b.allocated_workers == 2

    def test_weighted_split(self) -> None:
        pool = RepoWorkerPool(
            total_workers=6,
            repos=[_repo("/a", weight=2), _repo("/b", weight=1)],
        )
        a = pool.get_allocation("/a")
        b = pool.get_allocation("/b")
        assert a is not None and b is not None
        assert a.allocated_workers == 4
        assert b.allocated_workers == 2

    def test_remainder_distribution(self) -> None:
        """With 5 workers and equal weights, one repo gets the extra slot."""
        pool = RepoWorkerPool(
            total_workers=5,
            repos=[_repo("/a", weight=1), _repo("/b", weight=1)],
        )
        a = pool.get_allocation("/a")
        b = pool.get_allocation("/b")
        assert a is not None and b is not None
        total = a.allocated_workers + b.allocated_workers
        assert total == 5

    def test_max_workers_cap_respected(self) -> None:
        pool = RepoWorkerPool(
            total_workers=10,
            repos=[_repo("/a", weight=3, max_workers=2), _repo("/b", weight=1)],
        )
        a = pool.get_allocation("/a")
        b = pool.get_allocation("/b")
        assert a is not None and b is not None
        assert a.allocated_workers <= 2

    def test_disabled_repos_excluded(self) -> None:
        pool = RepoWorkerPool(
            total_workers=4,
            repos=[_repo("/a", weight=1), _repo("/b", weight=1, enabled=False)],
        )
        assert pool.get_allocation("/b") is None
        a = pool.get_allocation("/a")
        assert a is not None
        assert a.allocated_workers == 4

    def test_no_repos(self) -> None:
        pool = RepoWorkerPool(total_workers=4, repos=[])
        assert pool.get_all_allocations() == {}

    def test_total_workers_clamped_to_one(self) -> None:
        pool = RepoWorkerPool(total_workers=0, repos=[_repo("/a")])
        assert pool.total_workers == 1


# ---------------------------------------------------------------------------
# available_slots
# ---------------------------------------------------------------------------

class TestAvailableSlots:
    def test_full_availability(self) -> None:
        pool = RepoWorkerPool(total_workers=3, repos=[_repo("/a")])
        assert pool.available_slots("/a") == 3

    def test_reduced_by_active(self) -> None:
        pool = RepoWorkerPool(total_workers=3, repos=[_repo("/a")])
        pool.record_worker_start("/a")
        assert pool.available_slots("/a") == 2

    def test_unknown_repo(self) -> None:
        pool = RepoWorkerPool(total_workers=3, repos=[_repo("/a")])
        assert pool.available_slots("/nonexistent") == 0


# ---------------------------------------------------------------------------
# Worker lifecycle
# ---------------------------------------------------------------------------

class TestWorkerLifecycle:
    def test_start_and_done(self) -> None:
        pool = RepoWorkerPool(total_workers=2, repos=[_repo("/a")])
        pool.record_worker_start("/a")
        alloc = pool.get_allocation("/a")
        assert alloc is not None and alloc.active_workers == 1

        pool.record_worker_done("/a")
        alloc = pool.get_allocation("/a")
        assert alloc is not None and alloc.active_workers == 0

    def test_done_does_not_go_negative(self) -> None:
        pool = RepoWorkerPool(total_workers=2, repos=[_repo("/a")])
        pool.record_worker_done("/a")
        alloc = pool.get_allocation("/a")
        assert alloc is not None and alloc.active_workers == 0

    def test_unknown_repo_start_no_error(self) -> None:
        pool = RepoWorkerPool(total_workers=2, repos=[_repo("/a")])
        pool.record_worker_start("/unknown")  # should not raise

    def test_unknown_repo_done_no_error(self) -> None:
        pool = RepoWorkerPool(total_workers=2, repos=[_repo("/a")])
        pool.record_worker_done("/unknown")  # should not raise

    def test_multiple_workers(self) -> None:
        pool = RepoWorkerPool(total_workers=4, repos=[_repo("/a")])
        pool.record_worker_start("/a")
        pool.record_worker_start("/a")
        pool.record_worker_start("/a")
        alloc = pool.get_allocation("/a")
        assert alloc is not None and alloc.active_workers == 3

        pool.record_worker_done("/a")
        alloc = pool.get_allocation("/a")
        assert alloc is not None and alloc.active_workers == 2


# ---------------------------------------------------------------------------
# Rebalancing
# ---------------------------------------------------------------------------

class TestRebalancing:
    def test_no_rebalance_when_all_repos_have_work(self) -> None:
        pool = RepoWorkerPool(
            total_workers=4,
            repos=[_repo("/a", weight=1), _repo("/b", weight=1)],
        )
        result = pool.rebalance({"/a": 5, "/b": 5})
        assert result["/a"] == 2
        assert result["/b"] == 2

    def test_idle_repo_donates_to_busy_repo(self) -> None:
        pool = RepoWorkerPool(
            total_workers=4,
            repos=[_repo("/a", weight=1), _repo("/b", weight=1)],
        )
        result = pool.rebalance({"/a": 5, "/b": 0})
        assert result["/a"] > 2  # /a should get some of /b's idle slots
        assert result["/b"] < 2  # /b donated slots

    def test_rebalance_respects_max_workers_cap(self) -> None:
        pool = RepoWorkerPool(
            total_workers=6,
            repos=[_repo("/a", weight=1, max_workers=3), _repo("/b", weight=1)],
        )
        result = pool.rebalance({"/a": 10, "/b": 0})
        assert result["/a"] <= 3  # Respects max_workers cap

    def test_rebalance_with_active_workers_not_donated(self) -> None:
        """Active workers in an idle repo are not donated."""
        pool = RepoWorkerPool(
            total_workers=4,
            repos=[_repo("/a", weight=1), _repo("/b", weight=1)],
        )
        pool.record_worker_start("/b")  # 1 active worker in /b
        result = pool.rebalance({"/a": 5, "/b": 0})
        # /b had 2 allocated, 1 active, so can donate 1
        assert result["/a"] >= 3
        # /b keeps its active worker's slot
        assert result["/b"] >= 1

    def test_rebalance_all_repos_empty_restores_base(self) -> None:
        pool = RepoWorkerPool(
            total_workers=4,
            repos=[_repo("/a", weight=1), _repo("/b", weight=1)],
        )
        # First rebalance moves slots around
        pool.rebalance({"/a": 5, "/b": 0})
        # Then all repos empty — should restore base allocations
        result = pool.rebalance({"/a": 0, "/b": 0})
        assert result["/a"] == 2
        assert result["/b"] == 2

    def test_rebalance_with_three_repos(self) -> None:
        pool = RepoWorkerPool(
            total_workers=9,
            repos=[
                _repo("/a", weight=3),
                _repo("/b", weight=3),
                _repo("/c", weight=3),
            ],
        )
        # /c has no work — its 3 slots should go to /a and /b
        result = pool.rebalance({"/a": 5, "/b": 5, "/c": 0})
        total = result["/a"] + result["/b"] + result["/c"]
        assert total <= 9
        assert result["/a"] >= 3
        assert result["/b"] >= 3

    def test_rebalance_weighted_distribution(self) -> None:
        pool = RepoWorkerPool(
            total_workers=8,
            repos=[
                _repo("/a", weight=3),
                _repo("/b", weight=1),
                _repo("/c", weight=1),
            ],
        )
        # /b and /c empty, donate to /a
        result = pool.rebalance({"/a": 10, "/b": 0, "/c": 0})
        assert result["/a"] > 4  # /a should get most of the donated slots

    def test_rebalance_updates_ready_counts(self) -> None:
        pool = RepoWorkerPool(total_workers=4, repos=[_repo("/a")])
        pool.rebalance({"/a": 7})
        alloc = pool.get_allocation("/a")
        assert alloc is not None and alloc.ready_item_count == 7


# ---------------------------------------------------------------------------
# get_all_allocations returns snapshots
# ---------------------------------------------------------------------------

class TestGetAllAllocations:
    def test_returns_snapshots_not_references(self) -> None:
        pool = RepoWorkerPool(total_workers=2, repos=[_repo("/a")])
        snap = pool.get_all_allocations()
        # Mutating the snapshot should not affect the pool
        snap["/a"].active_workers = 99
        alloc = pool.get_allocation("/a")
        assert alloc is not None and alloc.active_workers == 0

    def test_all_repos_present(self) -> None:
        pool = RepoWorkerPool(
            total_workers=4,
            repos=[_repo("/a"), _repo("/b")],
        )
        allocs = pool.get_all_allocations()
        assert set(allocs.keys()) == {"/a", "/b"}


# ---------------------------------------------------------------------------
# Thread-safety smoke test
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_start_done(self) -> None:
        pool = RepoWorkerPool(total_workers=100, repos=[_repo("/a")])
        barrier = threading.Barrier(20)

        def worker() -> None:
            barrier.wait()
            pool.record_worker_start("/a")
            pool.record_worker_done("/a")

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        alloc = pool.get_allocation("/a")
        assert alloc is not None and alloc.active_workers == 0
