Your job is to address a specific beads item on your subtree then commit making sure all validation passes. 

You are working on item: {{item_id}}

**Title:** {{title}}

**Description:**
{{description}}

**Type:** {{issue_type}}
**Priority:** {{priority}}
{{#labels}}
**Labels:** {{labels}}
{{/labels}}


**Additional Context:**
Use these beads commands to get more information if needed:
- `bd show {{item_id}} --json` - View full item details
- `bd list --deps {{item_id}} --json` - Check dependencies
- `bd list --label <label> --json` - Find related items by label

**Success Criteria:**
- Provided item is fully implemented
- All pre-commit validation passes successfully
- All changes are committed and the worktree has been merged
