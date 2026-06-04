"""Unit-тесты ``MaskPiiProcessor`` (Sprint 8A K1 W4).

Покрывают:

* маскировка body / headers / query / path по отдельности и комбинированно;
* custom patterns заменяют дефолтные;
* fields-whitelist маскирует только выбранные поля;
* round-trip ``to_spec()`` (для YAML);
* регистрация в ProcessorRegistry.
"""

# ruff: noqa: S101 — assert разрешён в pytest

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.mask_pii import ALLOWED_TARGETS, MaskPiiProcessor


def _ex(
    body: Any = None,
    headers: dict[str, Any] | None = None,
    *,
    request: Any | None = None,
) -> Exchange[Any]:
    exchange = Exchange(in_message=Message(body=body, headers=headers or {}))
    if request is not None:
        exchange.set_property("request", request)
    return exchange


# ── targets ──


@pytest.mark.asyncio
async def test_target_body_dict_masks_emails_and_phones() -> None:
    proc = MaskPiiProcessor(targets=["body"])
    exchange = _ex(body={"email": "alice@x.io", "phone": "+7 999 1234567", "age": 30})
    await proc.process(exchange, AsyncMock())
    body = exchange.in_message.body
    assert body["email"] == "***"
    assert body["phone"] == "***"
    assert body["age"] == 30


@pytest.mark.asyncio
async def test_target_body_string_payload_masks_inline() -> None:
    proc = MaskPiiProcessor(targets=["body"])
    exchange = _ex(body="Звоните +7 999 1234567 или email a@b.c")
    await proc.process(exchange, AsyncMock())
    assert exchange.in_message.body == "Звоните *** или email ***"


@pytest.mark.asyncio
async def test_target_body_list_of_dicts() -> None:
    proc = MaskPiiProcessor(targets=["body"])
    exchange = _ex(body=[{"email": "a@x.io"}, {"email": "b@y.io"}])
    await proc.process(exchange, AsyncMock())
    assert exchange.in_message.body == [{"email": "***"}, {"email": "***"}]


@pytest.mark.asyncio
async def test_target_headers_only_does_not_touch_body() -> None:
    proc = MaskPiiProcessor(targets=["headers"])
    exchange = _ex(
        body={"email": "should-stay@x.io"},
        headers={"X-User-Email": "a@b.c", "X-Trace": "ok"},
    )
    await proc.process(exchange, AsyncMock())
    # body не тронут — targets=['headers'] исключительно.
    assert exchange.in_message.body == {"email": "should-stay@x.io"}
    assert exchange.in_message.headers["X-User-Email"] == "***"
    # значение без PII осталось как есть.
    assert exchange.in_message.headers["X-Trace"] == "ok"


@pytest.mark.asyncio
async def test_target_query_masks_request_query_params() -> None:
    request = SimpleNamespace(query_params={"email": "user@x.io", "page": "1"})
    proc = MaskPiiProcessor(targets=["query"])
    exchange = _ex(request=request)
    await proc.process(exchange, AsyncMock())
    assert request.query_params["email"] == "***"
    assert request.query_params["page"] == "1"


@pytest.mark.asyncio
async def test_target_path_masks_request_path_params() -> None:
    request = SimpleNamespace(path_params={"inn": "7707083893"})
    proc = MaskPiiProcessor(targets=["path"])
    exchange = _ex(request=request)
    await proc.process(exchange, AsyncMock())
    assert request.path_params["inn"] == "***"


@pytest.mark.asyncio
async def test_query_no_request_is_noop() -> None:
    """Если request отсутствует — silent no-op (route запущен по таймеру)."""
    proc = MaskPiiProcessor(targets=["query"])
    exchange = _ex(body={"email": "a@x.io"})
    await proc.process(exchange, AsyncMock())
    # body не трогается — targets=['query'].
    assert exchange.in_message.body == {"email": "a@x.io"}


# ── fields whitelist ──


@pytest.mark.asyncio
async def test_fields_whitelist_masks_only_selected() -> None:
    proc = MaskPiiProcessor(targets=["body"], fields=["email"])
    exchange = _ex(
        body={"email": "a@x.io", "phone": "+7 999 1234567", "note": "ничего секретного"}
    )
    await proc.process(exchange, AsyncMock())
    body = exchange.in_message.body
    assert body["email"] == "***"
    # phone тоже PII, но не в fields-whitelist → остаётся.
    assert body["phone"] == "+7 999 1234567"
    assert body["note"] == "ничего секретного"


# ── custom patterns ──


@pytest.mark.asyncio
async def test_custom_patterns_replace_defaults() -> None:
    proc = MaskPiiProcessor(
        targets=["body"], patterns=[r"secret_\d+"], replacement="<hidden>"
    )
    exchange = _ex(body={"key": "secret_42 и email=a@b.c"})
    await proc.process(exchange, AsyncMock())
    # email остался (дефолтные patterns не задействованы), secret_42 заменён.
    assert exchange.in_message.body["key"] == "<hidden> и email=a@b.c"


@pytest.mark.asyncio
async def test_custom_replacement_applied() -> None:
    proc = MaskPiiProcessor(targets=["body"], replacement="[PII]")
    exchange = _ex(body={"email": "x@y.io"})
    await proc.process(exchange, AsyncMock())
    assert exchange.in_message.body["email"] == "[PII]"


# ── validation ──


def test_empty_targets_raises() -> None:
    with pytest.raises(ValueError, match="targets must be non-empty"):
        MaskPiiProcessor(targets=[])


def test_unknown_target_raises() -> None:
    with pytest.raises(ValueError, match="unknown targets"):
        MaskPiiProcessor(targets=["body", "cookies"])


def test_invalid_custom_regex_raises() -> None:
    with pytest.raises(ValueError, match="invalid regex"):
        MaskPiiProcessor(targets=["body"], patterns=["[invalid"])


def test_allowed_targets_is_frozenset() -> None:
    assert ALLOWED_TARGETS == frozenset({"body", "headers", "query", "path"})


# ── multi-target ──


@pytest.mark.asyncio
async def test_multi_target_body_and_headers() -> None:
    proc = MaskPiiProcessor(targets=["body", "headers"])
    exchange = _ex(
        body={"email": "u@x.io"}, headers={"X-Email": "h@x.io", "X-Trace": "tid-1"}
    )
    await proc.process(exchange, AsyncMock())
    assert exchange.in_message.body["email"] == "***"
    assert exchange.in_message.headers["X-Email"] == "***"


# ── to_spec round-trip ──


def test_to_spec_minimal() -> None:
    proc = MaskPiiProcessor(targets=["body"])
    spec = proc.to_spec()
    assert spec == {"mask_pii": {"targets": ["body"], "replacement": "***"}}


def test_to_spec_full() -> None:
    proc = MaskPiiProcessor(
        targets=["body", "headers"],
        fields=["email"],
        replacement="<X>",
        patterns=[r"\d+"],
    )
    spec = proc.to_spec()
    assert spec == {
        "mask_pii": {
            "targets": ["body", "headers"],
            "replacement": "<X>",
            "fields": ["email"],
            "patterns": [r"\d+"],
        }
    }


# ── registry integration ──


def test_processor_registered_in_core_namespace() -> None:
    """MaskPiiProcessor зарегистрирован в core: namespace через @processor."""
    from src.backend.dsl.registry import get_processor_registry

    registry = get_processor_registry()
    spec = registry.get("core:mask_pii")
    assert spec.cls is MaskPiiProcessor
    assert spec.namespace == "core"
    assert "pii" in spec.tags
    assert spec.spec_schema is not None
    assert "targets" in spec.spec_schema.get("required", [])


# ── builder integration ──


def test_route_builder_mask_pii_method() -> None:
    """``RouteBuilder.mask_pii(...)`` создаёт MaskPiiProcessor в pipeline."""
    from src.backend.dsl.builder import RouteBuilder

    pipeline = (
        RouteBuilder.from_("test_mask_pii_route", source="http:POST /api/v1/x")
        .mask_pii(targets=["body", "headers"], fields=["email"], replacement="<X>")
        .build()
    )
    assert len(pipeline.processors) == 1
    proc = pipeline.processors[0]
    assert isinstance(proc, MaskPiiProcessor)
    spec = proc.to_spec()
    assert spec["mask_pii"]["targets"] == ["body", "headers"]
    assert spec["mask_pii"]["fields"] == ["email"]
    assert spec["mask_pii"]["replacement"] == "<X>"
