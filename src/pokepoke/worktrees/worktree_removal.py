"""Low-level directory removal utilities for worktree cleanup.

Provides safe, Windows-aware directory removal with symlink/junction
protection, path boundary validation, and lock file handling.
"""

import contextlib
import logging
import os
import stat
from pathlib import Path

from pokepoke.utils.constants import WORKTREE_DIR

logger = logging.getLogger(__name__)

# Retry settings for worktree removal on Windows
_CLEANUP_MAX_RETRIES = 5
_CLEANUP_RETRY_DELAY_SECONDS = 3.0
_CLEANUP_MAX_DELAY_SECONDS = 30.0


class SymlinkFoundError(OSError):
    """Raised when a symlink or junction is found during safe directory removal."""


class PathBoundaryError(OSError):
    """Raised when a path escapes the expected worktree boundary."""


def _validate_within_worktrees_dir(dir_path: Path, *, repo_root: Path | None = None) -> None:
    """Validate that *dir_path* resolves inside the expected worktrees directory.

    Raises :class:`PathBoundaryError` if the resolved path is not inside the
    expected worktrees directory.
    """
    try:
        resolved = dir_path.resolve(strict=False)
    except (OSError, ValueError) as exc:
        raise PathBoundaryError(
            f"Cannot resolve path for boundary validation: {dir_path} ({exc})"
        ) from exc

    try:
        if repo_root is None:
            from pokepoke.config import _find_repo_root
            repo_root = _find_repo_root()
        expected_worktrees_dir = (repo_root / WORKTREE_DIR).resolve(strict=False)
    except Exception as exc:
        raise PathBoundaryError(
            f"Cannot determine repository root for boundary validation: {exc}"
        ) from exc

    try:
        resolved.relative_to(expected_worktrees_dir)
    except ValueError:
        raise PathBoundaryError(
            f"Path {dir_path} (resolved: {resolved}) is not inside the expected "
            f"worktrees directory ({expected_worktrees_dir}) — refusing to delete"
        ) from None


_KNOWN_LOCK_FILES = frozenset({
    "index.lock",
    "HEAD.lock",
    "config.lock",
    "refs.lock",
    "shallow.lock",
    "packed-refs.lock",
})


def _release_known_lock_files(dir_path: Path) -> list[Path]:
    """Remove known git lock files that may prevent deletion.

    Returns the list of lock files that were successfully removed.
    """
    removed: list[Path] = []
    git_dir = dir_path / ".git"
    if not git_dir.is_dir():
        return removed

    for lock_name in _KNOWN_LOCK_FILES:
        lock_file = git_dir / lock_name
        try:
            if lock_file.exists():
                with contextlib.suppress(OSError):
                    os.chmod(str(lock_file), stat.S_IWRITE | stat.S_IREAD)
                os.remove(str(lock_file))
                removed.append(lock_file)
                logger.debug(f"   🔓 Removed lock file: {lock_file}")
        except OSError:
            logger.debug(f"   🔒 Could not remove lock file: {lock_file}")
    return removed


def _safe_rmtree(dir_path: Path) -> None:
    """Remove a directory tree without following symlinks or junctions.

    Before deletion, attempts to release known git lock files.  On partial
    failure, logs the specific files that could not be deleted.

    Raises :class:`SymlinkFoundError` if *dir_path* itself is a symlink/junction.
    """
    if dir_path.is_symlink() or _is_junction(dir_path):
        raise SymlinkFoundError(
            f"Refusing to remove {dir_path}: it is a symlink or junction"
        )

    _release_known_lock_files(dir_path)

    failed_files: list[tuple[Path, str]] = []

    def _remove_tree(path: Path) -> None:
        try:
            entries = list(path.iterdir())
        except (OSError, PermissionError):
            try:
                os.chmod(str(path), stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
                entries = list(path.iterdir())
            except (OSError, PermissionError):
                raise

        for entry in entries:
            if entry.is_symlink() or _is_junction(entry):
                try:
                    os.remove(str(entry))
                except OSError as e:
                    failed_files.append((entry, str(e)))
                    raise
            elif entry.is_dir():
                _remove_tree(entry)
            else:
                with contextlib.suppress(OSError):
                    os.chmod(str(entry), stat.S_IWRITE | stat.S_IREAD)
                try:
                    os.remove(str(entry))
                except OSError as e:
                    failed_files.append((entry, str(e)))
                    raise

        with contextlib.suppress(OSError):
            os.chmod(str(path), stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        try:
            os.rmdir(str(path))
        except OSError as e:
            failed_files.append((path, str(e)))
            raise

    try:
        _remove_tree(dir_path)
    except OSError:
        if failed_files:
            logger.warning(
                f"   ⚠️ Partial deletion of {dir_path} — "
                f"{len(failed_files)} item(s) could not be removed:"
            )
            for fpath, reason in failed_files[:10]:
                logger.warning(f"      • {fpath}: {reason}")
            if len(failed_files) > 10:
                logger.warning(f"      ... and {len(failed_files) - 10} more")
        raise


def _is_junction(path: Path) -> bool:
    """Return True if *path* is an NTFS junction point (Windows-only concept)."""
    try:
        return bool(path.is_junction())
    except AttributeError:
        try:
            import ctypes.wintypes  # only available on Windows
            FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == -1:
                return False
            return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT) and not path.is_symlink()
        except (AttributeError, ImportError, OSError):
            return False


def _is_windows_lock_error(error_text: str) -> bool:
    """Detect Windows file locking related errors."""
    if not error_text:
        return False

    error_lower = error_text.lower()
    windows_lock_indicators = [
        "being used by another process",
        "locked a portion of the file",
        "sharing violation",
        "[winerror 32]",
        "[winerror 33]",
    ]

    return any(indicator in error_lower for indicator in windows_lock_indicators)
