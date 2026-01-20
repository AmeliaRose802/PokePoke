"""GitHub Copilot CLI integration."""

import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .types import BeadsWorkItem, CopilotResult, RetryConfig
from .prompts import PromptService


def get_allowed_directories() -> list[str]:
    """Get the list of allowed directories for Copilot CLI access.
    
    Returns:
        List of absolute paths that Copilot is allowed to access
    """
    allowed = []
    
    # Always add current directory (worktree or main repo)
    current_dir = os.getcwd()
    allowed.append(current_dir)
    
    # Add main repo root if different from current
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True
        )
        git_common_dir = result.stdout.strip()
        repo_root = str(Path(git_common_dir).parent.resolve())
        if repo_root != current_dir:
            allowed.append(repo_root)
    except (subprocess.CalledProcessError, Exception):
        pass  # If git command fails, just use current dir
    
    return allowed


def build_prompt_from_template(
    work_item: BeadsWorkItem,
    template_name: str = "beads-item"
) -> str:
    """Build a prompt from a template file with proper variable substitution.
    
    Args:
        work_item: The beads work item
        template_name: Name of the template file (without .md extension)
        
    Returns:
        Rendered prompt string with all variables substituted
    """
    service = PromptService()
    
    # Get allowed directories
    allowed_dirs = get_allowed_directories()
    
    # Build variables dictionary
    variables = {
        "item_id": work_item.id,
        "title": work_item.title,
        "description": work_item.description or "",
        "issue_type": work_item.issue_type,
        "priority": work_item.priority,
        "labels": ", ".join(work_item.labels) if work_item.labels else None,
        "allowed_directories": allowed_dirs,
    }
    
    return service.load_and_render(template_name, variables)


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


def is_rate_limited(stderr_text: str, returncode: int) -> bool:
    """Detect if an error is due to rate limiting.
    
    Args:
        stderr_text: Standard error output from the process
        returncode: Exit code from the process
        
    Returns:
        True if error appears to be rate limiting, False otherwise
    """
    if not stderr_text:
        return False
    
    # Common rate limit indicators
    rate_limit_indicators = [
        "429",  # HTTP status code
        "rate limit",
        "too many requests",
        "throttle",
        "quota exceeded",
        "try again later"
    ]
    
    stderr_lower = stderr_text.lower()
    return any(indicator in stderr_lower for indicator in rate_limit_indicators)


def is_transient_error(stderr_text: str, returncode: int) -> bool:
    """Detect if an error is transient and retryable.
    
    Args:
        stderr_text: Standard error output from the process
        returncode: Exit code from the process
        
    Returns:
        True if error appears to be transient, False otherwise
    """
    if not stderr_text:
        return False
    
    # Common transient error indicators
    transient_indicators = [
        "timeout",
        "timed out",
        "connection",
        "network",
        "temporary",
        "503",  # Service unavailable
        "502",  # Bad gateway
        "504",  # Gateway timeout
    ]
    
    stderr_lower = stderr_text.lower()
    return any(indicator in stderr_lower for indicator in transient_indicators)


def calculate_backoff_delay(
    attempt: int, 
    config: RetryConfig
) -> float:
    """Calculate backoff delay with exponential backoff and jitter.
    
    Args:
        attempt: Current retry attempt (0-indexed)
        config: Retry configuration
        
    Returns:
        Delay in seconds before next retry
    """
    # Calculate exponential backoff: initial_delay * (backoff_factor ^ attempt)
    delay = config.initial_delay * (config.backoff_factor ** attempt)
    
    # Cap at max_delay
    delay = min(delay, config.max_delay)
    
    # Add jitter to prevent thundering herd (±25% random variation)
    if config.jitter:
        jitter_range = delay * 0.25
        delay = delay + random.uniform(-jitter_range, jitter_range)
        delay = max(0.1, delay)  # Ensure minimum delay of 0.1s
    
    return delay


def invoke_copilot_cli(
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    timeout: Optional[float] = None,
    deny_write: bool = False
) -> CopilotResult:
    """Invoke GitHub Copilot CLI with a work item, with retry logic.
    
    Args:
        work_item: The beads work item to process.
        prompt: Optional pre-built prompt (if not provided, will build one).
        retry_config: Retry configuration (uses defaults if not provided).
        timeout: Maximum execution time in seconds (default: 7200 = 2 hours).
        deny_write: If True, deny file write tools (for beads-only agents).
        
    Returns:
        Result of the Copilot CLI invocation.
    """
    config = retry_config or RetryConfig()
    final_prompt = prompt or build_prompt(work_item)
    max_timeout = timeout or 7200.0  # Default 2 hours
    start_time = time.time()
    
    print(f"\n📋 Invoking Copilot CLI for work item: {work_item.id}")
    print(f"   Title: {work_item.title}")
    print(f"   ⏱️  Max timeout: {max_timeout/60:.1f} minutes\n")
    print("=" * 60)
    print()
    
    for attempt in range(config.max_retries + 1):
        if attempt > 0:
            # Calculate and apply backoff delay
            delay = calculate_backoff_delay(attempt - 1, config)
            print(f"\n⏳ Retry attempt {attempt}/{config.max_retries}")
            print(f"   Waiting {delay:.1f}s before retry...")
            time.sleep(delay)
            print()
    
        try:
            # Write prompt to temp file and create a PowerShell script to invoke copilot
            # This completely avoids all escaping/parsing issues
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(final_prompt)
                prompt_file = f.name
            
            # Create PowerShell script to run copilot in non-interactive mode
            # Set environment variables to disable interactive prompts
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ps1', delete=False, encoding='utf-8') as f:
                # Set environment to non-interactive mode
                f.write('$env:CI = "true"\n')  # Many tools check CI env to disable prompts
                f.write('$env:COPILOT_NON_INTERACTIVE = "1"\n')  # Explicit non-interactive flag
                f.write(f'$prompt = Get-Content -Path "{prompt_file}" -Raw\n')
                # Build copilot command with optional write denial
                # NOTE: No --add-dir restrictions - allow access to all directories
                if deny_write:
                    f.write('copilot -p $prompt --allow-all-tools --deny-tool "write" --deny-tool "edit" --no-color\n')
                else:
                    f.write('copilot -p $prompt --allow-all-tools --no-color\n')
                script_file = f.name
            
            try:
                # Execute the PowerShell script with streaming output
                cmd = ['pwsh', '-NoProfile', '-File', script_file]
                
                # Use Popen for streaming output with UTF-8 encoding
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',  # Replace invalid UTF-8 sequences instead of crashing
                    bufsize=1,  # Line buffered
                    universal_newlines=True
                )
                
                # Collect output while streaming it
                stdout_lines = []
                stderr_lines = []
                
                # Stream stdout in real-time
                if process.stdout:
                    for line in process.stdout:
                        print(line, end='', flush=True)
                        stdout_lines.append(line)
                
                # Calculate remaining timeout
                elapsed = time.time() - start_time
                remaining_timeout = max(30, max_timeout - elapsed)  # At least 30s
                
                # Wait for process to complete with timeout
                try:
                    process.wait(timeout=remaining_timeout)
                except subprocess.TimeoutExpired:
                    print(f"\n⏱️  Process timeout after {remaining_timeout:.0f}s - terminating...")
                    process.kill()
                    process.wait()  # Clean up zombie process
                    raise  # Re-raise to handle in outer try/except
                
                # Capture any stderr
                if process.stderr:
                    stderr_text = process.stderr.read()
                    if stderr_text:
                        print(stderr_text, file=sys.stderr, flush=True)
                        stderr_lines.append(stderr_text)
                
                stdout_text = ''.join(stdout_lines)
                stderr_text = ''.join(stderr_lines)
                
            finally:
                # Clean up temp files
                try:
                    os.unlink(prompt_file)
                    os.unlink(script_file)
                except:
                    pass
            
            print()
            print("=" * 60)
            
            # Success case
            if process.returncode == 0:
                return CopilotResult(
                    work_item_id=work_item.id,
                    success=True,
                    output=stdout_text,
                    attempt_count=attempt + 1
                )
            
            # Check if error is retryable
            is_rate_limit = is_rate_limited(stderr_text, process.returncode)
            is_transient = is_transient_error(stderr_text, process.returncode)
            
            if is_rate_limit:
                print(f"\n🚦 Rate limit detected (HTTP 429 or similar)")
            elif is_transient:
                print(f"\n⚠️  Transient error detected")
            
            # If not retryable or out of retries, return failure
            if not (is_rate_limit or is_transient) or attempt >= config.max_retries:
                return CopilotResult(
                    work_item_id=work_item.id,
                    success=False,
                    error=f"Copilot CLI exited with code {process.returncode}: {stderr_text or 'Unknown error'}",
                    attempt_count=attempt + 1,
                    is_rate_limited=is_rate_limit
                )
            
            # Otherwise, continue to next retry attempt
            
        except subprocess.TimeoutExpired:
            # Timeout means the process hung - always return failure, don't retry
            elapsed = time.time() - start_time
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                error=f"Copilot CLI timed out after {elapsed:.0f}s (max: {max_timeout:.0f}s)",
                attempt_count=attempt + 1
            )
            
        except Exception as e:
            # Unexpected errors are not retried
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                error=f"Failed to invoke Copilot CLI: {e}",
                attempt_count=attempt + 1
            )
    
    # Should not reach here, but just in case
    return CopilotResult(
        work_item_id=work_item.id,
        success=False,
        error="Exhausted all retry attempts",
        attempt_count=config.max_retries + 1
        )
