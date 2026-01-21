Your job is to address a specific beads item on your subtree then commit making sure all validation passes. 

**[WARNING] CRITICAL: DIRECTORY ACCESS RESTRICTIONS**

YOU MUST NEVER ATTEMPT TO ACCESS ANY DIRECTORY OUTSIDE THE ALLOWED DIRECTORIES! YOU WILL GET STUCK AND DIE!!!

**Allowed Directories (you can ONLY access these):**
{{#allowed_directories}}
- `{{.}}`
{{/allowed_directories}}

**DO NOT access:**
- Parent directories outside the repo
- System directories (C:\Windows, /etc, /usr, etc.)
- User home directories
- Any path not explicitly listed above

You are working on item: {{item_id}}

**Title:** {{title}}

**Description:**
{{description}}

**Type:** {{issue_type}}
**Priority:** {{priority}}
{{#labels}}
**Labels:** {{labels}}
{{/labels}}

You should only complete the work and commit. Closing the beads item will be handled by the orchestrator.

**Additional Context:**
Use these beads commands to get more information if needed:
- `bd show {{item_id}} --json` - View full item details
- `bd list --deps {{item_id}} --json` - Check dependencies
- `bd list --label <label> --json` - Find related items by label

**Success Criteria:**
- Provided item is fully implemented
- All pre-commit validation passes successfully
- All changes are committed
