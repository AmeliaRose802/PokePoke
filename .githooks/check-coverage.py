#!/usr/bin/env python3
"""Pre-commit coverage checker for Python projects.

Works correctly in both regular repositories and git worktrees.
Explicitly resolves the repo/worktree root to avoid CWD dependency issues.
"""

import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Maximum time (seconds) for the pytest subprocess before it is killed.
# Individual tests time out at 30s via --timeout; this caps the entire suite.
_PYTEST_TIMEOUT_SECONDS = 600


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
            encoding="utf-8",
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        # Fallback: script is in .githooks/, so parent is repo root
        return Path(__file__).resolve().parent.parent


def _get_staged_files() -> list[str]:
    """Get all staged file paths (added/copied/modified) from git index."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
        )
        return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
    except subprocess.CalledProcessError as e:
        print(f"[error] Failed to get staged files: {e}", file=sys.stderr)
        return []


def get_staged_python_files() -> list[str]:
    """Get staged Python source files under src/pokepoke/ (excludes tests)."""
    return [
        f
        for f in _get_staged_files()
        if f.endswith(".py")
        and f.startswith("src/pokepoke/")
        and "/tests/" not in f
        and not os.path.basename(f).startswith("test_")
        and "__pycache__" not in f
    ]


def _collect_conftest_tests(
    all_staged: list[str], repo_root: Path, test_files: list[str]
) -> None:
    """Add tests scoped to changed conftest.py directories."""
    for f in all_staged:
        basename = os.path.basename(f)
        if basename == "conftest.py" and f.startswith("tests/"):
            conftest_dir = os.path.dirname(f) or "tests"
            abs_dir = repo_root / conftest_dir
            for match in abs_dir.rglob("test_*.py"):
                rel = str(match.relative_to(repo_root)).replace("\\", "/")
                if rel not in test_files:
                    test_files.append(rel)
            print(f"[scope] {f} changed — running tests in {conftest_dir}/")


def _collect_staged_test_files(
    all_staged: list[str], test_files: list[str]
) -> None:
    """Add directly-staged test files to the list."""
    for f in all_staged:
        if f.startswith("tests/") and f.endswith(".py") and "test_" in f and f not in test_files:
            test_files.append(f)


def _map_source_to_tests(
    staged_source: list[str], repo_root: Path, test_files: list[str]
) -> None:
    """Map staged source files to their corresponding test files."""
    tests_dir = repo_root / "tests"

    # Manual overrides for modules whose tests don't follow naming convention
    test_file_overrides: dict[str, list[str]] = {
        "worktree_cleanup": ["tests/test_worktrees.py"],
        "sdk_helpers": [
            "tests/models/test_copilot_sdk.py",
            "tests/models/test_copilot_sdk_integration.py",
        ],
        "sdk_beads_tracker": ["tests/utils/test_sdk_event_handler.py"],
    }

    for src_file in staged_source:
        module_name = Path(src_file).stem

        if module_name in test_file_overrides:
            for override_file in test_file_overrides[module_name]:
                if (repo_root / override_file).exists() and override_file not in test_files:
                    test_files.append(override_file)

        direct = f"tests/test_{module_name}.py"
        if (repo_root / direct).exists() and direct not in test_files:
            test_files.append(direct)

        for match in tests_dir.rglob(f"test_{module_name}.py"):
            rel = str(match.relative_to(repo_root)).replace("\\", "/")
            if rel not in test_files:
                test_files.append(rel)

        for match in tests_dir.rglob(f"test_{module_name}_*.py"):
            rel = str(match.relative_to(repo_root)).replace("\\", "/")
            if rel not in test_files:
                test_files.append(rel)


def _find_test_files_for_staged(
    staged_source: list[str], repo_root: Path,
) -> tuple[list[str], bool]:
    """Map staged source files to relevant test files. Returns (test_files, run_full_suite)."""
    all_staged = _get_staged_files()
    test_files: list[str] = []
    _collect_conftest_tests(all_staged, repo_root, test_files)
    _collect_staged_test_files(all_staged, test_files)
    _map_source_to_tests(staged_source, repo_root, test_files)
    if not test_files:
        print("[scope] No matching test files found — falling back to full test suite")
        return [], True
    return sorted(test_files), False


# Matches pytest progress lines:
#   xdist format:  "....s.F.. [ 37%]"
#   plain format:  "....s.F.."   (no percentage indicator)
_PROGRESS_RE = re.compile(r'^[.sFExXpP]+(\s+\[\s*\d+%\])?\s*$')


def _filter_pytest_output(output: str) -> str:
    """Remove progress-dot lines; keep failures, warnings, and the summary."""
    lines = [ln for ln in output.splitlines() if not _PROGRESS_RE.match(ln.lstrip())]
    result: list[str] = []
    for line in lines:
        if not line.strip() and result and not result[-1].strip():
            continue
        result.append(line)
    while result and not result[0].strip():
        result.pop(0)
    while result and not result[-1].strip():
        result.pop()
    return "\n".join(result)


def _filter_pytest_stderr(stderr: str) -> str:
    """Strip xdist temp-dir cleanup warnings from captured pytest stderr."""
    result: list[str] = []
    skip_block = False
    for line in stderr.splitlines():
        stripped = line.strip()
        if "PytestWarning" in stripped and "(rm_rf)" in stripped:
            skip_block = True
            if result and result[-1].strip() == "warnings.warn(":
                result.pop()
            continue
        if skip_block:
            if stripped.startswith(("<class 'OSError'>", "warnings.warn(")):
                if stripped == "warnings.warn(":
                    skip_block = False
                continue
            skip_block = False
        result.append(line)
    return "\n".join(result)


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its descendants (best-effort)."""
    if sys.platform == "win32":
        with contextlib.suppress(subprocess.SubprocessError, OSError):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=10)
    else:
        import signal
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)


def run_tests_with_coverage(
    repo_root: Path, test_files: list[str] | None = None
) -> bool:
    """Run pytest with coverage from the repo root."""
    if test_files:
        print(f"[test] Running {len(test_files)} scoped test file(s)...")
        for tf in test_files:
            print(f"       {tf}")
    else:
        print("[test] Running full test suite...")

    # Limit parallel workers to avoid memory exhaustion on pre-commit.
    import multiprocessing
    import platform
    if platform.system() == "Windows":
        max_workers = min(2, max(1, multiprocessing.cpu_count() // 2))
    else:
        max_workers = min(4, max(1, multiprocessing.cpu_count() // 2))

    basetemp = repo_root / ".pytest_tmp"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-n",
        str(max_workers),
        f"--basetemp={basetemp}",
        # Suppress xdist worker temp-dir cleanup warnings on Windows.
        # pyproject.toml filterwarnings applies inside each worker subprocess
        # but rm_rf cleanup can fire after that filter is torn down.
        "-W", "ignore::pytest.PytestWarning",
        "--cov=src/pokepoke",
        "--cov-report=json",
        "-q",
        "--no-header",
        "--tb=short",
        "--timeout=30",
    ]
    if test_files:
        cmd.extend(test_files)

    # Use Popen for process-tree control on timeout.
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=str(repo_root), encoding="utf-8", errors="backslashreplace",
            start_new_session=(sys.platform != "win32"),
        )
    except Exception as e:
        print(f"[error] Test execution failed: {e}", file=sys.stderr)
        return False

    try:
        stdout, stderr = proc.communicate(timeout=_PYTEST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc.pid)
        with contextlib.suppress(OSError):
            proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired, OSError):
            proc.communicate(timeout=5)
        timeout_min = _PYTEST_TIMEOUT_SECONDS // 60
        print(
            f"\n⏰ Pre-commit timed out after {timeout_min} minutes.\n"
            "Tests are likely hanging. Check for:\n"
            "  - Tests using real subprocess/git calls without mocking\n"
            "  - Tests waiting for stdin input\n"
            "  - Select-Object -First/-Last piping\n"
            "\nRun pytest with --timeout=30 to find the hanging test.",
            file=sys.stderr,
        )
        return False
    except Exception as e:
        with contextlib.suppress(OSError):
            proc.kill()
        with contextlib.suppress(OSError):
            proc.wait()
        print(f"[error] Test execution failed: {e}", file=sys.stderr)
        return False

    # Print filtered output (no progress dots)
    filtered = _filter_pytest_output(stdout)
    if filtered:
        print(filtered)

    exit_code = proc.wait()
    if exit_code != 0:
        if stderr.strip():
            print(_filter_pytest_stderr(stderr).strip(), file=sys.stderr)
        print("[error] Tests failed", file=sys.stderr)
        return False

    return True


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

    # Determine which test files to run (scoped or full suite)
    test_files, run_full = _find_test_files_for_staged(staged_files, repo_root)
    scoped = test_files if not run_full else None

    # Run tests from repo root
    if not run_tests_with_coverage(repo_root, test_files=scoped):
        return 1

    # Check coverage with explicit repo root
    if not check_coverage(staged_files, repo_root):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
