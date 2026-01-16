#!/usr/bin/env python3
"""Test enhanced invoker with simple prompt."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from pokepoke.copilot_enhanced import CopilotInvoker
from pokepoke.types import BeadsWorkItem

# Create very simple work item
work_item = BeadsWorkItem(
    id="test-simple",
    title="Count files",
    description="Count the number of TypeScript files in the src directory",
    status="open",
    priority=2,
    issue_type="task"
)

# Create invoker WITHOUT validation
print("Testing Copilot invoker without validation...")
invoker = CopilotInvoker(
    model="claude-haiku-4.5",  # Faster model
    timeout_seconds=60,
    max_retries=1,
    validation_hook=None  # No validation
)

print("\nInvoking Copilot...\n")
result = invoker.invoke(work_item)

print("\n" + "="*80)
if result.success:
    print("✅ SUCCESS!")
    print(f"\nOutput:\n{result.output}")
else:
    print("❌ FAILED!")
    print(f"\nError: {result.error}")
