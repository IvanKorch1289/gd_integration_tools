"""Unit-тесты PybreakerAdapter scaffold с state-persistence.

Wave: ``[wave:s16/k2-w4-pybreaker-replace]`` — DoD-9 Sprint 16.

Покрытие:
* call() пропускает успех / открывает breaker после fail_max.
* state переходы closed → open → (restore) → half_open.
* storage.save вызывается при каждом изменении state.
* restore() корректно восстанавливает state из storage.
"""

from __future__ import annotations

import pytest

from src.backend.core.utils.pybreaker_adapter import (
    BreakerState,
    FakeBreakerStateStorage,
    InMemoryPybreakerAdapter,
    PybreakerAdapter,
    make_pybreaker_adapter,
)


@pytest.mark.asyncio
async def test_adapter_call_success_keeps_closed() -> None:
    """Успешные вызовы не меняют state=closed."""
    adapter = InMemoryPybreakerAdapter(name="ok", fail_max=3)

    async def ok() -> str:
        return "ok"

    for _ in range(5):
        result = await adapter.call(ok)
        assert result == "ok"
    assert adapter.state == "closed"
    assert adapter.failure_count == 0


@pytest.mark.asyncio
async def test_adapter_opens_after_fail_max() -> None:
    """После fail_max отказов state → open; следующий вызов отвергается."""
    adapter = InMemoryPybreakerAdapter(name="bad", fail_max=2)

    async def bad() -> None:
        raise IOError("upstream down")

    for _ in range(2):
        with pytest.raises(IOError):
            await adapter.call(bad)

    assert adapter.state == "open"
    # Следующий вызов отвергается без вызова fn.
    with pytest.raises(RuntimeError, match="circuit_open"):
        await adapter.call(bad)


@pytest.mark.asyncio
async def test_adapter_persists_state_on_failure() -> None:
    """При каждом отказе storage.save вызывается с текущим state."""
    storage = FakeBreakerStateStorage()
    adapter = InMemoryPybreakerAdapter(name="t", fail_max=3, storage=storage)

    async def bad() -> None:
        raise ValueError("fail")

    with pytest.raises(ValueError):
        await adapter.call(bad)

    saved = await storage.load("t")
    assert saved is not None
    assert saved.fail_counter == 1
    assert saved.state == "closed"  # ещё не достигли fail_max


@pytest.mark.asyncio
async def test_adapter_restore_from_storage() -> None:
    """restore() восстанавливает state из storage (DoD-9 restart test)."""
    storage = FakeBreakerStateStorage()
    await storage.save(
        BreakerState(
            name="restored",
            state="open",
            fail_counter=7,
            last_failure_at_iso="2026-05-21T10:00:00+00:00",
        )
    )
    adapter = InMemoryPybreakerAdapter(name="restored", storage=storage)
    # До restore — defaults.
    assert adapter.state == "closed"
    await adapter.restore()
    assert adapter.state == "open"
    assert adapter.failure_count == 7


@pytest.mark.asyncio
async def test_adapter_restore_missing_keeps_defaults() -> None:
    """Если в storage нет ключа — defaults сохраняются."""
    storage = FakeBreakerStateStorage()
    adapter = InMemoryPybreakerAdapter(name="missing", storage=storage)
    await adapter.restore()
    assert adapter.state == "closed"
    assert adapter.failure_count == 0


@pytest.mark.asyncio
async def test_adapter_success_resets_counter() -> None:
    """Успешный вызов после нескольких отказов сбрасывает counter."""
    adapter = InMemoryPybreakerAdapter(name="mixed", fail_max=5)

    async def bad() -> None:
        raise IOError("intermittent")

    async def ok() -> str:
        return "ok"

    with pytest.raises(IOError):
        await adapter.call(bad)
    with pytest.raises(IOError):
        await adapter.call(bad)
    assert adapter.failure_count == 2

    await adapter.call(ok)
    assert adapter.failure_count == 0
    assert adapter.state == "closed"


@pytest.mark.asyncio
async def test_fake_storage_implements_protocol() -> None:
    """FakeBreakerStateStorage структурно соответствует Protocol."""
    storage = FakeBreakerStateStorage()
    from src.backend.core.utils.pybreaker_adapter import BreakerStateStorage

    assert isinstance(storage, BreakerStateStorage)


@pytest.mark.asyncio
async def test_adapter_implements_protocol() -> None:
    """InMemoryPybreakerAdapter структурно соответствует [PybreakerAdapter]."""
    adapter = InMemoryPybreakerAdapter(name="p")
    assert isinstance(adapter, PybreakerAdapter)


@pytest.mark.asyncio
async def test_dod9_restart_scenario_fail_max_5() -> None:
    """DoD-9 acceptance: open-state восстанавливается из storage после рестарта.

    Sprint 16 K2 W4: имитируется breaker, поднявший fail_max=5 и упавший
    в state=open ДО рестарта. Новый adapter с тем же storage и тем же
    именем после ``restore()`` должен начать работу сразу в open
    (а не в closed) — иначе persistence не достигнута.
    """
    storage = FakeBreakerStateStorage()
    await storage.save(
        BreakerState(
            name="t",
            state="open",
            fail_counter=5,
            last_failure_at_iso="2026-05-21T12:00:00+00:00",
        )
    )
    adapter = InMemoryPybreakerAdapter(name="t", fail_max=5, storage=storage)
    assert adapter.state == "closed"  # до restore — defaults

    await adapter.restore()

    assert adapter.state == "open"
    assert adapter.failure_count == 5
    # Дополнительный вызов отвергается — circuit действительно открыт.
    async def upstream() -> str:
        return "should_not_run"

    with pytest.raises(RuntimeError, match="circuit_open"):
        await adapter.call(upstream)


@pytest.mark.asyncio
async def test_make_pybreaker_adapter_returns_protocol() -> None:
    """Factory ``make_pybreaker_adapter`` возвращает совместимый Protocol."""
    storage = FakeBreakerStateStorage()
    adapter = make_pybreaker_adapter(
        name="factory", fail_max=3, reset_timeout=15.0, storage=storage
    )

    assert isinstance(adapter, PybreakerAdapter)
    assert adapter.state == "closed"
    assert adapter.failure_count == 0


def test_v11_pybreaker_enabled_default_off() -> None:
    """Feature-flag ``v11.pybreaker_enabled`` по умолчанию False (Sprint 16 K2 W4)."""
    from src.backend.core.config.v11 import V11Settings

    flags = V11Settings()
    assert flags.pybreaker_enabled is False
