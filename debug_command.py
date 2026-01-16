#!/usr/bin/env python3
"""Debug what command is actually being run."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from pokepoke.types import BeadsWorkItem

work_item = BeadsWorkItem(
    id="test-123",
    title="Simple test task",
    description="Just a simple test",
    status="open",
    priority=2,
    issue_type="task"
)

# Build the prompt like the enhanced invoker does
prompt = f"""You are working on a beads work item. Please complete the following task:

**Work Item ID:** {work_item.id}
**Title:** {work_item.title}
**Description:**
{work_item.description}

**Priority:** {work_item.priority}
**Type:** {work_item.issue_type}

**Requirements:**
1. Follow coding standards and project conventions
2. Add appropriate tests with 80%+ coverage
3. Update documentation if needed
4. Ensure all quality gates pass (linting, type checking, etc.)
5. Commit changes with descriptive conventional commit messages
6. DO NOT bypass pre-commit hooks with --no-verify
7. DO NOT modify quality gate scripts in .githooks/

**Project Context:**
- This is an autonomous workflow orchestrator (PokePoke)
- Uses beads for issue tracking, TypeScript/Node.js stack
- Quality gates are strictly enforced via pre-commit hooks
- All changes must pass tests, coverage, and quality checks

Work independently and complete the task. When finished, report:
✅ What was implemented
✅ Test coverage added
✅ Any blockers or dependencies discovered
"""

print(f"Prompt length: {len(prompt)} characters")
print(f"\nPrompt preview (first 200 chars):\n{prompt[:200]}...")

# Build PowerShell command
ps_cmd_parts = ["copilot", "-p", repr(prompt), "--model", "claude-sonnet-4.5", "--no-color", "--allow-all-tools"]
ps_script = " ".join(ps_cmd_parts)

print(f"\nPowerShell script length: {len(ps_script)} characters")
print(f"\nFirst 500 chars of PS script:\n{ps_script[:500]}...")
