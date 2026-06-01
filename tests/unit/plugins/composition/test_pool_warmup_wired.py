# ruff: noqa: S101, SLF001
"""Tail-debt s10-debt/c1 — проверка wiring :class:`PoolWarmup` в lifespan.

Закрывает orphan-scaffold: :class:`PoolWarmup` создан в S9 K2 W3, но до
этого коммита не имел production-callера. Тесты гарантируют, что
``pool_warmup`` присутствует в ``starting_operations`` и корректно
обрабатывает primary-only и primary+replica конфигурации.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.plugins.composition import setup_infra


def test_pool_warmup_registered_in_starting_operations() -> None:
    """``pool_warmup`` должен присутствовать после initialize-операций пулов."""

    names = [name for name, *_ in setup_infra.starting_operations]

    assert "pool_warmup" in names, names
    # Warmup может работать только после initialize: db pools + redis + ch
    # должны быть до него.
    pool_warmup_idx = names.index("pool_warmup")
    for required in (
        "db_async_pool_main",
        "db_async_pool_external",
        "clickhouse_client",
    ):
        assert names.index(required) < pool_warmup_idx, (required, names)


async def test_warmup_invokes_both_engines_when_replica_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если ``replica_engine`` задан — :class:`PoolWarmup` получает оба engine."""

    captured: dict[str, Any] = {}

    class _StubPoolWarmup:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def warmup(self) -> Any:
            return SimpleNamespace(
                duration_seconds=0.0, warmed_pools=[], failed_pools={}
            )

    primary = object()
    replica = object()
    fake_initializer = SimpleNamespace(
        async_engine=primary, replica_engine=replica
    )

    monkeypatch.setattr(setup_infra, "get_db_initializer", lambda: fake_initializer)
    monkeypatch.setattr(setup_infra, "_redis_enabled", lambda: False)
    monkeypatch.setattr(setup_infra, "_clickhouse_enabled", lambda: False)
    monkeypatch.setattr(
        "src.backend.infrastructure.database.pool_warmup.PoolWarmup",
        _StubPoolWarmup,
    )

    await setup_infra._warmup_connection_pools()

    assert captured["pg_engine"] is primary
    assert captured["pg_replica_engine"] is replica
    assert captured["redis_client"] is None
    assert captured["clickhouse_client"] is None


async def test_warmup_fallback_primary_only_when_no_replica(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Когда ``replica_engine=None`` — warmup получает только primary."""

    captured: dict[str, Any] = {}

    class _StubPoolWarmup:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

        async def warmup(self) -> Any:
            return SimpleNamespace(
                duration_seconds=0.0, warmed_pools=["pg"], failed_pools={}
            )

    primary = object()
    fake_initializer = SimpleNamespace(async_engine=primary, replica_engine=None)

    monkeypatch.setattr(setup_infra, "get_db_initializer", lambda: fake_initializer)
    monkeypatch.setattr(setup_infra, "_redis_enabled", lambda: False)
    monkeypatch.setattr(setup_infra, "_clickhouse_enabled", lambda: False)
    monkeypatch.setattr(
        "src.backend.infrastructure.database.pool_warmup.PoolWarmup",
        _StubPoolWarmup,
    )

    await setup_infra._warmup_connection_pools()

    assert captured["pg_engine"] is primary
    assert captured["pg_replica_engine"] is None


async def test_warmup_noop_when_all_backends_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Когда все backends недоступны — warmup завершается без вызова PoolWarmup."""

    called = False

    class _StubPoolWarmup:
        def __init__(self, **kwargs: Any) -> None:
            nonlocal called
            called = True

        async def warmup(self) -> Any:
            return None

    fake_initializer = SimpleNamespace(async_engine=None, replica_engine=None)
    monkeypatch.setattr(setup_infra, "get_db_initializer", lambda: fake_initializer)
    monkeypatch.setattr(setup_infra, "_redis_enabled", lambda: False)
    monkeypatch.setattr(setup_infra, "_clickhouse_enabled", lambda: False)
    monkeypatch.setattr(
        "src.backend.infrastructure.database.pool_warmup.PoolWarmup",
        _StubPoolWarmup,
    )

    await setup_infra._warmup_connection_pools()

    assert called is False
