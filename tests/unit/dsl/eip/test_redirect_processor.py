"""Unit-тесты RedirectProcessor (Wave 18.U3).

Покрытие:
    * Все 5 источников URL (static / header / body_field / exchange_var / query_param).
    * Whitelist по allowed_hosts для query_param.
    * Валидация конструктора (mode/status_code/url_source/source_key).
    * to_spec() для round-trip сериализации.
"""
# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, Message
from src.dsl.engine.processors.proxy.redirect import RedirectProcessor


def _make_exchange(*, body=None, headers=None, properties=None) -> Exchange:
    """Создаёт чистый Exchange с заданным in_message и properties."""
    exchange = Exchange(in_message=Message(body=body, headers=headers or {}))
    if properties:
        for k, v in properties.items():
            exchange.set_property(k, v)
    return exchange


def _make_context() -> ExecutionContext:
    """Возвращает минимальный ExecutionContext для процессора."""
    return ExecutionContext(route_id="test-route")


# ---------------------------------------------------------------------------
# mode=static
# ---------------------------------------------------------------------------


async def test_static_mode_sets_location_and_stops() -> None:
    """static-режим: устанавливает Location, status_code и stop()."""
    proc = RedirectProcessor(
        mode="static", status_code=301, target_url="http://example.com/new"
    )
    exchange = _make_exchange()
    await proc.process(exchange, _make_context())

    assert exchange.stopped is True
    assert exchange.get_property("_http_status_code") == 301
    assert exchange.get_property("_redirect_to") == "http://example.com/new"
    assert exchange.out_message is not None
    assert exchange.out_message.headers.get("Location") == "http://example.com/new"


async def test_static_mode_default_status_code_is_302() -> None:
    """status_code по умолчанию = 302."""
    proc = RedirectProcessor(mode="static", target_url="/v2/api")
    exchange = _make_exchange()
    await proc.process(exchange, _make_context())
    assert exchange.get_property("_http_status_code") == 302


# ---------------------------------------------------------------------------
# mode=proxy / url_source variants
# ---------------------------------------------------------------------------


async def test_proxy_header_source() -> None:
    """proxy: URL берётся из header in_message."""
    proc = RedirectProcessor(
        mode="proxy", url_source="header", source_key="X-Redirect-To"
    )
    exchange = _make_exchange(headers={"X-Redirect-To": "http://h.example/path"})
    await proc.process(exchange, _make_context())
    assert exchange.get_property("_redirect_to") == "http://h.example/path"
    assert exchange.stopped is True


async def test_proxy_body_field_source_dotted() -> None:
    """proxy: body_field с точечным путём ``a.b.c``."""
    proc = RedirectProcessor(
        mode="proxy", url_source="body_field", source_key="meta.target.url"
    )
    exchange = _make_exchange(
        body={"meta": {"target": {"url": "http://body.example/here"}}}
    )
    await proc.process(exchange, _make_context())
    assert exchange.get_property("_redirect_to") == "http://body.example/here"


async def test_proxy_exchange_var_source() -> None:
    """proxy: exchange_var — URL из exchange.properties."""
    proc = RedirectProcessor(
        mode="proxy", url_source="exchange_var", source_key="redirect_url"
    )
    exchange = _make_exchange(properties={"redirect_url": "http://var.example/x"})
    await proc.process(exchange, _make_context())
    assert exchange.get_property("_redirect_to") == "http://var.example/x"


async def test_proxy_query_param_source() -> None:
    """proxy: query_param — URL из header вида ``__query_<key>``."""
    proc = RedirectProcessor(
        mode="proxy", url_source="query_param", source_key="next"
    )
    exchange = _make_exchange(headers={"__query_next": "http://qp.example/dest"})
    await proc.process(exchange, _make_context())
    assert exchange.get_property("_redirect_to") == "http://qp.example/dest"


# ---------------------------------------------------------------------------
# allowed_hosts whitelist (query_param и не только)
# ---------------------------------------------------------------------------


async def test_query_param_with_allowed_hosts_pass() -> None:
    """query_param + allowed_hosts: разрешённый хост проходит."""
    proc = RedirectProcessor(
        mode="proxy",
        url_source="query_param",
        source_key="back",
        allowed_hosts=["example.com", "partner.org"],
    )
    exchange = _make_exchange(headers={"__query_back": "https://example.com/page"})
    await proc.process(exchange, _make_context())
    assert exchange.get_property("_redirect_to") == "https://example.com/page"
    assert exchange.error is None


async def test_query_param_with_allowed_hosts_blocked() -> None:
    """query_param + allowed_hosts: чужой хост блокируется через fail()."""
    proc = RedirectProcessor(
        mode="proxy",
        url_source="query_param",
        source_key="back",
        allowed_hosts=["example.com"],
    )
    exchange = _make_exchange(headers={"__query_back": "https://evil.example/x"})
    await proc.process(exchange, _make_context())
    assert exchange.error is not None
    assert "evil.example" in exchange.error
    assert exchange.out_message is None  # Location не установлен


# ---------------------------------------------------------------------------
# Валидация конструктора
# ---------------------------------------------------------------------------


def test_invalid_mode_raises() -> None:
    """Неверный mode → ValueError."""
    with pytest.raises(ValueError, match="mode="):
        RedirectProcessor(mode="weird", target_url="http://a/")


def test_invalid_status_code_raises() -> None:
    """status_code вне whitelist → ValueError."""
    with pytest.raises(ValueError, match="status_code"):
        RedirectProcessor(mode="static", status_code=200, target_url="http://a/")


def test_static_without_target_raises() -> None:
    """mode=static без target_url → ValueError."""
    with pytest.raises(ValueError, match="target_url"):
        RedirectProcessor(mode="static")


def test_proxy_without_url_source_raises() -> None:
    """mode=proxy без url_source → ValueError."""
    with pytest.raises(ValueError, match="url_source"):
        RedirectProcessor(mode="proxy", source_key="k")


def test_proxy_without_source_key_raises() -> None:
    """mode=proxy без source_key → ValueError."""
    with pytest.raises(ValueError, match="source_key"):
        RedirectProcessor(mode="proxy", url_source="header")


def test_proxy_with_invalid_url_source_raises() -> None:
    """mode=proxy с неизвестным url_source → ValueError."""
    with pytest.raises(ValueError, match="url_source"):
        RedirectProcessor(mode="proxy", url_source="bogus", source_key="k")


# ---------------------------------------------------------------------------
# to_spec — round-trip сериализация
# ---------------------------------------------------------------------------


def test_to_spec_static() -> None:
    """to_spec для static-режима содержит target_url + status_code."""
    proc = RedirectProcessor(
        mode="static", status_code=308, target_url="http://x.example/"
    )
    assert proc.to_spec() == {
        "redirect": {"status_code": 308, "target_url": "http://x.example/"}
    }


def test_to_spec_proxy_with_allowed_hosts() -> None:
    """to_spec для proxy-режима содержит url_source/source_key/allowed_hosts."""
    proc = RedirectProcessor(
        mode="proxy",
        status_code=302,
        url_source="query_param",
        source_key="next",
        allowed_hosts=["a.com", "b.org"],
    )
    spec = proc.to_spec()
    assert spec["redirect"]["url_source"] == "query_param"
    assert spec["redirect"]["source_key"] == "next"
    assert sorted(spec["redirect"]["allowed_hosts"]) == ["a.com", "b.org"]


# ---------------------------------------------------------------------------
# Прочие edge cases
# ---------------------------------------------------------------------------


async def test_proxy_missing_url_in_source_raises() -> None:
    """Если в источнике URL отсутствует — поднимается ValueError."""
    proc = RedirectProcessor(
        mode="proxy", url_source="header", source_key="X-Missing"
    )
    exchange = _make_exchange()
    with pytest.raises(ValueError, match="не удалось получить URL"):
        await proc.process(exchange, _make_context())


async def test_proxy_body_field_non_dict_returns_none() -> None:
    """body_field на не-dict body → попытка извлечь URL вернёт None → ValueError."""
    proc = RedirectProcessor(
        mode="proxy", url_source="body_field", source_key="x.y"
    )
    exchange = _make_exchange(body="raw string")
    with pytest.raises(ValueError):
        await proc.process(exchange, _make_context())
