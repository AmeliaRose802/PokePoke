"""Performance metrics for the merge queue.

Extracted into its own module to keep types.py under the file-length limit.
"""

from dataclasses import dataclass, field
from statistics import mean
from typing import Any


@dataclass
class MergeQueueStats:
    """Performance metrics for the merge queue.

    Tracks throughput, latency, and failure rates for the serialized merge
    pipeline so operators can identify bottlenecks.
    """

    # Counters
    total_merges: int = 0
    successful_merges: int = 0
    failed_merges: int = 0
    total_rebases: int = 0
    successful_rebases: int = 0
    failed_rebases: int = 0
    high_conflict_merges: int = 0

    # Timing samples (seconds)
    merge_durations: list[float] = field(default_factory=list)
    wait_times: list[float] = field(default_factory=list)
    queue_depth_samples: list[int] = field(default_factory=list)
    double_rebase_overhead_seconds: list[float] = field(default_factory=list)

    @property
    def avg_merge_duration(self) -> float:
        return mean(self.merge_durations) if self.merge_durations else 0.0

    @property
    def max_merge_duration(self) -> float:
        return max(self.merge_durations) if self.merge_durations else 0.0

    @property
    def avg_wait_time(self) -> float:
        return mean(self.wait_times) if self.wait_times else 0.0

    @property
    def max_wait_time(self) -> float:
        return max(self.wait_times) if self.wait_times else 0.0

    @property
    def max_queue_depth(self) -> int:
        return max(self.queue_depth_samples) if self.queue_depth_samples else 0

    @property
    def avg_queue_depth(self) -> float:
        return mean(self.queue_depth_samples) if self.queue_depth_samples else 0.0

    @property
    def rebase_success_rate(self) -> float:
        """Fraction of rebases that succeeded (0.0-1.0)."""
        return self.successful_rebases / self.total_rebases if self.total_rebases else 0.0

    @property
    def avg_double_rebase_overhead(self) -> float:
        return mean(self.double_rebase_overhead_seconds) if self.double_rebase_overhead_seconds else 0.0

    def copy(self) -> "MergeQueueStats":
        """Return a shallow copy with independent lists."""
        return MergeQueueStats(
            total_merges=self.total_merges,
            successful_merges=self.successful_merges,
            failed_merges=self.failed_merges,
            total_rebases=self.total_rebases,
            successful_rebases=self.successful_rebases,
            failed_rebases=self.failed_rebases,
            high_conflict_merges=self.high_conflict_merges,
            merge_durations=list(self.merge_durations),
            wait_times=list(self.wait_times),
            queue_depth_samples=list(self.queue_depth_samples),
            double_rebase_overhead_seconds=list(self.double_rebase_overhead_seconds),
        )

    def to_summary_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable summary (no raw sample lists)."""
        return {
            "total_merges": self.total_merges,
            "successful_merges": self.successful_merges,
            "failed_merges": self.failed_merges,
            "total_rebases": self.total_rebases,
            "successful_rebases": self.successful_rebases,
            "failed_rebases": self.failed_rebases,
            "high_conflict_merges": self.high_conflict_merges,
            "avg_merge_duration_s": round(self.avg_merge_duration, 3),
            "max_merge_duration_s": round(self.max_merge_duration, 3),
            "avg_wait_time_s": round(self.avg_wait_time, 3),
            "max_wait_time_s": round(self.max_wait_time, 3),
            "max_queue_depth": self.max_queue_depth,
            "avg_queue_depth": round(self.avg_queue_depth, 2),
            "rebase_success_rate": round(self.rebase_success_rate, 3),
            "avg_double_rebase_overhead_s": round(self.avg_double_rebase_overhead, 3),
        }
