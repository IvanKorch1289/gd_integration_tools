"""Smoke-тесты :class:`LiteTemporalBackend` (Sprint 4 К3-D).

Проверяют:
* :meth:`connect` с mock ``WorkflowEnvironment.start_local`` — backend.client
  равен env.client, namespace передаётся;
* :meth:`shutdown` идемпотентен (повторный вызов — no-op);
* :meth:`shutdown` ловит exception от env.shutdown() и логирует
  без re-raise;
* property ``env`` возвращает текущий env (или None после shutdown);
* Конструктор сохраняет refs и default_task_queue.

``temporalio`` — реальный установленный SDK (1.27.x); мокаем только
``WorkflowEnvironment.start_local`` через ``monkeypatch.setattr``,
чтобы не запускать локальный Temporal-сервер.
"""
# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("temporalio", reason="temporalio SDK not installed")

from src.backend.infrastructure.workflow.lite_temporal_backend import (
    LiteTemporalBackend,
)


class _FakeEnv:
    """Минимальный stand-in для ``WorkflowEnvironment``."""

    def __init__(self, *, client: Any, fail_shutdown: bool = False) -> None:
        self.client = client
        self._fail_shutdown = fail_shutdown
        self.shutdown_called = 0

    async def shutdown(self) -> None:
        self.shutdown_called += 1
        if self._fail_shutdown:
            raise RuntimeError("simulated env shutdown failure")


@pytest.fixture
def patch_start_local(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Подменить ``temporalio.testing.WorkflowEnvironment.start_local``.

    Возвращает словарь с фейковым env'ом, fake client и mock'ом
    start_local для inspectability.
    """
    from temporalio.testing import WorkflowEnvironment

    holder: dict[str, Any] = {}
    fake_client = MagicMock(name="temporal-client")
    fake_env = _FakeEnv(client=fake_client)
    holder["env"] = fake_env
    holder["client"] = fake_client

    start_local_mock = AsyncMock(return_value=fake_env)
    monkeypatch.setattr(WorkflowEnvironment, "start_local", start_local_mock)
    holder["start_local_mock"] = start_local_mock
    return holder


@pytest.mark.asyncio
async def test_connect_passes_namespace_and_returns_backend(
    patch_start_local: dict[str, Any],
) -> None:
    backend = await LiteTemporalBackend.connect(namespace="custom-ns")
    start_local_mock: AsyncMock = patch_start_local["start_local_mock"]
    start_local_mock.assert_awaited_once()
    kwargs = start_local_mock.call_args.kwargs
    assert kwargs["namespace"] == "custom-ns"
    # data_converter передаётся (build_temporal_data_converter возвращает Any).
    assert "data_converter" in kwargs
    assert isinstance(backend, LiteTemporalBackend)
    assert backend._client is patch_start_local["client"]  # type: ignore[attr-defined]
    assert backend.env is patch_start_local["env"]


@pytest.mark.asyncio
async def test_connect_uses_default_task_queue_param(
    patch_start_local: dict[str, Any],
) -> None:
    backend = await LiteTemporalBackend.connect(default_task_queue="my-queue")
    assert backend._default_task_queue == "my-queue"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_connect_ignores_target_and_api_key(
    patch_start_local: dict[str, Any],
) -> None:
    """Target/api_key — игнорируются (in-process не нуждается)."""
    backend = await LiteTemporalBackend.connect(
        target="will-be-ignored:7233", api_key="will-be-ignored"
    )
    start_local_mock: AsyncMock = patch_start_local["start_local_mock"]
    kwargs = start_local_mock.call_args.kwargs
    assert "target" not in kwargs
    assert "api_key" not in kwargs
    assert backend.env is patch_start_local["env"]


@pytest.mark.asyncio
async def test_shutdown_calls_env_shutdown_once(
    patch_start_local: dict[str, Any],
) -> None:
    backend = await LiteTemporalBackend.connect()
    fake_env: _FakeEnv = patch_start_local["env"]
    await backend.shutdown()
    assert fake_env.shutdown_called == 1
    # Повторный вызов — no-op (env обнулён).
    await backend.shutdown()
    assert fake_env.shutdown_called == 1


@pytest.mark.asyncio
async def test_shutdown_swallows_env_shutdown_exception(
    patch_start_local: dict[str, Any],
) -> None:
    """``env.shutdown()`` exception → log.warning без re-raise."""
    fake_env: _FakeEnv = patch_start_local["env"]
    fake_env._fail_shutdown = True

    backend = await LiteTemporalBackend.connect()
    # Не должен пробрасывать exception.
    await backend.shutdown()
    assert fake_env.shutdown_called == 1
    # env обнулён даже при failure.
    assert backend._env is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_env_property_returns_env(
    patch_start_local: dict[str, Any],
) -> None:
    backend = await LiteTemporalBackend.connect()
    assert backend.env is patch_start_local["env"]


@pytest.mark.asyncio
async def test_init_constructs_with_explicit_client_and_env() -> None:
    """Direct constructor должен корректно сохранять refs."""
    fake_client = MagicMock()
    fake_env = _FakeEnv(client=fake_client)
    backend = LiteTemporalBackend(
        client=fake_client, env=fake_env, default_task_queue="t1"
    )
    assert backend._client is fake_client  # type: ignore[attr-defined]
    assert backend.env is fake_env
    assert backend._default_task_queue == "t1"  # type: ignore[attr-defined]
