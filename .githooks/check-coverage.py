#!/usr/bin/env python3
"""Pre-commit coverage checker for Python projects.

Works correctly in both regular repositories and git worktrees.
Explicitly resolves the repo/worktree root to avoid CWD dependency issues.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def get_repo_root() -> Path:
    """Get the git repository or worktree root directory.

    Uses 'git rev-parse --show-toplevel' which correctly returns
    the worktree root when running inside a git worktree.
    Falls back to the parent directory of the script location.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        # Fallback: script is in .githooks/, so parent is repo root
        return Path(__file__).resolve().parent.parent


def get_staged_python_files() -> list[str]:
    """Get list of staged Python source files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=True,
        )

        files = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Include Python files in src/pokepoke, exclude tests
            if (
                line.endswith(".py")
                and line.startswith("src/pokepoke/")
                and "test" not in line
                and "__pycache__" not in line
            ):
                files.append(line)

        return files
    except subprocess.CalledProcessError as e:
        print(f"[error] Failed to get staged files: {e}", file=sys.stderr)
        return []


def run_tests_with_coverage(repo_root: Path) -> bool:
    """Run pytest with coverage from the repo root."""
    print("[test] Running tests with coverage...")

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--cov=src/pokepoke",
                "--cov-report=json",
                "-q",
                "--tb=line",
                "--timeout=30",
            ],
            text=True,
            timeout=300,
            cwd=str(repo_root),
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


def _normalize_path(p: Path) -> str:
    """Normalize a path for comparison (lowercase + consistent separators)."""
    return os.path.normcase(os.path.normpath(str(p)))


def check_coverage(
    files: list[str], repo_root: Path, min_coverage: int = 80
) -> bool:
    """Check coverage for specified files.

    Resolves all paths relative to repo_root to work correctly
    in both regular repositories and git worktrees.
    """
    if not files:
        return True

    coverage_file = repo_root / "coverage.json"
    if not coverage_file.exists():
        print("[warn] No coverage data found", file=sys.stderr)
        return False

    with open(coverage_file) as f:
        coverage = json.load(f)

    failed_files = []
    passed_count = 0

    # Pre-compute normalized coverage keys for efficient matching.
    # Coverage.json keys may be relative (src\pokepoke\foo.py) or absolute.
    cov_lookup: dict[str, dict[str, object]] = {}
    for cov_key, data in coverage["files"].items():
        cov_path = Path(cov_key)
        if not cov_path.is_absolute():
            cov_path = repo_root / cov_path
        normalized = _normalize_path(cov_path)
        cov_lookup[normalized] = data

    for file_path in files:
        # file_path from git diff uses forward slashes: src/pokepoke/foo.py
        full_path = repo_root / file_path
        normalized_file = _normalize_path(full_path)

        file_data = cov_lookup.get(normalized_file)

        if not file_data:
            print(f"  [warn] {file_path} - No coverage data (needs tests)")
            failed_files.append(file_path)
            continue

        line_coverage = file_data["summary"]["percent_covered"]

        if line_coverage < min_coverage:
            print(
                f"  [FAIL] {file_path} - Coverage: "
                f"{line_coverage:.1f}% (minimum: {min_coverage}%)"
            )
            failed_files.append(file_path)
        else:
            passed_count += 1

    if failed_files:
        print(
            f"\n[FAIL] {len(failed_files)} file(s) below "
            f"{min_coverage}% coverage"
        )
        print("\nAdd tests to increase coverage for these files.")
        return False

    print(f"[PASS] Coverage {min_coverage}%+ ({passed_count} files)")
    return True


def main() -> int:
    """Main execution."""
    # Explicitly resolve repo root — works in both repos and worktrees.
    repo_root = get_repo_root()
    os.chdir(repo_root)

    staged_files = get_staged_python_files()

    if not staged_files:
        print("No Python source files staged for commit")
        return 0

    print(f"Checking coverage for {len(staged_files)} staged file(s)...")

    # Run tests from repo root
    if not run_tests_with_coverage(repo_root):
        return 1

    # Check coverage with explicit repo root
    if not check_coverage(staged_files, repo_root):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
