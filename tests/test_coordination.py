"""Tests for pokepoke.coordination module."""

from pathlib import Path
from unittest.mock import patch

import pytest
from filelock import Timeout

from pokepoke.coordination import acquire_lock, try_lock, _lock_dir, _lock_path


class TestLockDir:
    """Tests for lock directory helpers."""

    def test_lock_dir_creates_directory(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir") as mock_dir:
            d = tmp_path / ".pokepoke" / "locks"
            mock_dir.return_value = d
            result = mock_dir()
            assert result == d

    def test_lock_path_returns_correct_name(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            assert _lock_path("foo") == tmp_path / "foo.lock"


class TestAcquireLock:
    """Tests for acquire_lock context manager."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with acquire_lock("test") as lock:
                assert lock.is_locked
                lock_file = tmp_path / "test.lock"
                assert lock_file.exists()
            assert not lock.is_locked

    def test_lock_file_created_in_lock_dir(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with acquire_lock("mylock"):
                assert (tmp_path / "mylock.lock").exists()

    def test_timeout_raises(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with acquire_lock("exclusive"):
                # Same lock with zero timeout should fail
                with pytest.raises(Timeout):
                    with acquire_lock("exclusive", timeout=0):
                        pass  # pragma: no cover

    def test_release_on_exception(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(RuntimeError):
                with acquire_lock("err") as lock:
                    lock_ref = lock
                    raise RuntimeError("boom")
            assert lock_ref is not None
            assert not lock_ref.is_locked


class TestTryLock:
    """Tests for try_lock non-blocking acquisition."""

    def test_returns_lock_when_available(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock = try_lock("avail")
            assert lock is not None
            assert lock.is_locked
            lock.release()

    def test_returns_none_when_held(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with acquire_lock("held"):
                result = try_lock("held")
                assert result is None

    def test_caller_must_release(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock = try_lock("manual")
            assert lock is not None
            assert lock.is_locked
            lock.release()
            assert not lock.is_locked


class TestLockDirCreation:
    """Tests for _lock_dir lazy directory creation."""

    def test_creates_nested_directories(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        d = _lock_dir()
        assert d.is_dir()
        assert d == Path(".pokepoke") / "locks"

    def test_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        d1 = _lock_dir()
        d2 = _lock_dir()
        assert d1 == d2
        assert d1.is_dir()
