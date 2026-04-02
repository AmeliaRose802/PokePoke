"""MergeResult dataclass for merge_worktree return values."""

from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass
class MergeResult:
    """Result of a merge_worktree operation.

    Supports 2-tuple unpacking (success, unmerged_files) for backward
    compatibility while exposing rollback_failed for callers that need it.
    """

    success: bool
    unmerged_files: list[str] = field(default_factory=list)
    rollback_failed: bool = False

    def __iter__(self) -> Iterator[bool | list[str]]:
        """Yield (success, unmerged_files) for backward-compatible unpacking."""
        yield self.success
        yield self.unmerged_files

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int) -> bool | list[str]:
        if index == 0:
            return self.success
        if index == 1:
            return self.unmerged_files
        raise IndexError(index)
