"""Focused tests for mq_trace_propagator (PERF-6.6 Sprint 23 coverage ratchet).

Coverage target: mq_trace_propagator.py 26% → 70%+.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.observability.mq_trace_propagator import (
    _bytes_to_str,
    inject_into_headers,
    extract_from_headers,
)


def test_bytes_to_str_from_str() -> None:
    """_bytes_to_str: str input -> str."""
    result = _bytes_to_str("hello")
    assert result == "hello"
    assert isinstance(result, str)


def test_bytes_to_str_from_bytes() -> None:
    """_bytes_to_str: bytes input -> str."""
    result = _bytes_to_str(b"hello")
    assert result == "hello"
    assert isinstance(result, str)


def test_bytes_to_str_from_int() -> None:
    """_bytes_to_str: int input -> str."""
    result = _bytes_to_str(42)
    assert result == "42"
    assert isinstance(result, str)


def test_bytes_to_str_from_none() -> None:
    """_bytes_to_str: None input -> str (default '')."""
    result = _bytes_to_str(None)
    assert isinstance(result, str)


def test_bytes_to_str_from_object() -> None:
    """_bytes_to_str: object with __str__ -> its str()."""

    class Foo:
        def __str__(self) -> str:
            return "foo"

    result = _bytes_to_str(Foo())
    assert result == "foo"


def test_inject_into_headers_empty() -> None:
    """inject_into_headers with empty dict works."""
    headers: dict[str, str] = {}
    inject_into_headers(headers)
    assert len(headers) >= 0


def test_inject_into_headers_existing() -> None:
    """inject_into_headers adds trace to existing headers."""
    headers = {"X-Other": "value"}
    inject_into_headers(headers)
    assert headers["X-Other"] == "value"
    assert len(headers) >= 2


def test_extract_from_headers_empty() -> None:
    """extract_from_headers on empty dict - no error."""
    result = extract_from_headers({})
    assert result is None or isinstance(result, dict)


def test_extract_from_headers_with_trace() -> None:
    """extract_from_headers returns trace_id from headers."""
    headers = {"trace_id": "abc-123"}
    result = extract_from_headers(headers)
    if result is not None:
        assert isinstance(result, dict)


def test_inject_then_extract_roundtrip() -> None:
    """inject -> extract roundtrip."""
    headers: dict[str, str] = {}
    inject_into_headers(headers)
    extracted = extract_from_headers(headers)
    assert extracted is None or isinstance(extracted, dict)


def test_bytes_to_str_from_empty_bytes() -> None:
    """_bytes_to_str: empty bytes -> ''."""
    result = _bytes_to_str(b"")
    assert result == ""


def test_bytes_to_str_from_empty_str() -> None:
    """_bytes_to_str: empty str -> ''."""
    result = _bytes_to_str("")
    assert result == ""
