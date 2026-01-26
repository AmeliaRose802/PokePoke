#!/usr/bin/env python3
"""Quick test of PokePoke functionality."""

from src.pokepoke.beads import get_ready_work_items, get_issue_dependencies
from src.pokepoke.copilot import build_prompt


def main():
    print("\n" + "=" * 80)
    print("🚀 POKEPOKE - TESTING CORE FUNCTIONALITY")
    print("=" * 80 + "\n")
    
    # Test 1: Query ready work items
    print("📋 Test 1: Querying ready work items from beads...")
    try:
        items = get_ready_work_items()
        print(f"✅ SUCCESS: Found {len(items)} ready work items\n")
        
        if items:
            print("Top 5 ready items:")
            for i, item in enumerate(items[:5], 1):
                print(f"  {i}. [{item.id}] {item.title}")
                print(f"     Type: {item.issue_type} | Priority: {item.priority}")
                if item.labels:
                    print(f"     Labels: {', '.join(item.labels)}")
                print()
        else:
            print("  (No ready work items found)")
    except Exception as e:
        print(f"❌ FAILED: {e}\n")
        return 1
    
    # Test 2: Get issue details with dependencies
    if items:
        print("\n📋 Test 2: Getting detailed info for first item...")
        first_item = items[0]
        try:
            issue = get_issue_dependencies(first_item.id)
            if issue:
                print(f"✅ SUCCESS: Retrieved details for {issue.id}")
                print(f"   Title: {issue.title}")
                if issue.dependencies:
                    print(f"   Dependencies: {len(issue.dependencies)}")
                if issue.dependents:
                    print(f"   Dependents: {len(issue.dependents)}")
            else:
                print(f"⚠️  No detailed info found for {first_item.id}")
        except Exception as e:
            print(f"❌ FAILED: {e}\n")
            return 1
    
    # Test 3: Build Copilot prompt
    if items:
        print("\n📋 Test 3: Building Copilot CLI prompt...")
        try:
            prompt = build_prompt(items[0])
            print("✅ SUCCESS: Prompt generated")
            print(f"   Prompt length: {len(prompt)} characters")
            print("\n   Preview (first 200 chars):")
            print("   " + "-" * 60)
            print("   " + prompt[:200].replace("\n", "\n   ") + "...")
            print("   " + "-" * 60)
        except Exception as e:
            print(f"❌ FAILED: {e}\n")
            return 1
    
    print("\n" + "=" * 80)
    print("✅ ALL TESTS PASSED - POKEPOKE CORE FUNCTIONALITY WORKING")
    print("=" * 80 + "\n")
    
    print("📝 Note: This test validates core components:")
    print("   - Beads integration (querying work items)")
    print("   - Issue dependency retrieval")
    print("   - Copilot prompt generation")
    print("\n⚠️  Full orchestrator (worktree creation, Copilot invocation, validation)")
    print("   is not yet implemented in the main source tree.")
    print("\n💡 To implement a work item manually, you can use:")
    print("   python -c \"from src.pokepoke.copilot import invoke_copilot; ...")
    
    return 0


if __name__ == "__main__":
    exit(main())
