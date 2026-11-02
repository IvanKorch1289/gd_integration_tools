"""W25.2 — Round-trip тесты builder → to_spec → load_pipeline_from_dict.

Проверяет, что для процессоров с примитивными аргументами цикл
``RouteBuilder → Pipeline.to_dict → load_pipeline_from_dict`` сохраняет
эквивалентность представления (по итоговому ``to_dict``).

Покрывает W25.2 supported subset: set_header / set_property / log /
transform / dispatch_action / enrich / throttle / delay.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml

#: Action'ы, которые используют тесты модуля.
_REQUIRED_ACTIONS = ("rt.handler", "orders.create", "users.lookup")


@pytest.fixture(autouse=True)
def _registered_actions() -> Iterator[None]:
    """Гарантирует регистрацию action'ов теста в глобальном реестре (ADR-0410).

    ``Pipeline.build()`` и YAML-загрузчик (``load_pipeline_from_yaml``)
    валидируют имена ``dispatch_action`` по ЖИВОМУ глобальному реестру
    (``action_handler_registry.list_actions()``). Пока реестр пуст —
    валидация пропускается, и round-trip проходит; как только реестр
    наполняет соседний тест-модуль, ``rt.handler`` становится «неизвестным»
    и тест падает (order-dependent, ADR-0410).

    Фикстура делает зависимость явной: нужные action'ы зарегистрированы на
    время теста, а после — реестр возвращён к исходному состоянию
    (snapshot/restore, паттерн ADR-0404). Валидация имён action'ов при этом
    ОСТАЁТСЯ включённой — тест не отключает продуктовую проверку.
    """
    from src.backend.dsl.commands.registry import action_handler_registry

    saved_handlers = dict(action_handler_registry._handlers)
    saved_metadata = dict(action_handler_registry._metadata)
    saved_middleware = list(action_handler_registry._middleware)
    try:
        for name in _REQUIRED_ACTIONS:
            if name not in action_handler_registry.list_actions():
                action_handler_registry.register(
                    action=name,
                    service_getter=lambda: None,
                    service_method="noop",
                    payload_model=None,
                )
        yield
    finally:
        action_handler_registry.clear()
        action_handler_registry._handlers.update(saved_handlers)
        action_handler_registry._metadata.update(saved_metadata)
        action_handler_registry._middleware.extend(saved_middleware)


def _round_trip(builder: RouteBuilder) -> tuple[dict, dict]:
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    return dump, rebuilt.to_dict()


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("set_header", {"key": "x-trace", "value": "abc-123"}),
        ("set_property", {"key": "domain", "value": "orders"}),
        ("log", {"level": "warning"}),
        ("transform", {"expression": "items[?active].id"}),
        ("dispatch_action", {"action": "orders.create"}),
        ("enrich", {"action": "users.lookup"}),
        ("throttle", {"rate": 10.0}),
        ("delay", {"delay_ms": 250}),
    ],
)
def test_single_processor_round_trip(method: str, kwargs: dict) -> None:
    builder = RouteBuilder.from_("rt.single", source="test:rt.single")
    getattr(builder, method)(**kwargs)
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt, (
        f"Round-trip mismatch for {method}: {original} != {rebuilt}"
    )


def test_multi_processor_pipeline_round_trip() -> None:
    builder = (
        RouteBuilder.from_("rt.multi", source="test:rt.multi", description="multi")
        .set_header(key="x-route-id", value="rt.multi")
        .set_property(key="domain", value="rt")
        .log(level="info")
        .transform(expression="data")
        .dispatch_action("rt.handler")
    )
    original, rebuilt = _round_trip(builder)
    assert original == rebuilt
    assert original["route_id"] == "rt.multi"
    assert len(original["processors"]) == 5


def test_dispatch_action_with_payload_factory_skipped_in_spec() -> None:
    """Процессор с callable-аргументом не сериализуется (to_spec → None)."""
    builder = (
        RouteBuilder.from_("rt.skip", source="test:rt.skip")
        .set_header(key="k", value="v")
        .dispatch_action("rt.handler", payload_factory=lambda ex: {"x": 1})
        .log(level="info")
    )
    # Реестр action'ов изолирован фикстурой ``_registered_actions`` —
    # валидация имён остаётся включённой (ADR-0410).
    pipeline = builder.build()
    spec = pipeline.to_dict()
    procs = spec["processors"]
    # dispatch_action с payload_factory выпал из spec'а; остальные сохранились.
    methods = [next(iter(p)) for p in procs]
    assert methods == ["set_header", "log"]
