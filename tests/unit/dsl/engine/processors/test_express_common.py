"""Tests for src.backend.dsl.engine.processors.express._common.

T3 coverage sprint: добавлены тесты для ``resolve_value``, ``_walk_path``,
``_host_from_url`` (все pure-Python, без external deps).

Test coverage:
- ``_walk_path``: dict navigation, missing key, non-dict node
- ``resolve_value``: 4 namespaces (body, header, properties, result) + fallback
- ``_host_from_url``: simple URL host extraction
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.express._common import (
    _host_from_url,
    _walk_path,
    resolve_value,
)


def _make_exchange(
    body: object | None = None,
    headers: dict[str, object] | None = None,
    properties: dict[str, object] | None = None,
) -> Exchange:
    """Build Exchange stub with the minimum interface used by resolve_value.

    Note: ``get_property`` is NOT in Exchange spec — we attach it as a real
    attribute via ``configure_mock`` to match resolve_value's contract.
    """
    msg = MagicMock()
    msg.body = body
    msg.headers = headers or {}
    ex = MagicMock(spec=Exchange)
    ex.in_message = msg
    ex.properties = properties or {}

    def _get_property(key: str) -> object | None:
        return properties.get(key) if properties else None

    ex.get_property = _get_property  # type: ignore[attr-defined]
    return ex


# ─────────── _walk_path ───────────


def test_walk_path_dict_simple() -> None:
    assert _walk_path({"a": 1}, ["a"]) == 1


def test_walk_path_dict_nested() -> None:
    node = {"outer": {"inner": {"leaf": "value"}}}
    assert _walk_path(node, ["outer", "inner", "leaf"]) == "value"


def test_walk_path_missing_key_returns_none() -> None:
    assert _walk_path({"a": 1}, ["b"]) is None


def test_walk_path_partial_nested_missing() -> None:
    """Если ключ отсутствует на любом уровне, возвращается None."""
    node = {"outer": {"inner": "x"}}
    assert _walk_path(node, ["outer", "missing", "leaf"]) is None


def test_walk_path_non_dict_node_returns_none() -> None:
    """Если узел стал не dict, walk прерывается и возвращает None."""
    assert _walk_path({"a": "string"}, ["a", "next"]) is None


def test_walk_path_empty_parts() -> None:
    assert _walk_path({"a": 1}, []) == {"a": 1}


# ─────────── resolve_value ───────────


def test_resolve_value_body() -> None:
    ex = _make_exchange(body={"user": {"id": 42}})
    assert resolve_value(ex, "body.user.id") == 42


def test_resolve_value_body_missing() -> None:
    ex = _make_exchange(body={"user": {"id": 42}})
    assert resolve_value(ex, "body.user.missing") is None


def test_resolve_value_header_simple() -> None:
    ex = _make_exchange(headers={"X-Trace-Id": "abc-123"})
    assert resolve_value(ex, "header.X-Trace-Id") == "abc-123"


def test_resolve_value_header_missing() -> None:
    ex = _make_exchange(headers={"X-Trace-Id": "abc-123"})
    assert resolve_value(ex, "header.X-Missing") is None


def test_resolve_value_properties_dict() -> None:
    ex = _make_exchange(properties={"user": {"name": "alice"}})
    assert resolve_value(ex, "properties.user.name") == "alice"


def test_resolve_value_properties_root() -> None:
    """``properties`` без дочерних путей возвращает весь dict."""
    props = {"a": 1, "b": 2}
    ex = _make_exchange(properties=props)
    assert resolve_value(ex, "properties") == props


def test_resolve_value_result_via_action_result() -> None:
    ex = _make_exchange(properties={"action_result": {"status": "ok"}})
    assert resolve_value(ex, "result.status") == "ok"


def test_resolve_value_result_root() -> None:
    ex = _make_exchange(properties={"action_result": {"status": "ok"}})
    assert resolve_value(ex, "result") == {"status": "ok"}


def test_resolve_value_fallback_to_properties() -> None:
    """Unknown namespace fallback'ит на properties (navigates dotted path)."""
    ex = _make_exchange(properties={"unknown": {"namespace": {"x": 1}}})
    assert resolve_value(ex, "unknown.namespace.x") == 1


def test_resolve_value_empty_body_returns_none() -> None:
    ex = _make_exchange(body=None)
    assert resolve_value(ex, "body.missing.path") is None


# ─────────── _host_from_url ───────────


def test_host_from_url_https() -> None:
    assert _host_from_url("https://api.example.com/v1/orders") == "api.example.com"


def test_host_from_url_http_with_port() -> None:
    assert _host_from_url("http://localhost:8080/health") == "localhost"


def test_host_from_url_no_scheme_returns_empty() -> None:
    """Без scheme (e.g., ``api.example.com/path``) urllib.parse не может
    распарсить hostname — возвращаем пустую строку."""
    assert _host_from_url("api.example.com/path") == ""


def test_host_from_url_path_only() -> None:
    assert _host_from_url("https://example.com") == "example.com"


def test_host_from_url_subdomain() -> None:
    assert _host_from_url("https://v1.api.staging.example.com/x") == "v1.api.staging.example.com"


def test_host_from_url_empty() -> None:
    assert _host_from_url("") == ""


def test_host_from_url_path_with_query() -> None:
    assert _host_from_url("https://example.com/path?q=1") == "example.com"
