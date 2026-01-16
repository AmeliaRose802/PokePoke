#!/usr/bin/env python3
"""Minimal test of Copilot CLI invocation."""

import subprocess
import tempfile
import os

# Test 1: Direct copilot call with simple prompt via PowerShell
print("Test 1: Direct copilot call via PowerShell")
print("="*80)

result = subprocess.run(
    ['pwsh', '-Command', 'copilot -p "What is 2+2? Just answer with the number." --allow-all-tools'],
    capture_output=True,
    text=True,
    timeout=60
)

print(f"Exit code: {result.returncode}")
print(f"Stdout:\n{result.stdout}")
print(f"Stderr:\n{result.stderr}")

print("\n" + "="*80)
print("Test 2: Using temp file for prompt")
print("="*80)

# Test 2: Using temp file
prompt = "List the files in the current directory using ls or dir command."

with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
    f.write(prompt)
    prompt_file = f.name

try:
    # Use PowerShell to read file and invoke copilot
    ps_script = f'$prompt = Get-Content -Path "{prompt_file}" -Raw; copilot -p $prompt --allow-all-tools'
    
    result = subprocess.run(
        ['pwsh', '-Command', ps_script],
        capture_output=True,
        text=True,
        timeout=60
    )
    
    print(f"Exit code: {result.returncode}")
    print(f"Stdout:\n{result.stdout}")
    print(f"Stderr:\n{result.stderr}")
    
finally:
    os.unlink(prompt_file)

print("\n✅ Tests complete!")
