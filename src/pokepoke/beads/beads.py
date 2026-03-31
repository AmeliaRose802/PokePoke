"""Beads integration - query and manage work items.

This module provides a unified interface to beads operations.
Implementation is split across:
- beads_query: Query operations
- beads_hierarchy: Parent-child relationships
- beads_management: Item management (assign, close, select)
"""

# Re-export all public functions for backward compatibility
from pokepoke.git.multi_repo_aggregator import (
    RepoQueryResult,
    aggregate_ready_work_items,
    get_aggregated_stats,
    query_repo_ready_items,
)

from .beads_hierarchy import (
    HIGH_CONFLICT_LABELS,
    all_children_complete,
    close_parent_if_complete,
    get_children,
    get_next_child_task,
    get_parent_id,
    has_feature_parent,
    is_high_conflict_risk,
    resolve_to_leaf_task,
)
from .beads_management import (
    add_comment,
    assign_and_sync_item,
    close_item,
    fail_task,
    get_total_attempts,
    increment_total_attempts,
    is_item_claimable,
    select_next_hierarchical_item,
    unassign_item,
)
from .beads_query import (
    get_beads_stats,
    get_issue_dependencies,
    get_ready_work_items,
    has_unmet_blocking_dependencies,
    is_beads_item_closed,
)
from .beads_recovery import (
    get_failed_unassign_count,
    retry_failed_unassigns,
    unassign_with_retry,
)
from .sync_strategy import (
    DaemonSync,
    ExplicitSync,
    SyncStrategy,
    get_active_sync_strategy,
    set_active_sync_strategy,
)

__all__ = [
    # Query operations
    'get_ready_work_items',
    'get_issue_dependencies',
    'get_beads_stats',
    'has_unmet_blocking_dependencies',
    'is_beads_item_closed',

    # Hierarchy operations
    'get_children',
    'get_next_child_task',
    'all_children_complete',
    'close_parent_if_complete',
    'get_parent_id',
    'has_feature_parent',
    'resolve_to_leaf_task',
    'is_high_conflict_risk',
    'HIGH_CONFLICT_LABELS',

    # Management operations
    'close_item',
    'fail_task',
    'select_next_hierarchical_item',
    'is_item_claimable',
    'assign_and_sync_item',
    'unassign_item',
    'unassign_with_retry',
    'retry_failed_unassigns',
    'get_failed_unassign_count',
    'add_comment',
    'get_total_attempts',
    'increment_total_attempts',

    # Sync strategy
    'SyncStrategy',
    'DaemonSync',
    'ExplicitSync',
    'get_active_sync_strategy',
    'set_active_sync_strategy',

    # Multi-repo aggregation
    'aggregate_ready_work_items',
    'query_repo_ready_items',
    'get_aggregated_stats',
    'RepoQueryResult',
]
