"""Proof of Concept test for Copilot SDK integration.

This script tests the SDK-based approach with a simple work item.
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from pokepoke.copilot_sdk import invoke_copilot_sdk_sync
from pokepoke.types import BeadsWorkItem


def main():
    """Run a simple POC test."""
    print("=" * 80)
    print("PROOF OF CONCEPT: GitHub Copilot SDK")
    print("=" * 80)
    print()
    
    # Create a simple test work item
    test_item = BeadsWorkItem(
        id="poc-test-1",
        title="Test SDK Integration",
        description="Simple test: Please calculate 2+2 and explain what the GitHub Copilot SDK is.",
        status="in_progress",
        issue_type="task",
        priority=2,
        labels=["poc", "sdk-test"]
    )
    
    print("Test work item created:")
    print(f"  ID: {test_item.id}")
    print(f"  Title: {test_item.title}")
    print()
    
    # Invoke Copilot SDK
    print("Invoking Copilot SDK...")
    print()
    
    result = invoke_copilot_sdk_sync(
        work_item=test_item,
        timeout=300.0,  # 5 minute timeout for POC
        deny_write=False  # Allow file tools to see if that helps
    )
    
    # Display results
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Success: {result.success}")
    print(f"Attempts: {result.attempt_count}")
    print()
    
    if result.success:
        print("Output:")
        print("-" * 80)
        print(result.output)
        print("-" * 80)
        print()
        print("✅ POC SUCCESSFUL!")
        print()
        print("The SDK approach is viable! Key observations:")
        print("- Clean async/await interface")
        print("- Real-time streaming output")
        print("- Structured event handling")
        print("- No subprocess/PowerShell complexity")
        return 0
    else:
        print("Error:")
        print(result.error)
        print()
        print("❌ POC FAILED")
        print("Check error messages above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
