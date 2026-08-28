"""Shared fixtures для тестирования ActionCommandSchema propagation.

Cycle 45 (Phase 4 Test infrastructure). Все principal/permissions
regression tests (cycles 24, 34, 35, 38, 39, 40, 41, 42) используют
один и тот же паттерн: monkeypatch.ActionHandlerRegistry.dispatch для
захвата ``command`` параметра.

Этот conftest предоставляет переиспользуемую fixture
``captured_action_command``, которая стандартизирует pattern и
убирает ~15 LOC boilerplate из каждого test файла.

Использование:

.. code-block:: python

    @pytest.mark.asyncio
    async def test_principal_propagation(captured_action_command):
        proc = MyProcessor(...)
        await proc.process(exchange, context)
        cmd = captured_action_command["command"]
        assert cmd.meta.principal == "alice"
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def captured_action_command(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``ActionHandlerRegistry.dispatch`` для захвата ``ActionCommandSchema``.

    Returns dict с ключом ``"command"`` для assertion.
    Default ``fake_dispatch`` возвращает ``{"result": "ok"}`` dict.

    Usage::

        async def test_x(captured_action_command):
            ...
            cmd = captured_action_command["command"]
            assert cmd.meta.principal == "alice"

    Кастомизация return value через ``captured_action_command["_return"]``:

        async def test_y(captured_action_command):
            captured_action_command["_return"] = ["item1", "item2"]
            ...
    """
    captured: dict[str, Any] = {}

    def fake_dispatch_factory() -> Any:
        async def fake_dispatch(command: Any, *args: Any, **kwargs: Any) -> Any:
            captured["command"] = command
            return captured.get("_return", {"result": "ok"})
        return fake_dispatch

    from src.backend.dsl.commands.action_registry import ActionHandlerRegistry

    monkeypatch.setattr(
        ActionHandlerRegistry, "dispatch", fake_dispatch_factory()
    )
    return captured
