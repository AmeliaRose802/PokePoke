"""Beads integration - query and manage work items.

This module provides a unified interface to beads operations.
Implementation is split across:
- beads_query: Query operations
- beads_hierarchy: Parent-child relationships
- beads_management: Item management (assign, close, select)
"""

# Re-export all public functions for backward compatibility
from .beads_query import (
    get_ready_work_items,
    get_issue_dependencies,
    get_beads_stats,
    has_unmet_blocking_dependencies
)

from .beads_hierarchy import (
    get_children,
    get_next_child_task,
    all_children_complete,
    close_parent_if_complete,
    get_parent_id,
    has_feature_parent,
    resolve_to_leaf_task,
    is_high_conflict_risk,
    HIGH_CONFLICT_LABELS,
)

from .beads_management import (
    close_item,
    select_next_hierarchical_item,
    is_item_claimable,
    assign_and_sync_item,
    unassign_item,
    add_comment
)

from .beads_recovery import (
    unassign_with_retry,
    retry_failed_unassigns,
    get_failed_unassign_count,
)

from .multi_repo_aggregator import (
    aggregate_ready_work_items,
    query_repo_ready_items,
    get_aggregated_stats,
    RepoQueryResult,
)

__all__ = [
    # Query operations
    'get_ready_work_items',
    'get_issue_dependencies',
    'get_beads_stats',
    'has_unmet_blocking_dependencies',

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
    'select_next_hierarchical_item',
    'is_item_claimable',
    'assign_and_sync_item',
    'unassign_item',
    'unassign_with_retry',
    'retry_failed_unassigns',
    'get_failed_unassign_count',
    'add_comment',

    # Multi-repo aggregation
    'aggregate_ready_work_items',
    'query_repo_ready_items',
    'get_aggregated_stats',
    'RepoQueryResult',
]
