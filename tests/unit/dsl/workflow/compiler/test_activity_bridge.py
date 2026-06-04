"""Тесты :mod:`dsl.workflow.compiler.activity_bridge`.

Проверяют:
* :func:`bridge_action_handler` — корректный wrapping и атрибуты ``__name__`` /
  ``__activity_name__``;
* :class:`ActivityBridge.get` — кэш по ``action_id``;
* :meth:`ActivityBridge.collect_activities` — без дубликатов, включая saga;
* :meth:`ActivityBridge.decorate` — идемпотентен (повторный вызов не дублирует
  декораторы).
"""

from __future__ import annotations

import pytest  # noqa: S101

pytest.importorskip(
    "temporalio", reason="temporalio not installed — run: uv sync --extra workflow"
)

from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.compiler.activity_bridge import (
    ActivityBridge,
    bridge_action_handler,
    get_activity_callables,
)


def test_bridge_action_handler_sets_attribute_metadata() -> None:
    fn = bridge_action_handler("orders.create")
    assert fn.__activity_name__ == "orders.create"  # type: ignore[attr-defined]
    # Точки заменены на underscore для Python identifier (Temporal не позволяет '.' в __name__).
    assert fn.__name__ == "orders_create"
    assert "activity::orders.create" in fn.__qualname__


def test_bridge_handler_is_async_callable() -> None:
    import inspect

    fn = bridge_action_handler("foo.bar")
    # Не вызываем — handler dispatch'ит через action_handler_registry,
    # который потребовал бы реальный handler. Проверка только сигнатуры.
    assert inspect.iscoroutinefunction(fn)


def test_activity_bridge_caches_by_action_id() -> None:
    bridge = ActivityBridge()
    a = bridge.get("orders.create")
    b = bridge.get("orders.create")
    assert a is b


def test_activity_bridge_creates_new_wrapper_per_action_id() -> None:
    bridge = ActivityBridge()
    a = bridge.get("orders.create")
    b = bridge.get("payment.charge")
    assert a is not b
    assert a.__activity_name__ != b.__activity_name__  # type: ignore[attr-defined]


def test_collect_activities_skips_duplicates_across_workflows() -> None:
    bridge = ActivityBridge()
    decl1 = (
        WorkflowBuilder("wf.a").activity("foo.shared").activity("foo.unique_a").build()
    )
    decl2 = (
        WorkflowBuilder("wf.b")
        .activity("foo.shared")  # duplicate
        .activity("foo.unique_b")
        .build()
    )
    activities = bridge.collect_activities([decl1, decl2])
    names = [getattr(fn, "__activity_name__") for fn in activities]
    assert names == ["foo.shared", "foo.unique_a", "foo.unique_b"]


def test_collect_activities_includes_saga_forward_and_compensate() -> None:
    bridge = ActivityBridge()
    decl = (
        WorkflowBuilder("orders.flow")
        .saga()
        .forward("orders.create")
        .forward("payment.charge")
        .compensate("orders.cancel")
        .compensate("payment.refund")
        .end_saga()
        .build()
    )
    activities = bridge.collect_activities([decl])
    names = [getattr(fn, "__activity_name__") for fn in activities]
    assert set(names) == {
        "orders.create",
        "payment.charge",
        "orders.cancel",
        "payment.refund",
    }


def test_collect_activities_no_duplicates_for_saga_with_repeating_activities() -> None:
    bridge = ActivityBridge()
    decl = (
        WorkflowBuilder("repeat")
        .activity("foo.x")  # вне saga
        .saga()
        .forward("foo.x")  # тот же action_id
        .compensate("foo.y")
        .end_saga()
        .build()
    )
    activities = bridge.collect_activities([decl])
    names = [getattr(fn, "__activity_name__") for fn in activities]
    assert names.count("foo.x") == 1
    assert names.count("foo.y") == 1


def test_decorate_is_idempotent() -> None:
    """Повторный decorate() не плодит ``@activity.defn``-обёртки."""
    bridge = ActivityBridge()
    bridge.get("foo.bar")
    bridge.decorate()
    decorated_first = bridge._cache["foo.bar"]
    bridge.decorate()
    decorated_second = bridge._cache["foo.bar"]
    assert decorated_first is decorated_second


def test_decorate_applies_temporal_activity_marker() -> None:
    bridge = ActivityBridge()
    bridge.get("orders.create")
    bridge.decorate()
    fn = bridge._cache["orders.create"]
    assert getattr(fn, "__temporal_activity_definition", None) is not None


def test_get_activity_callables_with_default_bridge() -> None:
    decl = WorkflowBuilder("a").activity("foo").activity("bar").build()
    callables = get_activity_callables([decl])
    assert len(callables) == 2
    names = [getattr(fn, "__activity_name__") for fn in callables]
    assert names == ["foo", "bar"]


def test_get_activity_callables_with_shared_bridge() -> None:
    bridge = ActivityBridge()
    decl_a = WorkflowBuilder("a").activity("foo").build()
    decl_b = WorkflowBuilder("b").activity("foo").build()  # same activity
    list_a = get_activity_callables([decl_a], bridge=bridge)
    list_b = get_activity_callables([decl_b], bridge=bridge)
    # Bridge возвращает уже-собранный список второго вызова (включает foo) —
    # реализация collect возвращает все уникальные за вызов.
    assert list_a[0] is list_b[0]  # cache shared
