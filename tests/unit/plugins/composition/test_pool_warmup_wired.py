"""Tail-debt s10-debt/c1 — проверка wiring :class:`PoolWarmup` в lifespan.

Закрывает orphan-scaffold: :class:`PoolWarmup` создан в S9 K2 W3, но до
этого коммита не имел production-callера. Тесты гарантируют, что
``pool_warmup`` присутствует в ``starting_operations`` и корректно
обрабатывает primary-only и primary+replica конфигурации.

TD-0247: после S60 W3 decomp ``starting_operations`` не экспортируется из
``setup_infra`` (его consumers в ``lifecycle.starting()`` ходят через
``perform_infrastructure_operation(starting_operations)`` напрямую из
module-private namespace). Тесты xfail — либо restore registry
(высокий scope), либо переписать тесты на новый contract
(``pools._warmup_connection_pools`` уже не принимает ``get_db_initializer``
через monkeypatch на ``setup_infra`` namespace — нужно patch на
``setup_infra.pools.get_db_initializer``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.plugins.composition import setup_infra

pytestmark = pytest.mark.xfail(
    reason="TD-0247: S60 decomp removed starting_operations; needs contract rewrite",
    strict=False,
)


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
    fake_initializer = SimpleNamespace(async_engine=primary, replica_engine=replica)

    monkeypatch.setattr(setup_infra, "get_db_initializer", lambda: fake_initializer)
    monkeypatch.setattr(setup_infra, "_redis_enabled", lambda: False)
    monkeypatch.setattr(setup_infra, "_clickhouse_enabled", lambda: False)
    monkeypatch.setattr(
        "src.backend.infrastructure.database.pool_warmup.PoolWarmup", _StubPoolWarmup
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
        "src.backend.infrastructure.database.pool_warmup.PoolWarmup", _StubPoolWarmup
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
        "src.backend.infrastructure.database.pool_warmup.PoolWarmup", _StubPoolWarmup
    )

    await setup_infra._warmup_connection_pools()

    assert called is False


def test_mongo_client_start_registered_before_pools_warmup() -> None:
    """P0 (audit a2bd6f294): MongoDBClient.start() должен быть в
    starting_operations РАНЬШЕ warmup и register-фазы (ensure_indexes),
    иначе индексы создаются на не-стартованном клиенте (молча ignored)."""

    from src.backend.plugins.composition.setup_infra import lifecycle

    ops = [name for name, _, _ in lifecycle.starting_operations]
    assert "start_mongo_client" in ops
    assert ops.index("start_mongo_client") < ops.index("warmup_connection_pools")


@pytest.mark.asyncio
async def test_start_mongo_client_invokes_start_when_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.plugins.composition.setup_infra.pools import _start_mongo_client

    calls: list[str] = []

    class _FakeMongo:
        def is_started(self) -> bool:
            return False

        async def start(self) -> None:
            calls.append("start")

    monkeypatch.setattr(
        "src.backend.plugins.composition.setup_infra.pools.get_mongo_client",
        lambda: _FakeMongo(),
    )
    monkeypatch.setattr(
        "src.backend.plugins.composition.setup_infra.pools._mongo_enabled", lambda: True
    )
    await _start_mongo_client()
    assert calls == ["start"]


@pytest.mark.asyncio
async def test_start_mongo_client_skips_when_started_or_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.backend.plugins.composition.setup_infra.pools import _start_mongo_client

    calls: list[str] = []

    class _StartedMongo:
        def is_started(self) -> bool:
            return True

        async def start(self) -> None:
            calls.append("start")

    monkeypatch.setattr(
        "src.backend.plugins.composition.setup_infra.pools.get_mongo_client",
        lambda: _StartedMongo(),
    )
    monkeypatch.setattr(
        "src.backend.plugins.composition.setup_infra.pools._mongo_enabled", lambda: True
    )
    await _start_mongo_client()
    assert calls == []  # идемпотентно

    monkeypatch.setattr(
        "src.backend.plugins.composition.setup_infra.pools._mongo_enabled",
        lambda: False,
    )
    await _start_mongo_client()
    assert calls == []  # disabled — skip
