#!/usr/bin/env python3
"""
Demo script showing how to invoke GitHub Copilot CLI programmatically.
"""

import subprocess
import json
import sys
from typing import Optional, List


def run_copilot(
    prompt: str,
    model: str = "claude-sonnet-4.5",
    allow_tools: Optional[List[str]] = None,
    deny_tools: Optional[List[str]] = None,
    allow_all_tools: bool = False,
    allow_write: bool = False,
) -> tuple[int, str, str]:
    """
    Run GitHub Copilot CLI in programmatic mode.
    
    Args:
        prompt: The prompt to send to Copilot
        model: Model to use (claude-sonnet-4.5, claude-haiku-4.5, gpt-5, etc.)
        allow_tools: List of specific tools to allow (e.g., ['shell(bd)', 'write'])
        deny_tools: List of specific tools to deny
        allow_all_tools: Allow all tools without confirmation (use carefully!)
        allow_write: Shortcut to allow file writing
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    cmd = ["copilot", "-p", prompt, "--model", model]
    
    # Add tool permissions
    if allow_all_tools:
        cmd.append("--allow-all-tools")
    elif allow_write:
        cmd.extend(["--allow-tool", "write"])
    
    if allow_tools:
        for tool in allow_tools:
            cmd.extend(["--allow-tool", tool])
    
    if deny_tools:
        for tool in deny_tools:
            cmd.extend(["--deny-tool", tool])
    
    print(f"Running: {' '.join(cmd)}")
    print("-" * 80)
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding='utf-8'
    )
    
    return result.returncode, result.stdout, result.stderr


def demo_basic_query():
    """Demo 1: Basic read-only query"""
    print("\n=== Demo 1: Basic Read-Only Query ===\n")
    
    code, stdout, stderr = run_copilot(
        prompt="What is the current directory? Use pwd command.",
        model="claude-haiku-4.5",  # Faster model for simple tasks
        allow_tools=["shell(pwd)", "shell(Get-Location)"]
    )
    
    print(stdout)
    if code != 0:
        print(f"Error: {stderr}", file=sys.stderr)


def demo_beads_check():
    """Demo 2: Check beads issue status"""
    print("\n=== Demo 2: Check Beads Issue Status ===\n")
    
    code, stdout, stderr = run_copilot(
        prompt="Use bd show command to check the status of beads issue icm_queue_c#-50 and report if it's complete",
        model="claude-sonnet-4.5",
        allow_tools=["shell(bd)"]
    )
    
    print(stdout)
    if code != 0:
        print(f"Error: {stderr}", file=sys.stderr)


def demo_file_modification():
    """Demo 3: Modify a file"""
    print("\n=== Demo 3: File Modification ===\n")
    
    code, stdout, stderr = run_copilot(
        prompt="Create a file called demo-output.txt with the text 'Created by Copilot CLI via Python!'",
        model="claude-sonnet-4.5",
        allow_write=True
    )
    
    print(stdout)
    if code != 0:
        print(f"Error: {stderr}", file=sys.stderr)


def demo_safe_git_operations():
    """Demo 4: Safe git operations (allow read, deny push)"""
    print("\n=== Demo 4: Safe Git Operations ===\n")
    
    code, stdout, stderr = run_copilot(
        prompt="Show me the last 3 git commits in a concise format",
        model="claude-haiku-4.5",
        allow_tools=["shell(git)"],
        deny_tools=["shell(git push)", "shell(git force-push)"]
    )
    
    print(stdout)
    if code != 0:
        print(f"Error: {stderr}", file=sys.stderr)


def demo_code_analysis():
    """Demo 5: Code analysis without modifications"""
    print("\n=== Demo 5: Code Analysis ===\n")
    
    code, stdout, stderr = run_copilot(
        prompt="Search for all TODO comments in the src/ directory and list them",
        model="claude-sonnet-4.5",
        allow_tools=["shell(Select-String)", "shell(rg)", "shell(grep)"]
    )
    
    print(stdout)
    if code != 0:
        print(f"Error: {stderr}", file=sys.stderr)


def demo_dangerous_with_safeguards():
    """Demo 6: Allow most operations but deny dangerous ones"""
    print("\n=== Demo 6: Broad Permissions with Safeguards ===\n")
    
    code, stdout, stderr = run_copilot(
        prompt="List all .cs files in the src directory and count them",
        allow_all_tools=True,  # Allow everything...
        deny_tools=[  # ...except these dangerous operations
            "shell(rm)",
            "shell(Remove-Item)",
            "shell(git push)",
            "shell(git force-push)",
            "shell(format)",
        ]
    )
    
    print(stdout)
    if code != 0:
        print(f"Error: {stderr}", file=sys.stderr)


def main():
    """Run all demos"""
    print("=" * 80)
    print("GitHub Copilot CLI - Python Integration Demo")
    print("=" * 80)
    
    demos = [
        demo_basic_query,
        demo_beads_check,
        demo_file_modification,
        demo_safe_git_operations,
        demo_code_analysis,
        demo_dangerous_with_safeguards,
    ]
    
    for demo in demos:
        try:
            demo()
        except Exception as e:
            print(f"Demo failed: {e}", file=sys.stderr)
        
        print("\n" + "=" * 80)
    
    print("\n✅ All demos completed!")


if __name__ == "__main__":
    # Run individual demo or all
    if len(sys.argv) > 1:
        demo_name = sys.argv[1]
        if demo_name == "basic":
            demo_basic_query()
        elif demo_name == "beads":
            demo_beads_check()
        elif demo_name == "file":
            demo_file_modification()
        elif demo_name == "git":
            demo_safe_git_operations()
        elif demo_name == "analysis":
            demo_code_analysis()
        elif demo_name == "safeguards":
            demo_dangerous_with_safeguards()
        else:
            print(f"Unknown demo: {demo_name}")
            print("Available: basic, beads, file, git, analysis, safeguards")
            sys.exit(1)
    else:
        main()
