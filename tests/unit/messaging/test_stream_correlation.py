# ruff: noqa: S101
"""Тесты propagation correlation_id в FastStream publish (S17 K3 W3 D12).

Покрывают helper ``_inject_correlation_id_headers``:

* пустой ContextVar → header не добавляется;
* установленный ContextVar → headers пополняется ``correlation_id``;
* caller-override (явный ключ ``correlation_id``) сохраняется.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure.clients.messaging.stream import (
    _inject_correlation_id_headers,
)
from src.backend.infrastructure.observability.correlation import (
    correlation_id_var,
    set_correlation_context,
)


@pytest.fixture(autouse=True)
def _reset_correlation_var() -> None:
    """Сбросить correlation_id_var перед каждым тестом."""
    correlation_id_var.set("")


def test_empty_context_var_returns_empty_headers() -> None:
    """Пустой ContextVar + None headers → пустой dict."""
    result = _inject_correlation_id_headers(None)
    assert result == {}


def test_empty_context_var_preserves_existing_headers() -> None:
    """Пустой ContextVar + caller headers → caller headers без correlation."""
    result = _inject_correlation_id_headers({"other": "value"})
    assert result == {"other": "value"}


def test_context_var_populates_correlation_id() -> None:
    """Установленный ContextVar → headers пополняется ``correlation_id``."""
    set_correlation_context(correlation_id="cid-stream-123")
    result = _inject_correlation_id_headers(None)
    assert result == {"correlation_id": "cid-stream-123"}


def test_context_var_merges_with_caller_headers() -> None:
    """ContextVar добавляется к caller headers, не перетирая их."""
    set_correlation_context(correlation_id="cid-merge")
    result = _inject_correlation_id_headers({"trace_id": "trc-1"})
    assert result == {"trace_id": "trc-1", "correlation_id": "cid-merge"}


def test_explicit_correlation_id_wins_over_context_var() -> None:
    """Явный ``correlation_id`` в headers caller'а сохраняется."""
    set_correlation_context(correlation_id="cid-from-context")
    result = _inject_correlation_id_headers({"correlation_id": "cid-explicit"})
    assert result == {"correlation_id": "cid-explicit"}
