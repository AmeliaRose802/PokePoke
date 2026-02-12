#!/usr/bin/env python3
"""Pre-commit coverage checker for Python projects."""

import json
import subprocess
import sys
from pathlib import Path


def get_staged_python_files():
    """Get list of staged Python source files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=True
        )
        
        files = []
        for line in result.stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            # Include Python files in src/pokepoke, exclude tests
            if (line.endswith('.py') and 
                line.startswith('src/pokepoke/') and
                'test' not in line and
                '__pycache__' not in line):
                files.append(line)
        
        return files
    except subprocess.CalledProcessError as e:
        print(f"[error] Failed to get staged files: {e}", file=sys.stderr)
        return []


def run_tests_with_coverage():
    """Run pytest with coverage."""
    print("[test] Running tests with coverage...")
    
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "--cov=src/pokepoke",
                "--cov-report=json",
                "-q",
                "--tb=line",
                "--timeout=30"
            ],
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            print("[error] Tests failed", file=sys.stderr)
            return False
        
        return True
    except subprocess.TimeoutExpired:
        print("[error] Tests timed out", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[error] Test execution failed: {e}", file=sys.stderr)
        return False


def check_coverage(files, min_coverage=80):
    """Check coverage for specified files."""
    if not files:
        return True
    
    coverage_file = Path("coverage.json")
    if not coverage_file.exists():
        print("[warn] No coverage data found", file=sys.stderr)
        return False
    
    with open(coverage_file) as f:
        coverage = json.load(f)
    
    failed_files = []
    passed_count = 0
    
    for file_path in files:
        # Try to find coverage data for this file
        file_data = None
        full_path = Path(file_path).resolve()
        
        for cov_file, data in coverage["files"].items():
            if Path(cov_file).resolve() == full_path:
                file_data = data
                break
        
        if not file_data:
            print(f"  [warn] {file_path} - No coverage data (needs tests)")
            failed_files.append(file_path)
            continue
        
        line_coverage = file_data["summary"]["percent_covered"]
        
        if line_coverage < min_coverage:
            print(f"  [FAIL] {file_path} - Coverage: {line_coverage:.1f}% (minimum: {min_coverage}%)")
            failed_files.append(file_path)
        else:
            passed_count += 1
    
    if failed_files:
        print(f"\n[FAIL] {len(failed_files)} file(s) below {min_coverage}% coverage")
        print("\nAdd tests to increase coverage for these files.")
        return False
    
    print(f"[PASS] Coverage {min_coverage}%+ ({passed_count} files)")
    return True


def main():
    """Main execution."""
    staged_files = get_staged_python_files()
    
    if not staged_files:
        print("No Python source files staged for commit")
        return 0
    
    print(f"Checking coverage for {len(staged_files)} staged file(s)...")
    
    # Run tests
    if not run_tests_with_coverage():
        return 1
    
    # Check coverage
    if not check_coverage(staged_files):
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
