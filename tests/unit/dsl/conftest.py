"""Shared fixtures для тестов в tests/unit/dsl/.

Cycle 57: расширил scope conftest из tests/unit/dsl/commands/ до
tests/unit/dsl/ (parent dir) — позволяет использовать fixtures
в tests/unit/dsl/engine/processors/ и других subdirs.

Fixtures:
- captured_action_command: monkeypatch ``ActionHandlerRegistry.dispatch``
  для захвата ``ActionCommandSchema`` (cycle 45).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit._capability_mocks import patched_db_capability_allow


@pytest.fixture
def captured_action_command(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``ActionHandlerRegistry.dispatch`` для захвата ``ActionCommandSchema``.

    Returns dict с ключом ``"command"`` для assertion.
    Default ``fake_dispatch`` возвращает ``{"result": "ok"}`` dict.

    Handles both calling conventions:
    - Class attribute replacement (``registry.dispatch(command)``) — first arg is ``self``
    - Direct function call (``dispatch(command)``) — first arg is command
    Fixture detects which convention and captures the actual ``command``.

    Кастомизация return value через ``captured_action_command["_return"]``::

        captured_action_command["_return"] = ["item1", "item2"]
    """
    captured: dict[str, Any] = {}

    async def fake_dispatch(*args: Any, **kwargs: Any) -> Any:
        # ``registry.dispatch(command)`` → args=(self, command).
        # ``dispatch(command)`` → args=(command,).
        # Detect via type: ActionHandlerRegistry is the class instance.
        from src.backend.dsl.commands.action_registry import ActionHandlerRegistry

        actual_command = None
        for arg in args:
            if not isinstance(arg, ActionHandlerRegistry):
                actual_command = arg
                break
        if actual_command is None:
            actual_command = kwargs.get("command")
        captured["command"] = actual_command
        return captured.get("_return", {"result": "ok"})

    from src.backend.dsl.commands.action_registry import ActionHandlerRegistry

    monkeypatch.setattr(ActionHandlerRegistry, "dispatch", fake_dispatch)
    return captured


@pytest.fixture(autouse=True)
def _allow_db_capability_for_dsl(request: pytest.FixtureRequest) -> None:
    """ADR-0393: capability-гейт разрешён для тестов БД-шагов DSL.

    DSL-процессоры доступа к БД объявляют ``required_capability``
    (``db.read`` / ``db.write``) → прямой вызов ``process()`` без
    namespace'а роута получал бы fail-closed отказ (ADR-0366). Тесты
    проверки поведения БД не дублируют проверку авторизации — она покрыта
    отдельно (см. ``tests/unit/dsl/engine/capability/``).

    Модуль может отключить подмену, задав ``REAL_CAPABILITY_GATE = True``.
    """
    if getattr(request.module, "REAL_CAPABILITY_GATE", False):
        yield
        return
    with patched_db_capability_allow():
        yield
