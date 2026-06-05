# ruff: noqa: S101
"""Smoke tests for IMAP monitor (entrypoints/email/imap_monitor.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.entrypoints.email.imap_monitor import ImapConfig, ImapMonitor

# ── ImapConfig dataclass ───────────────────────────────────────────


def test_imap_config_defaults() -> None:
    cfg = ImapConfig(host="imap.example.com")
    assert cfg.host == "imap.example.com"
    assert cfg.port == 993
    assert cfg.username == ""
    assert cfg.password == ""
    assert cfg.folder == "INBOX"
    assert cfg.poll_interval == 60.0
    assert cfg.use_ssl is True
    assert cfg.starttls is True
    assert cfg.verify_cert is True
    assert cfg.idle_mode is False
    assert cfg.idle_timeout == 29 * 60
    assert cfg.subject_pattern is None
    assert cfg.from_filter is None
    assert cfg.since_uid == 0


def test_imap_config_custom_values() -> None:
    cfg = ImapConfig(
        host="mail",
        port=143,
        username="u",
        password="p",
        folder="Sent",
        poll_interval=10.0,
        use_ssl=False,
        starttls=False,
        idle_mode=True,
        subject_pattern="re:foo",
    )
    assert cfg.port == 143
    assert cfg.folder == "Sent"
    assert cfg.poll_interval == 10.0
    assert cfg.use_ssl is False
    assert cfg.idle_mode is True
    assert cfg.subject_pattern == "re:foo"


# ── ImapMonitor: filter pattern compilation ─────────────────────────


def test_compile_subject_pattern_none() -> None:
    assert ImapMonitor._compile_subject_pattern(None) is None
    assert ImapMonitor._compile_subject_pattern("") is None


def test_compile_subject_pattern_literal() -> None:
    pat = ImapMonitor._compile_subject_pattern("hello")
    assert pat is not None
    assert pat.search("Hello world") is not None
    assert pat.search("Bye") is None


def test_compile_subject_pattern_re_prefix() -> None:
    pat = ImapMonitor._compile_subject_pattern(r"re:foo\d+")
    assert pat is not None
    assert pat.search("foo42") is not None
    assert pat.search("foo") is None


# ── ImapMonitor: filter matching ────────────────────────────────────


def test_matches_filters_no_filters() -> None:
    cfg = ImapConfig(host="x", use_ssl=False, starttls=False)
    mon = ImapMonitor(cfg)
    assert mon._matches_filters({"subject": "anything", "from": "a@b.c"}) is True


def test_matches_filters_subject_literal() -> None:
    cfg = ImapConfig(host="x", use_ssl=False, starttls=False, subject_pattern="alert")
    mon = ImapMonitor(cfg)
    assert mon._matches_filters({"subject": "ALERT: problem", "from": "a@b.c"}) is True
    assert mon._matches_filters({"subject": "hello", "from": "a@b.c"}) is False


def test_matches_filters_from_substring() -> None:
    cfg = ImapConfig(host="x", use_ssl=False, starttls=False, from_filter="example.com")
    mon = ImapMonitor(cfg)
    assert mon._matches_filters({"subject": "x", "from": "user@EXAMPLE.com"}) is True
    assert mon._matches_filters({"subject": "x", "from": "user@other.com"}) is False


# ── ImapMonitor: SSL context ────────────────────────────────────────


def test_ssl_context_returns_none_when_no_ssl() -> None:
    cfg = ImapConfig(host="x", use_ssl=False, starttls=False)
    mon = ImapMonitor(cfg)
    assert mon._ssl_context() is None


def test_ssl_context_returns_context_when_ssl() -> None:
    cfg = ImapConfig(host="x", use_ssl=True, starttls=False)
    mon = ImapMonitor(cfg)
    ctx = mon._ssl_context()
    assert ctx is not None


def test_ssl_context_logs_warning_when_no_verify() -> None:
    cfg = ImapConfig(host="x", use_ssl=True, starttls=False, verify_cert=False)
    mon = ImapMonitor(cfg)
    with patch("src.backend.entrypoints.email.imap_monitor.logger") as mock_log:
        ctx = mon._ssl_context()
    assert ctx is not None
    mock_log.warning.assert_called()


# ── ImapMonitor: resolve password ───────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_password_from_config() -> None:
    cfg = ImapConfig(host="x", use_ssl=False, starttls=False, password="plain")
    mon = ImapMonitor(cfg)
    pw = await mon._resolve_password()
    assert pw == "plain"


@pytest.mark.asyncio
async def test_resolve_password_vault_failure_falls_back() -> None:
    cfg = ImapConfig(
        host="x",
        use_ssl=False,
        starttls=False,
        password="fallback",
        password_vault_ref="vault:bad#key",
    )
    mon = ImapMonitor(cfg)
    with patch(
        "src.backend.core.di.providers.get_vault_refresher_provider",
        side_effect=RuntimeError("vault down"),
    ):
        pw = await mon._resolve_password()
    assert pw == "fallback"


# ── ImapMonitor: lifecycle state ────────────────────────────────────


def test_initial_state() -> None:
    cfg = ImapConfig(host="x", use_ssl=False, starttls=False)
    mon = ImapMonitor(cfg)
    assert mon._task is None
    assert mon._running is False
    assert mon._last_uid == 0


def test_initial_state_with_since_uid() -> None:
    cfg = ImapConfig(host="x", use_ssl=False, starttls=False, since_uid=42)
    mon = ImapMonitor(cfg)
    assert mon._last_uid == 42


# ── Mark unrunnable / live network paths as xfail ───────────────────


@pytest.mark.xfail(reason="Requires live IMAP server", strict=False)
@pytest.mark.asyncio
async def test_connect_live_server() -> None:
    cfg = ImapConfig(host="imap.example.com", username="x", password="y")
    mon = ImapMonitor(cfg)
    _ = await mon._connect()


# Helper: just to silence unused import warning
_ = MagicMock
