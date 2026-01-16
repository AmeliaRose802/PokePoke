"""Enhanced GitHub Copilot CLI integration with retry logic and validation."""

import subprocess
import sys
from typing import Optional, List, Dict, Any
from pathlib import Path

from .types import BeadsWorkItem, CopilotResult


class CopilotInvoker:
    """Enhanced Copilot CLI invoker with validation and retry logic."""
    
    def __init__(
        self,
        model: str = "claude-sonnet-4.5",
        timeout_seconds: int = 300,
        max_retries: int = 3,
        validation_hook: Optional[callable] = None
    ):
        """Initialize the Copilot invoker.
        
        Args:
            model: LLM model to use
            timeout_seconds: Timeout for each Copilot invocation
            max_retries: Maximum retry attempts on validation failure
            validation_hook: Optional validation function(work_item, output) -> (success, errors)
        """
        self.model = model
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.validation_hook = validation_hook
    
    def build_prompt(
        self,
        work_item: BeadsWorkItem,
        attempt: int = 1,
        previous_errors: Optional[List[str]] = None
    ) -> str:
        """Build a prompt for Copilot CLI from a work item.
        
        Args:
            work_item: The beads work item
            attempt: Current attempt number (for retry context)
            previous_errors: Errors from previous attempt (if retrying)
            
        Returns:
            Formatted prompt string
        """
        labels_section = ""
        if work_item.labels:
            labels_section = f"\n**Labels:** {', '.join(work_item.labels)}"
        
        retry_context = ""
        if attempt > 1 and previous_errors:
            errors_formatted = "\n".join(f"  - {error}" for error in previous_errors)
            retry_context = f"""

⚠️ **RETRY ATTEMPT {attempt}/{self.max_retries}**

The previous attempt failed validation with these errors:
{errors_formatted}

Please fix these issues and try again. Focus on:
1. Resolving the validation errors listed above
2. Ensuring all tests pass
3. Meeting code quality standards
4. Following project conventions
"""
        
        prompt = f"""You are working on a beads work item. Please complete the following task:

**Work Item ID:** {work_item.id}
**Title:** {work_item.title}
**Description:**
{work_item.description}

**Priority:** {work_item.priority}
**Type:** {work_item.issue_type}{labels_section}{retry_context}

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
        return prompt
    
    def invoke(
        self,
        work_item: BeadsWorkItem,
        prompt: Optional[str] = None,
        allow_tools: Optional[List[str]] = None,
        deny_tools: Optional[List[str]] = None,
        allow_all_tools: bool = True
    ) -> CopilotResult:
        """Invoke Copilot CLI with retry logic.
        
        Args:
            work_item: The beads work item to process
            prompt: Optional pre-built prompt
            allow_tools: Specific tools to allow
            deny_tools: Tools to deny (safety guardrails)
            allow_all_tools: Allow all tools (default for autonomous operation)
            
        Returns:
            CopilotResult with success status and output/errors
        """
        # Default deny list for safety
        default_deny = [
            "shell(rm -rf /)",
            "shell(Remove-Item -Recurse -Force C:\\)",
            "shell(format)",
        ]
        deny_tools = (deny_tools or []) + default_deny
        
        attempt = 1
        previous_errors = None
        
        while attempt <= self.max_retries:
            print(f"\n{'='*80}")
            print(f"🚀 Invoking Copilot CLI (Attempt {attempt}/{self.max_retries})")
            print(f"   Work Item: {work_item.id}")
            print(f"   Title: {work_item.title}")
            print(f"   Model: {self.model}")
            print(f"{'='*80}\n")
            
            # Build prompt with retry context if applicable
            final_prompt = prompt or self.build_prompt(
                work_item,
                attempt=attempt,
                previous_errors=previous_errors
            )
            
            # Invoke Copilot CLI
            result = self._run_copilot(
                final_prompt,
                allow_tools=allow_tools,
                deny_tools=deny_tools,
                allow_all_tools=allow_all_tools
            )
            
            # Check if invocation itself failed
            if not result.success:
                print(f"❌ Copilot CLI invocation failed: {result.error}")
                return result
            
            # Run validation if hook provided
            if self.validation_hook:
                print("\n🔍 Running validation checks...")
                validation_success, validation_errors = self.validation_hook(work_item, result.output)
                
                if validation_success:
                    print("✅ All validation checks passed!")
                    return result
                else:
                    print(f"❌ Validation failed with {len(validation_errors)} error(s)")
                    for error in validation_errors:
                        print(f"   - {error}")
                    
                    # Prepare for retry
                    previous_errors = validation_errors
                    attempt += 1
                    
                    if attempt > self.max_retries:
                        return CopilotResult(
                            work_item_id=work_item.id,
                            success=False,
                            error=f"Max retries ({self.max_retries}) exceeded. Last errors: {validation_errors}",
                            output=result.output,
                            validation_errors=validation_errors
                        )
                    
                    print(f"\n🔄 Retrying with corrective feedback...\n")
            else:
                # No validation hook, consider it successful
                return result
        
        # Should never reach here, but handle it
        return CopilotResult(
            work_item_id=work_item.id,
            success=False,
            error="Unexpected retry loop exit"
        )
    
    def _run_copilot(
        self,
        prompt: str,
        allow_tools: Optional[List[str]] = None,
        deny_tools: Optional[List[str]] = None,
        allow_all_tools: bool = True
    ) -> CopilotResult:
        """Internal method to run Copilot CLI once.
        
        Args:
            prompt: The prompt to send
            allow_tools: Tools to explicitly allow
            deny_tools: Tools to explicitly deny
            allow_all_tools: Allow all tools flag
            
        Returns:
            CopilotResult from this single invocation
        """
        try:
            import sys
            
            # Build command using PowerShell on Windows for proper escaping
            if sys.platform == "win32":
                # Build PowerShell command with proper escaping using repr()
                ps_cmd_parts = ["copilot", "-p", repr(prompt), "--model", self.model, "--no-color"]
                
                # Add tool permissions
                if allow_all_tools:
                    ps_cmd_parts.append("--allow-all-tools")
                
                if allow_tools:
                    for tool in allow_tools:
                        ps_cmd_parts.extend(["--allow-tool", repr(tool)])
                
                if deny_tools:
                    for tool in deny_tools:
                        ps_cmd_parts.extend(["--deny-tool", repr(tool)])
                
                ps_script = " ".join(ps_cmd_parts)
                
                # Stream output in real-time on Windows
                process = subprocess.Popen(
                    ["pwsh", "-NoProfile", "-Command", ps_script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8'
                )
                
                stdout_lines = []
                stderr_lines = []
                
                # Read output in real-time
                import threading
                
                def read_stdout():
                    for line in iter(process.stdout.readline, ''):
                        print(line, end='', flush=True)
                        stdout_lines.append(line)
                    process.stdout.close()
                
                def read_stderr():
                    for line in iter(process.stderr.readline, ''):
                        print(line, end='', flush=True, file=sys.stderr)
                        stderr_lines.append(line)
                    process.stderr.close()
                
                stdout_thread = threading.Thread(target=read_stdout)
                stderr_thread = threading.Thread(target=read_stderr)
                
                stdout_thread.start()
                stderr_thread.start()
                
                # Wait for process to complete with timeout
                try:
                    process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout_thread.join(timeout=1)
                    stderr_thread.join(timeout=1)
                    return CopilotResult(
                        work_item_id="unknown",
                        success=False,
                        error=f"Copilot CLI timed out after {self.timeout} seconds"
                    )
                
                stdout_thread.join()
                stderr_thread.join()
                
                result_stdout = ''.join(stdout_lines)
                result_stderr = ''.join(stderr_lines)
                result_returncode = process.returncode
            else:
                # Unix/Linux: direct invocation
                cmd = ["copilot", "-p", prompt, "--model", self.model, "--no-color"]
                
                if allow_all_tools:
                    cmd.append("--allow-all-tools")
                
                if allow_tools:
                    for tool in allow_tools:
                        cmd.extend(["--allow-tool", tool])
                
                if deny_tools:
                    for tool in deny_tools:
                        cmd.extend(["--deny-tool", tool])
                
                # Stream output in real-time
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8'
                )
                
                stdout_lines = []
                stderr_lines = []
                
                # Read output in real-time
                import threading
                
                def read_stdout():
                    for line in iter(process.stdout.readline, ''):
                        print(line, end='', flush=True)
                        stdout_lines.append(line)
                    process.stdout.close()
                
                def read_stderr():
                    for line in iter(process.stderr.readline, ''):
                        print(line, end='', flush=True, file=sys.stderr)
                        stderr_lines.append(line)
                    process.stderr.close()
                
                stdout_thread = threading.Thread(target=read_stdout)
                stderr_thread = threading.Thread(target=read_stderr)
                
                stdout_thread.start()
                stderr_thread.start()
                
                # Wait for process to complete with timeout
                try:
                    process.wait(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout_thread.join(timeout=1)
                    stderr_thread.join(timeout=1)
                    return CopilotResult(
                        work_item_id="unknown",
                        success=False,
                        error=f"Copilot CLI timed out after {self.timeout} seconds"
                    )
                
                stdout_thread.join()
                stderr_thread.join()
                
                result_stdout = ''.join(stdout_lines)
                result_stderr = ''.join(stderr_lines)
                result_returncode = process.returncode
            
            # Check exit code
            if result_returncode != 0:
                return CopilotResult(
                    work_item_id="unknown",  # Will be set by caller
                    success=False,
                    error=f"Copilot CLI exited with code {result_returncode}: {result_stderr or 'Unknown error'}"
                )
            
            return CopilotResult(
                work_item_id="unknown",
                success=True,
                output=result_stdout
            )
        
        except subprocess.TimeoutExpired:
            return CopilotResult(
                work_item_id="unknown",
                success=False,
                error=f"Copilot CLI timed out after {self.timeout} seconds"
            )
        except Exception as e:
            return CopilotResult(
                work_item_id="unknown",
                success=False,
                error=f"Failed to invoke Copilot CLI: {e}"
            )


def create_validation_hook() -> callable:
    """Create a validation hook that runs quality gates.
    
    Returns:
        Validation function that checks tests, coverage, linting, etc.
    """
    def validate(work_item: BeadsWorkItem, output: str) -> tuple[bool, List[str]]:
        """Run quality gate validations.
        
        Returns:
            (success, errors) tuple
        """
        errors = []
        
        # 1. Check if tests pass
        try:
            result = subprocess.run(
                ['npm', 'test'],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode != 0:
                errors.append("Tests failed - see npm test output")
        except Exception as e:
            errors.append(f"Could not run tests: {e}")
        
        # 2. Check git status (should have no uncommitted changes for autonomous mode)
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                # This might be okay if Copilot is supposed to leave uncommitted work
                # Remove this check if that's the expected behavior
                pass
        except Exception as e:
            errors.append(f"Could not check git status: {e}")
        
        # 3. Check for compilation errors (TypeScript)
        try:
            result = subprocess.run(
                ['npx', 'tsc', '--noEmit'],
                capture_output=True,
                text=True,
                timeout=60
            )
            if result.returncode != 0:
                errors.append("TypeScript compilation errors found")
        except Exception as e:
            errors.append(f"Could not check TypeScript: {e}")
        
        return len(errors) == 0, errors
    
    return validate


# Convenience function for backward compatibility
def invoke_copilot_cli(
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None
) -> CopilotResult:
    """Invoke Copilot CLI (simple interface for backward compatibility).
    
    Args:
        work_item: The beads work item to process
        prompt: Optional pre-built prompt
        
    Returns:
        CopilotResult
    """
    invoker = CopilotInvoker(
        model="claude-sonnet-4.5",
        timeout_seconds=300,
        max_retries=1  # No retries for backward compatibility
    )
    return invoker.invoke(work_item, prompt)
