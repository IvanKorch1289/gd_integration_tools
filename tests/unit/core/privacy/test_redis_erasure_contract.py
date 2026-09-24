"""Contract tests: RedisErasureAdapter (privacy lifecycle, v5 P0 #2).

Per PRIVACY_REDIS_INVESTIGATION_2026-09-24 §4: контракт-тест
«insert + erase + verify absence» отсутствовал. Здесь фиксируется
ФАКТИЧЕСКОЕ поведение адаптера (SCAN + UNLINK по subject_id) на fake-клиенте
без живого Redis:

1. Erase удаляет subject-ключи во всех префиксах; чужие ключи выживают.
2. AdapterResult: SUCCESS + records_affected = число удалённых ключей.
3. Без redis_client → SKIPPED (error="redis_client not configured").
4. Исключение клиента → FAILED с типом ошибки.

Tenant-awareness (TenantContext/префикс-скоп) — deferred под privacy-ADR
(см. KNOWN_ISSUES #3): тест фиксирует текущий контракт, не будущий.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.privacy.delete_data_subject._redis import RedisErasureAdapter
from src.backend.core.privacy.delete_data_subject._types import (
    ErasureResultStatus,
    ErasureStrategy,
)


class FakeRedis:
    """Минимальный async-клиент: dict + SCAN по substring + UNLINK."""

    def __init__(self, keys: list[str] | None = None) -> None:
        self.keys: dict[str, str] = {k: "v" for k in keys or []}
        self.unlink_calls: list[tuple[str, ...]] = []
        self.fail_on_scan = False

    async def scan(
        self, cursor: int, match: str = "*", count: int = 100
    ) -> tuple[int, list[str]]:
        if self.fail_on_scan:
            raise RuntimeError("scan exploded")
        # Простейшая glob-семантика: '*' → любой префикс/суффикс.
        pattern = re_glob(match)
        matched = [k for k in self.keys if pattern.fullmatch(k)]
        return 0, matched

    async def unlink(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self.keys:
                del self.keys[k]
                deleted += 1
        self.unlink_calls.append(tuple(keys))
        return deleted


def re_glob(match: str) -> Any:
    """Конвертирует redis-glob 'a*b' → regex для fake-клиента."""
    import re

    return re.compile("^" + re.escape(match).replace(r"\*", ".*") + "$")


def _keys() -> list[str]:
    return [
        "user:42:profile",
        "session:42:token",
        "cache:user:42:last_search",
        "tenant:42:settings",
        "user:43:profile",  # другой subject — должен выжить
        "cache:user:43:cart",
    ]


@pytest.mark.asyncio
async def test_erase_removes_subject_keys_across_prefixes() -> None:
    """Erase удаляет все ключи с subject_id во всех префиксах."""
    fake = FakeRedis(_keys())
    adapter = RedisErasureAdapter(redis_client=fake)

    result = await adapter.execute(
        subject_id="42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="corr-1",
    )

    assert result.status == ErasureResultStatus.SUCCESS
    assert result.records_affected == 4
    # Subject-ключи удалены (verify absence).
    for k in ("user:42:profile", "session:42:token", "cache:user:42:last_search"):
        assert k not in fake.keys
    # Чужой subject выжил.
    assert "user:43:profile" in fake.keys
    assert "cache:user:43:cart" in fake.keys


@pytest.mark.asyncio
async def test_erase_no_matching_keys_zero_deleted() -> None:
    """Нет ключей субъекта → SUCCESS с records_affected=0."""
    fake = FakeRedis(["user:43:profile"])
    adapter = RedisErasureAdapter(redis_client=fake)

    result = await adapter.execute(
        subject_id="999",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="corr-2",
    )

    assert result.status == ErasureResultStatus.SUCCESS
    assert result.records_affected == 0


@pytest.mark.asyncio
async def test_no_client_skipped() -> None:
    """Без redis_client → SKIPPED с ошибкой конфигурации."""
    adapter = RedisErasureAdapter(redis_client=None)

    result = await adapter.execute(
        subject_id="42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="corr-3",
    )

    assert result.status == ErasureResultStatus.SKIPPED
    assert result.error == "redis_client not configured"


@pytest.mark.asyncio
async def test_client_exception_failed() -> None:
    """Падение клиента → FAILED с типом исключения (не бросает наружу)."""
    fake = FakeRedis(_keys())
    fake.fail_on_scan = True
    adapter = RedisErasureAdapter(redis_client=fake)

    result = await adapter.execute(
        subject_id="42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="corr-4",
    )

    assert result.status == ErasureResultStatus.FAILED
    assert "RuntimeError" in (result.error or "")


@pytest.mark.asyncio
async def test_custom_prefixes_narrow_scope() -> None:
    """Кастомные префиксы сужают SCAN (не задевают другие префиксы)."""
    fake = FakeRedis(_keys())
    adapter = RedisErasureAdapter(redis_client=fake, key_prefixes=("cache:user:",))

    result = await adapter.execute(
        subject_id="42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="corr-5",
    )

    assert result.records_affected == 1
    assert "user:42:profile" in fake.keys  # вне кастомного префикса — выжил
    assert "cache:user:42:last_search" not in fake.keys
