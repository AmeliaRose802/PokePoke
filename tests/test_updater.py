"""Tests for pokepoke.updater — auto-update checker."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.updater import (
    RELEASES_PAGE_URL,
    _parse_version,
    check_for_updates,
    get_current_version,
)


# ---------------------------------------------------------------------------
# get_current_version
# ---------------------------------------------------------------------------


def test_get_current_version_returns_string() -> None:
    version = get_current_version()
    assert isinstance(version, str)
    assert len(version) > 0


def test_get_current_version_fallback_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata

    def _raise(_name: str) -> str:  # type: ignore[override]
        raise importlib.metadata.PackageNotFoundError("pokepoke")

    monkeypatch.setattr(importlib.metadata, "version", _raise)
    assert get_current_version() == "0.0.0"


# ---------------------------------------------------------------------------
# _parse_version
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0.0", (1, 0, 0)),
        ("v2.3.4", (2, 3, 4)),
        ("0.1.0", (0, 1, 0)),
        ("10.20.30", (10, 20, 30)),
        ("1.0", (1, 0)),
        ("", (0,)),        # empty string → single zero part
        ("bad", (0,)),     # non-numeric → 0
        ("1.bad.3", (1, 0, 3)),
    ],
)
def test_parse_version(version: str, expected: tuple[int, ...]) -> None:
    assert _parse_version(version) == expected


# ---------------------------------------------------------------------------
# check_for_updates — helpers
# ---------------------------------------------------------------------------


def _make_response(body: dict[str, object], status: int = 200) -> MagicMock:
    """Return a mock context-manager response object."""
    raw = json.dumps(body).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# check_for_updates — success paths
# ---------------------------------------------------------------------------


def test_check_for_updates_up_to_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.2.3")
    payload = {"tag_name": "v1.2.3", "assets": []}
    with patch("pokepoke.updater.urlopen", return_value=_make_response(payload)):
        result = check_for_updates()

    assert result["current_version"] == "1.2.3"
    assert result["latest_version"] == "1.2.3"
    assert result["update_available"] is False
    assert result["error"] is None
    assert result["download_url"] == RELEASES_PAGE_URL


def test_check_for_updates_newer_version_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.0.0")
    payload = {"tag_name": "v1.2.0", "assets": []}
    with patch("pokepoke.updater.urlopen", return_value=_make_response(payload)):
        result = check_for_updates()

    assert result["update_available"] is True
    assert result["latest_version"] == "1.2.0"
    assert result["error"] is None


def test_check_for_updates_uses_installer_asset_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.0.0")
    installer_url = "https://example.com/PokePoke-Setup-1.2.0.exe"
    payload = {
        "tag_name": "v1.2.0",
        "assets": [
            {"name": "PokePoke-Setup-1.2.0.exe", "browser_download_url": installer_url},
        ],
    }
    with patch("pokepoke.updater.urlopen", return_value=_make_response(payload)):
        result = check_for_updates()

    assert result["download_url"] == installer_url


def test_check_for_updates_uses_msi_asset_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.0.0")
    msi_url = "https://example.com/PokePoke-1.2.0.msi"
    payload = {
        "tag_name": "v1.2.0",
        "assets": [
            {"name": "PokePoke-1.2.0.msi", "browser_download_url": msi_url},
        ],
    }
    with patch("pokepoke.updater.urlopen", return_value=_make_response(payload)):
        result = check_for_updates()

    assert result["download_url"] == msi_url


def test_check_for_updates_ignores_non_installer_assets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.0.0")
    payload = {
        "tag_name": "v1.2.0",
        "assets": [
            {"name": "source.tar.gz", "browser_download_url": "https://example.com/source.tar.gz"},
        ],
    }
    with patch("pokepoke.updater.urlopen", return_value=_make_response(payload)):
        result = check_for_updates()

    assert result["download_url"] == RELEASES_PAGE_URL


def test_check_for_updates_missing_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.0.0")
    payload: dict[str, object] = {"assets": []}
    with patch("pokepoke.updater.urlopen", return_value=_make_response(payload)):
        result = check_for_updates()

    assert result["error"] == "No release tag found"
    assert result["latest_version"] is None
    assert result["update_available"] is False


# ---------------------------------------------------------------------------
# check_for_updates — error paths
# ---------------------------------------------------------------------------


def test_check_for_updates_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.error import URLError

    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.0.0")
    with patch("pokepoke.updater.urlopen", side_effect=URLError("connection refused")):
        result = check_for_updates()

    assert result["error"] is not None
    assert "Network error" in result["error"]
    assert result["update_available"] is False


def test_check_for_updates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.0.0")
    with patch("pokepoke.updater.urlopen", side_effect=TimeoutError()):
        result = check_for_updates()

    assert result["error"] == "Request timed out"
    assert result["update_available"] is False


def test_check_for_updates_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "1.0.0")
    with patch("pokepoke.updater.urlopen", side_effect=ValueError("bad json")):
        result = check_for_updates()

    assert result["error"] is not None
    assert result["update_available"] is False


def test_check_for_updates_returns_current_version_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.updater.get_current_version", lambda: "2.0.0")
    from urllib.error import URLError

    with patch("pokepoke.updater.urlopen", side_effect=URLError("err")):
        result = check_for_updates()

    assert result["current_version"] == "2.0.0"
    assert result["download_url"] == RELEASES_PAGE_URL
