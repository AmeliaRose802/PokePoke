#!/usr/bin/env python3
"""
Example: Using the enhanced Copilot invoker with retry logic and validation.

This demonstrates the autonomous workflow pattern with quality gates.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from pokepoke.copilot_enhanced import CopilotInvoker, create_validation_hook
from pokepoke.types import BeadsWorkItem


def example_basic_invocation():
    """Example 1: Basic invocation without validation (backward compatible)"""
    print("\n" + "="*80)
    print("Example 1: Basic Invocation (No Validation)")
    print("="*80 + "\n")
    
    # Create a mock work item
    work_item = BeadsWorkItem(
        id="test-123",
        title="Add timestamp to log messages",
        description="Update the logging utility to include timestamps in all log messages",
        status="in_progress",
        priority=2,
        issue_type="task",
        labels=["logging", "utilities"]
    )
    
    # Create invoker without validation
    invoker = CopilotInvoker(
        model="claude-haiku-4.5",  # Faster model for simple tasks
        timeout_seconds=120,
        max_retries=1
    )
    
    # Invoke
    result = invoker.invoke(work_item)
    
    if result.success:
        print(f"\n✅ Success! Work item {work_item.id} completed.")
    else:
        print(f"\n❌ Failed: {result.error}")


def example_with_validation():
    """Example 2: Invocation with validation and automatic retry"""
    print("\n" + "="*80)
    print("Example 2: With Validation and Retry")
    print("="*80 + "\n")
    
    # Create a mock work item
    work_item = BeadsWorkItem(
        id="test-456",
        title="Fix failing unit test in orchestrator",
        description="The test_worktree_creation test is failing. Debug and fix it.",
        status="in_progress",
        priority=1,
        issue_type="bug",
        labels=["tests", "orchestrator"]
    )
    
    # Create validation hook
    validation_hook = create_validation_hook()
    
    # Create invoker with validation and retries
    invoker = CopilotInvoker(
        model="claude-sonnet-4.5",  # More capable model
        timeout_seconds=300,
        max_retries=3,  # Will retry up to 3 times on validation failure
        validation_hook=validation_hook
    )
    
    # Invoke - will automatically retry with corrective feedback if validation fails
    result = invoker.invoke(work_item)
    
    if result.success:
        print(f"\n✅ Success after {result.attempt_count} attempt(s)!")
    else:
        print(f"\n❌ Failed after {result.attempt_count} attempts")
        print(f"   Error: {result.error}")
        if result.validation_errors:
            print("   Validation errors:")
            for error in result.validation_errors:
                print(f"     - {error}")


def example_with_custom_validation():
    """Example 3: Custom validation logic"""
    print("\n" + "="*80)
    print("Example 3: Custom Validation Logic")
    print("="*80 + "\n")
    
    # Custom validation function
    def custom_validator(work_item: BeadsWorkItem, output: str) -> tuple[bool, list[str]]:
        """Custom validation: check if specific keywords are in output."""
        errors = []
        
        # Check if Copilot mentioned running tests
        if "test" not in output.lower():
            errors.append("Output does not mention running tests")
        
        # Check if Copilot mentioned committing
        if "commit" not in output.lower():
            errors.append("Output does not mention committing changes")
        
        # Check if specific keywords for this work item are present
        if work_item.issue_type == "feature" and "documentation" not in output.lower():
            errors.append("Feature work should update documentation")
        
        return len(errors) == 0, errors
    
    work_item = BeadsWorkItem(
        id="test-789",
        title="Add caching to beads query results",
        description="Implement LRU cache for beads query results to improve performance",
        status="in_progress",
        priority=2,
        issue_type="feature",
        labels=["performance", "beads"]
    )
    
    invoker = CopilotInvoker(
        model="claude-sonnet-4.5",
        timeout_seconds=300,
        max_retries=3,
        validation_hook=custom_validator
    )
    
    result = invoker.invoke(work_item)
    
    if result.success:
        print(f"\n✅ Custom validation passed!")
    else:
        print(f"\n❌ Custom validation failed: {result.error}")


def example_with_tool_restrictions():
    """Example 4: Safety guardrails with tool restrictions"""
    print("\n" + "="*80)
    print("Example 4: Tool Restrictions for Safety")
    print("="*80 + "\n")
    
    work_item = BeadsWorkItem(
        id="test-999",
        title="Analyze code quality metrics",
        description="Run static analysis and report code quality issues",
        status="in_progress",
        priority=3,
        issue_type="task",
        labels=["quality", "analysis"]
    )
    
    invoker = CopilotInvoker(
        model="claude-haiku-4.5",
        timeout_seconds=180
    )
    
    # Allow analysis but deny modifications
    result = invoker.invoke(
        work_item,
        allow_all_tools=False,
        allow_tools=[
            "shell(npx eslint)",
            "shell(npx tsc --noEmit)",
            "shell(git diff --stat)",
            "readFile",
            "grepSearch"
        ],
        deny_tools=[
            "writeFile",
            "editFile",
            "shell(git commit)",
            "shell(git push)"
        ]
    )
    
    if result.success:
        print(f"\n✅ Analysis complete (read-only mode)")
    else:
        print(f"\n❌ Analysis failed: {result.error}")


def example_with_custom_prompt():
    """Example 5: Custom prompt with specific instructions"""
    print("\n" + "="*80)
    print("Example 5: Custom Prompt")
    print("="*80 + "\n")
    
    work_item = BeadsWorkItem(
        id="test-111",
        title="Refactor orchestrator loop",
        description="Extract the main loop logic into smaller, testable functions",
        status="in_progress",
        priority=2,
        issue_type="task",
        labels=["refactoring", "orchestrator"]
    )
    
    # Build custom prompt with very specific instructions
    custom_prompt = f"""You are refactoring code for work item {work_item.id}.

**Task:** {work_item.title}

**Specific Requirements:**
1. Extract each distinct operation into its own function
2. Each function should be <50 lines
3. Add docstrings with examples
4. Add unit tests for each new function
5. Ensure 100% test coverage for new code
6. Use type hints for all parameters
7. Follow Google Python style guide

**Files to modify:**
- pokepoke/orchestrator.py (main refactor)
- tests/orchestrator.spec.ts (add new tests)

**DO NOT:**
- Change the public API
- Modify existing tests (add new ones)
- Touch any .githooks/ files

Begin the refactoring now. Report what you changed and test coverage achieved.
"""
    
    invoker = CopilotInvoker(
        model="claude-sonnet-4.5",
        timeout_seconds=300
    )
    
    result = invoker.invoke(work_item, prompt=custom_prompt)
    
    if result.success:
        print(f"\n✅ Refactoring complete!")
    else:
        print(f"\n❌ Refactoring failed: {result.error}")


def main():
    """Run all examples or specific one"""
    examples = {
        "basic": example_basic_invocation,
        "validation": example_with_validation,
        "custom": example_with_custom_validation,
        "safety": example_with_tool_restrictions,
        "prompt": example_with_custom_prompt,
    }
    
    if len(sys.argv) > 1:
        example_name = sys.argv[1]
        if example_name in examples:
            examples[example_name]()
        else:
            print(f"Unknown example: {example_name}")
            print(f"Available: {', '.join(examples.keys())}")
            sys.exit(1)
    else:
        # Run all examples
        print("\n" + "="*80)
        print("Enhanced Copilot Invoker Examples")
        print("="*80)
        
        for name, example_func in examples.items():
            try:
                example_func()
            except Exception as e:
                print(f"\n❌ Example '{name}' failed: {e}")
        
        print("\n" + "="*80)
        print("All examples completed!")
        print("="*80 + "\n")


if __name__ == "__main__":
    main()
