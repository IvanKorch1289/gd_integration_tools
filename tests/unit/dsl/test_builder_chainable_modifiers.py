"""Тесты chainable per-step modifiers RouteBuilder (Sprint 2 §12.5).

Проверяют:
* `with_timeout` — переопределяет ``_timeout`` последнего step.
* `with_retries` — переопределяет ``_max_attempts``/``_backoff``.
* `with_headers` — merge / replace для ``_headers``.
* `with_auth` — token / api_key / mtls_cert ветки.
* Поведение при пустом pipeline (ValueError).
* Поведение при processor без поддержки атрибута (ValueError).
"""
# ruff: noqa: S101, S105, S106

from __future__ import annotations

import pytest

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.components import HttpCallProcessor
from src.backend.dsl.engine.processors.control_flow import RetryProcessor


class _NoopProcessor(BaseProcessor):
    """No-op процессор для wrap'а в RetryProcessor (минимальная заглушка)."""

    async def process(self, exchange, context):  # type: ignore[no-untyped-def]
        return None


def _builder() -> RouteBuilder:
    return RouteBuilder.from_("test.route", source="internal:test")


# ── with_timeout ──


def test_with_timeout_overrides_http_call_timeout() -> None:
    b = _builder().http_call("https://api.example.com", timeout=30.0).with_timeout(5)
    last = b._processors[-1]
    assert isinstance(last, HttpCallProcessor)
    assert last._timeout == 5.0


def test_with_timeout_raises_on_empty_pipeline() -> None:
    with pytest.raises(ValueError, match="до первого step"):
        _builder().with_timeout(10)


def test_with_timeout_raises_on_unsupported_processor() -> None:
    b = _builder().set_property("foo", "bar")
    with pytest.raises(ValueError, match="не поддерживает атрибут timeout"):
        b.with_timeout(5)


# ── with_retries ──


def test_with_retries_overrides_retry_processor() -> None:
    inner = _NoopProcessor(name="inner")
    pipeline = (
        _builder()
        .retry([inner], max_attempts=3, backoff="exponential")
        .with_retries(7, backoff="fixed")
    )
    last = pipeline._processors[-1]
    assert isinstance(last, RetryProcessor)
    assert last._max_attempts == 7
    assert last._backoff == "fixed"


def test_with_retries_without_backoff_keeps_existing() -> None:
    inner = _NoopProcessor(name="inner")
    pipeline = (
        _builder()
        .retry([inner], max_attempts=3, backoff="exponential")
        .with_retries(5)
    )
    last = pipeline._processors[-1]
    assert last._max_attempts == 5
    assert last._backoff == "exponential"


def test_with_retries_raises_on_empty_pipeline() -> None:
    with pytest.raises(ValueError, match="до первого step"):
        _builder().with_retries(3)


# ── with_headers ──


def test_with_headers_merge_combines_with_existing() -> None:
    b = (
        _builder()
        .http_call(
            "https://api.example.com",
            headers={"X-Trace": "init", "X-Original": "keep"},
        )
        .with_headers({"X-Trace": "override", "X-New": "added"}, mode="merge")
    )
    last = b._processors[-1]
    assert last._headers == {
        "X-Original": "keep",
        "X-Trace": "override",
        "X-New": "added",
    }


def test_with_headers_replace_drops_previous() -> None:
    b = (
        _builder()
        .http_call(
            "https://api.example.com",
            headers={"X-Trace": "init", "X-Original": "keep"},
        )
        .with_headers({"X-New": "only"}, mode="replace")
    )
    last = b._processors[-1]
    assert last._headers == {"X-New": "only"}


def test_with_headers_invalid_mode_raises() -> None:
    b = _builder().http_call("https://api.example.com")
    with pytest.raises(ValueError, match="mode должен быть"):
        b.with_headers({"X-Foo": "bar"}, mode="invalid")


# ── with_auth ──


def test_with_auth_token_sets_auth_token() -> None:
    b = (
        _builder()
        .http_call("https://api.example.com")
        .with_auth(token="bearer-xyz")
    )
    last = b._processors[-1]
    assert last._auth_token == "bearer-xyz"


def test_with_auth_api_key_routed_through_headers() -> None:
    b = (
        _builder()
        .http_call("https://api.example.com", headers={"X-Trace": "t"})
        .with_auth(api_key="k-123")
    )
    last = b._processors[-1]
    assert last._headers == {"X-Trace": "t", "X-API-Key": "k-123"}


def test_with_auth_requires_exactly_one_arg() -> None:
    b = _builder().http_call("https://api.example.com")
    with pytest.raises(ValueError, match="ровно один"):
        b.with_auth()
    with pytest.raises(ValueError, match="ровно один"):
        b.with_auth(token="x", api_key="y")


def test_with_auth_token_unsupported_processor_raises() -> None:
    b = _builder().set_property("foo", "bar")
    with pytest.raises(ValueError, match="не поддерживает атрибут auth_token"):
        b.with_auth(token="bearer-xyz")


# ── Composition ──


def test_modifiers_chain_in_sequence() -> None:
    b = (
        _builder()
        .http_call("https://api.example.com", headers={"X-Initial": "1"})
        .with_timeout(15)
        .with_headers({"X-Added": "2"}, mode="merge")
        .with_auth(token="tok")
    )
    last = b._processors[-1]
    assert last._timeout == 15.0
    assert last._headers == {"X-Initial": "1", "X-Added": "2"}
    assert last._auth_token == "tok"
