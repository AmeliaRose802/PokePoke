"""GitHub Copilot CLI integration."""

import subprocess
import sys
from typing import Optional

from .types import BeadsWorkItem, CopilotResult


def build_prompt(work_item: BeadsWorkItem) -> str:
    """Build a prompt for Copilot CLI from a work item.
    
    Args:
        work_item: The beads work item.
        
    Returns:
        Formatted prompt string.
    """
    labels_section = ""
    if work_item.labels:
        labels_section = f"\n**Labels:** {', '.join(work_item.labels)}"
    
    return f"""You are working on a beads work item. Please complete the following task:

**Work Item ID:** {work_item.id}
**Title:** {work_item.title}
**Description:**
{work_item.description}

**Priority:** {work_item.priority}
**Type:** {work_item.issue_type}{labels_section}

Please implement this task according to the project guidelines and best practices. Make sure to:
1. Follow the coding standards
2. Add appropriate tests
3. Update documentation if needed
4. Commit your changes with a descriptive message

Work independently and let me know when complete."""


def invoke_copilot_cli(
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None
) -> CopilotResult:
    """Invoke GitHub Copilot CLI with a work item.
    
    Args:
        work_item: The beads work item to process.
        prompt: Optional pre-built prompt (if not provided, will build one).
        
    Returns:
        Result of the Copilot CLI invocation.
    """
    final_prompt = prompt or build_prompt(work_item)
    
    print(f"\n📋 Invoking Copilot CLI for work item: {work_item.id}")
    print(f"   Title: {work_item.title}\n")
    
    try:
        # Write prompt to temp file and create a PowerShell script to invoke copilot
        # This completely avoids all escaping/parsing issues
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(final_prompt)
            prompt_file = f.name
        
        # Create PowerShell script to run copilot
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8') as f:
            f.write(f'$prompt = Get-Content -Path "{prompt_file}" -Raw\n')
            f.write('copilot -p $prompt --allow-all-tools --no-color\n')
            script_file = f.name
        
        try:
            # Execute the PowerShell script
            cmd = ['pwsh', '-NoProfile', '-File', script_file]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
        finally:
            # Clean up temp files
            try:
                os.unlink(prompt_file)
                os.unlink(script_file)
            except:
                pass
        
        # Echo output
        if result.stdout:
            print(result.stdout)
        
        if result.stderr:
            print(result.stderr, flush=True)
        
        if result.returncode != 0:
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                error=f"Copilot CLI exited with code {result.returncode}: {result.stderr or 'Unknown error'}"
            )
        
        return CopilotResult(
            work_item_id=work_item.id,
            success=True,
            output=result.stdout
        )
        
    except subprocess.TimeoutExpired:
        return CopilotResult(
            work_item_id=work_item.id,
            success=False,
            error="Copilot CLI timed out after 5 minutes"
        )
    except Exception as e:
        return CopilotResult(
            work_item_id=work_item.id,
            success=False,
            error=f"Failed to invoke Copilot CLI: {e}"
        )
