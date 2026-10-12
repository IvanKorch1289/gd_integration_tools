"""Unit-тесты для response-binding (ADR-0349).

Покрывают:
* helper рендеринга ``${expr}`` в literal-значениях body;
* контракт ``Pipeline.response`` (новое поле, по умолчанию ``None``);
* ``RouteBuilder.to_response`` пробрасывает binding в Pipeline;
* ``ExecutionEngine._finalize`` записывает ``out_message`` из binding;
* YAML ``to:`` в ``_build_pipeline`` конструирует ``ResponseBinding``.

Тест на ``builder_facade.execute_route`` намеренно не входит: facade
читает ``out_message.body`` без изменений (см. существующий test_builder_facade_proxy),
поэтому факт прохождения binding до facade проверяется через прямой
тест ``_finalize``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline, ResponseBinding
from src.backend.dsl.engine.processors.core import TransformProcessor
from src.backend.dsl.yaml_loader.build import _build_pipeline

# ─────────────────────── render helper ───────────────────────


def _resolve_stub(exchange: Exchange[Any], expr: str | None) -> Any:
    """Замена _resolve для предсказуемого теста рендера (не зависит от JMESPath)."""
    return f"RESOLVED({expr!r})"


def test_render_binding_value_resolves_dollar_brace_strings() -> None:
    """Строки ${expr} подставляются через переданный resolver."""
    out = ExecutionEngine._render_binding_value(
        {"status": "ok", "uid": "${body.user_id}"},
        _resolve_stub,
        exchange=Exchange(in_message=Message(body={})),
    )
    assert out == {"status": "ok", "uid": "RESOLVED('body.user_id')"}


def test_render_binding_value_passes_literals_through() -> None:
    """Нестроковые значения и строки без ``${…}`` остаются как есть."""
    out = ExecutionEngine._render_binding_value(
        {"a": 42, "b": None, "c": "literal", "d": "$not closed", "e": "${incomplete"},
        _resolve_stub,
        exchange=Exchange(in_message=Message(body={})),
    )
    assert out == {
        "a": 42,
        "b": None,
        "c": "literal",
        "d": "$not closed",
        "e": "${incomplete",
    }


def test_render_binding_value_recurses_into_nested_structures() -> None:
    """Вложенные dict/list обходятся рекурсивно; резолв применяется на каждом уровне."""
    out = ExecutionEngine._render_binding_value(
        {"list": [{"x": "${body.x}"}, {"y": 1}], "deep": {"k": {"v": "${body.v}"}}},
        _resolve_stub,
        exchange=Exchange(in_message=Message(body={})),
    )
    assert out == {
        "list": [{"x": "RESOLVED('body.x')"}, {"y": 1}],
        "deep": {"k": {"v": "RESOLVED('body.v')"}},
    }


# ─────────────────────── pipeline & builder ───────────────────────


def test_pipeline_response_defaults_to_none() -> None:
    """Pipeline без binding имеет ``response=None`` — backward-compat."""
    p = Pipeline(route_id="r", processors=[TransformProcessor(expression="@")])
    assert p.response is None


def test_route_builder_to_response_sets_binding() -> None:
    """``to_response()`` накапливает binding и ``build()`` пробрасывает его."""
    rb = (
        RouteBuilder.from_("r", source="http:GET /r")
        .process(TransformProcessor(expression="@"))
        .to_response(
            ResponseBinding(body={"status": "ok"}, headers={"X-Frame-Options": "DENY"})
        )
    )
    p = rb.build()
    assert p.response is not None
    assert p.response.body == {"status": "ok"}
    assert p.response.headers == {"X-Frame-Options": "DENY"}


# ─────────────────────── execution ───────────────────────


def _build_pipeline_with_response(to_spec: dict[str, Any]) -> Pipeline:
    return (
        RouteBuilder.from_("r", source="http:GET /r")
        .process(TransformProcessor(expression="@"))
        .to_response(
            ResponseBinding(
                body=to_spec.get("body", {}), headers=to_spec.get("headers", {})
            )
        )
        .build()
    )


def test_finalize_writes_out_message_from_response_binding() -> None:
    """После выполнения ``out_message.body`` и ``out_message.headers`` соответствуют binding."""
    pipeline = _build_pipeline_with_response(
        {
            "body": {"status": "ok", "uid": "${body.user_id}"},
            "headers": {"X-Frame-Options": "DENY"},
        }
    )
    exchange = Exchange(
        in_message=Message(body={"user_id": 42, "ignored": "x"}, headers={})
    )
    out = asyncio.run(ExecutionEngine().execute(pipeline, exchange=exchange))

    assert out.status.value == "completed"
    assert out.out_message is not None
    assert out.out_message.body == {"status": "ok", "uid": 42}
    assert out.out_message.headers == {"X-Frame-Options": "DENY"}


def test_finalize_binding_overrides_processor_out_message() -> None:
    """Binding — финальная декларация маршрута, переопределяет ``out_message`` процессора.

    ADR-0349: автор роута явно указал форму ответа в ``to:`` — этот контракт
    важнее промежуточного состояния, выставленного процессорами. Ошибка
    процессора (``status=failed``) по-прежнему блокирует binding: см. ниже.
    """
    pipeline = _build_pipeline_with_response(
        {"body": {"from_binding": True}, "headers": {}}
    )
    pre = Exchange(in_message=Message(body={"x": 1}, headers={}))
    pre.out_message = Message(body={"from_processor": "ignored"}, headers={})
    out = asyncio.run(ExecutionEngine().execute(pipeline, exchange=pre))
    assert out.out_message is not None
    assert out.out_message.body == {"from_binding": True}


# Примечание о test "binding skipped on failed-status":
# Обнаружено, что ExecutionEngine.execute() перезаписывает pre-set
# status=failed на status=processing в самом начале. Это означает, что
# binding-тест на pre-failed изолированно проверить нельзя — статус
# будет сброшен. Сам контракт binding ("не подменять при failed")
# реализован в _finalize и активируется, если status==failed
# выставлен процессором во время execute. Интеграционный тест этого
# сценария выходит за рамки первого среза.


# ─────────────────────── YAML loader ───────────────────────


def test_yaml_to_block_builds_response_binding() -> None:
    """``to: {body: …, headers: …}`` в YAML создаёт ``Pipeline.response``."""
    spec = {
        "route_id": "r",
        "from": "http:GET /r",
        "steps": [{"transform": {"expression": "@"}}],
        "to": {
            "body": {"status": "ok", "uid": "${body.user_id}"},
            "headers": {"X-Frame-Options": "DENY"},
        },
    }
    p = _build_pipeline(spec)
    assert p.response is not None
    assert p.response.body == {"status": "ok", "uid": "${body.user_id}"}
    assert p.response.headers == {"X-Frame-Options": "DENY"}


def test_yaml_to_block_only_body() -> None:
    """``to: {body: …}`` без headers — допустимо, headers=``{}``."""
    p = _build_pipeline(
        {
            "route_id": "r",
            "from": "http:GET /r",
            "steps": [{"transform": {"expression": "@"}}],
            "to": {"body": {"k": "v"}},
        }
    )
    assert p.response is not None
    assert p.response.body == {"k": "v"}
    assert p.response.headers == {}


def test_yaml_to_block_only_headers() -> None:
    """``to: {headers: …}`` без body — допустимо, body=``{}``."""
    p = _build_pipeline(
        {
            "route_id": "r",
            "from": "http:GET /r",
            "steps": [{"transform": {"expression": "@"}}],
            "to": {"headers": {"X-Frame-Options": "DENY"}},
        }
    )
    assert p.response is not None
    assert p.response.body == {}
    assert p.response.headers == {"X-Frame-Options": "DENY"}


def test_yaml_to_block_rejects_garbage() -> None:
    """``to:`` должен быть mapping с body и/или headers."""
    # Не dict
    with pytest.raises(ValueError, match="'to' must be a mapping"):
        _build_pipeline(
            {
                "route_id": "r",
                "from": "http:GET /r",
                "steps": [{"transform": {"expression": "@"}}],
                "to": "not a dict",
            }
        )
    # dict без body и headers
    with pytest.raises(ValueError, match="at least one of 'body' or 'headers'"):
        _build_pipeline(
            {
                "route_id": "r",
                "from": "http:GET /r",
                "steps": [{"transform": {"expression": "@"}}],
                "to": {"foo": "bar"},
            }
        )
    # body не dict
    with pytest.raises(ValueError, match="'to.body' must be a mapping"):
        _build_pipeline(
            {
                "route_id": "r",
                "from": "http:GET /r",
                "steps": [{"transform": {"expression": "@"}}],
                "to": {"body": "literal-string-is-wrong"},
            }
        )
