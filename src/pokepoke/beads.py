"""Beads integration - query and filter work items.

This module provides a unified interface to beads operations.
Implementation is split across:
- beads_query: Query operations
- beads_hierarchy: Parent-child relationships
- beads_management: Item management and filtering
"""

# Re-export all public functions for backward compatibility
from .beads_query import (
    get_ready_work_items,
    get_issue_dependencies,
    get_beads_stats
)

from .beads_hierarchy import (
    get_children,
    get_next_child_task,
    all_children_complete,
    close_parent_if_complete,
    get_parent_id,
    has_feature_parent,
    resolve_to_leaf_task
)

from .beads_management import (
    close_item,
    create_issue,
    filter_work_items,
    get_first_ready_work_item,
    select_next_hierarchical_item,
    assign_and_sync_item,
    add_comment
)

__all__ = [
    # Query operations
    'get_ready_work_items',
    'get_issue_dependencies',
    'get_beads_stats',
    
    # Hierarchy operations
    'get_children',
    'get_next_child_task',
    'all_children_complete',
    'close_parent_if_complete',
    'get_parent_id',
    'has_feature_parent',
    'resolve_to_leaf_task',
    
    # Management operations
    'close_item',
    'create_issue',
    'filter_work_items',
    'get_first_ready_work_item',
    'select_next_hierarchical_item',
    'assign_and_sync_item',
    'add_comment',
]
