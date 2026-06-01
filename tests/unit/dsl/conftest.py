# ruff: noqa: SLF001
"""Conftest для DSL unit-тестов: изоляция глобальных реестров между тестами.

Между тестами расходится :class:`ProcessorRegistry` — модули могут
регистрировать свои процессоры через побочные ``@processor``-декораторы,
из-за чего blueprint-тесты валятся в зависимости от порядка запуска.

Дополнительно для модуля :mod:`tests.unit.dsl.test_blueprints` инжектируются
фейковые имена действий, отсутствующие в реальном реестре, но необходимые
валидатору :meth:`RouteBuilder._validate_action_names`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.dsl.registry import get_processor_registry


@pytest.fixture(autouse=True)
def _reset_processor_registry() -> Iterator[None]:
    """Снимает snapshot ProcessorRegistry до теста и восстанавливает после."""

    registry = get_processor_registry()
    snapshot = dict(registry._by_fqn)
    try:
        yield
    finally:
        registry._by_fqn.clear()
        registry._by_fqn.update(snapshot)


@pytest.fixture(autouse=True)
def _stabilize_blueprint_actions(request: pytest.FixtureRequest) -> Iterator[None]:
    """Стабилизирует blueprint-тесты при непустом ``action_handler_registry``.

    :meth:`RouteBuilder._validate_action_names` пропускает валидацию только
    при пустом реестре. Когда в сессии раньше выполнялись модули,
    предзаполняющие реестр (``test_action_metadata_contract.py`` через
    module-scoped fixture, импортирующий ``get_v1_routers()``), валидатор
    срабатывает и blueprint-тесты падают на фейковых именах действий
    (``messaging.publish_event``/``data.ingest``/``documents.process``).

    Фикстура активна только для модуля :mod:`tests.unit.dsl.test_blueprints`
    — добавляет недостающие имена на время теста и удаляет их после.
    Остальные тесты не затрагиваются.
    """

    test_module = request.node.module.__name__ if request.node.module else ""
    if not test_module.endswith("test_blueprints"):
        yield
        return

    from src.backend.core.interfaces.action_dispatcher import ActionMetadata
    from src.backend.dsl.commands.action_registry import ActionHandlerSpec

    injected: list[str] = []
    for action_name in (
        "messaging.publish_event",
        "data.ingest",
        "documents.process",
        "orders.create",
    ):
        if action_name in action_handler_registry._handlers:
            continue
        action_handler_registry._handlers[action_name] = ActionHandlerSpec(
            action=action_name,
            service_getter=lambda: None,
            service_method="noop",
            payload_model=None,
        )
        action_handler_registry._metadata.setdefault(
            action_name, ActionMetadata(action=action_name)
        )
        injected.append(action_name)

    try:
        yield
    finally:
        for action_name in injected:
            action_handler_registry._handlers.pop(action_name, None)
            action_handler_registry._metadata.pop(action_name, None)
