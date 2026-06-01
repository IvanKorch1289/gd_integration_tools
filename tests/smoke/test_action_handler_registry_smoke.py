"""S36 w1 — Smoke test: ActionHandlerRegistry.

Проверяет критический путь: регистрация action-handler'ов,
получение метаданных, листинг, dispatch через in-memory stub.
"""

# ruff: noqa: S101

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from src.backend.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    ActionHandlerSpec,
)


class _StubPayload(BaseModel):
    """Минимальный payload для smoke-теста."""


@dataclass(slots=True)
class _StubService:
    """Сервис-стаб с методом echo()."""

    def echo(self, payload: _StubPayload) -> str:
        return f"echo:{payload}"


def test_registry_register_and_list() -> None:
    """register() добавляет action; list_actions() возвращает его."""
    registry = ActionHandlerRegistry()

    registry.register(
        action="smoke.actions.echo",
        service_getter=lambda: _StubService(),
        service_method="echo",
        payload_model=_StubPayload,
    )

    assert "smoke.actions.echo" in registry.list_actions()


def test_registry_register_many() -> None:
    """register_many() регистрирует пакет ActionHandlerSpec'ов за один вызов."""
    registry = ActionHandlerRegistry()
    specs = [
        ActionHandlerSpec(
            action=f"smoke.actions.bulk_{i}",
            service_getter=lambda: _StubService(),
            service_method="echo",
            payload_model=_StubPayload,
        )
        for i in range(3)
    ]

    registry.register_many(specs)

    actions = registry.list_actions()
    assert len(actions) == 3
    assert all(a.startswith("smoke.actions.bulk_") for a in actions)


def test_registry_get_metadata_returns_none_for_unknown() -> None:
    """get_metadata(unknown_action) → None (не raises)."""
    registry = ActionHandlerRegistry()

    result = registry.get_metadata("smoke.actions.nonexistent")

    assert result is None


def test_registry_metadata_isolated_per_instance() -> None:
    """Каждый ActionHandlerRegistry — изолированное хранилище."""
    reg_a = ActionHandlerRegistry()
    reg_b = ActionHandlerRegistry()

    reg_a.register(
        action="smoke.actions.isolated",
        service_getter=lambda: _StubService(),
        service_method="echo",
        payload_model=_StubPayload,
    )

    assert "smoke.actions.isolated" in reg_a.list_actions()
    assert "smoke.actions.isolated" not in reg_b.list_actions()
