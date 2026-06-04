"""Unit tests for HTTP utility helpers."""

# ruff: noqa: S101

from __future__ import annotations

from src.backend.core.net.http_utils import ensure_url_protocol, generate_link_page


def test_ensure_url_protocol_adds_http() -> None:
    assert ensure_url_protocol("example.com") == "http://example.com"


def test_ensure_url_protocol_keeps_http() -> None:
    assert ensure_url_protocol("http://example.com") == "http://example.com"


def test_ensure_url_protocol_keeps_https() -> None:
    assert ensure_url_protocol("https://example.com") == "https://example.com"


def test_generate_link_page() -> None:
    resp = generate_link_page("example.com", "Test")
    body = resp.body.decode() if isinstance(resp.body, bytes) else resp.body
    assert "http://example.com" in body
    assert "Test link:" in body
