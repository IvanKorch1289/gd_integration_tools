"""Регрессия: tenant-изоляция erasure в RedisErasureAdapter (audit 30.09.2026).

Найдено при попытке опровергнуть собственный результат: прогон
``tests/unit/core/privacy/`` вскрыл, что A/B-тест
``test_runtime_a_b_erasure_contract.py`` проходит только потому, что
использует tenant-квалифицированные ``subject_id`` (``user:tenant_A:42``).
Такой ``subject_id`` маскирует дефект, а не проверяет его.

Корень: ``_build_scan_patterns`` строил список как
``(*DEFAULT_PREFIXES, "tenant:<id>:")`` — глобальные паттерны
``*user:<subject_id>*`` оставались активными. При не-tenant-квалифицированном
``subject_id`` (например ``"42"``, именно такой пример документирован в
``_orchestrator.execute``) SCAN матчил ключи ЧУЖИХ tenant'ов, и UNLINK их
удалял.

Воспроизведение ДО фикса (subject_id="42", tenant_id="tenant_A"):
    status=SUCCESS records_affected=5
    CROSS-TENANT DELETED: tenant:tenant_B:user:user:42
    CROSS-TENANT DELETED: tenant:tenant_B:session:user:42
    CROSS-TENANT DELETED: tenant:tenant_B:auth:user:42

Контракт после фикса:
- при разрешённом tenant сканируются ТОЛЬКО ключи этого tenant'а;
- без tenant и без ``allow_global_scan=True`` — fail-closed (FAILED, 0 удалений);
- глобальный скан legacy-ключей — только через явный opt-in.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.backend.core.privacy.delete_data_subject._redis import RedisErasureAdapter
from src.backend.core.privacy.delete_data_subject._types import (
    ErasureResultStatus,
    ErasureStrategy,
)


@dataclass
class _FakeRedis:
    """Fake redis с async SCAN + UNLINK (glob-семантика как у реального Redis)."""

    store: dict[str, bytes] = field(default_factory=dict)
    scan_log: list[str] = field(default_factory=list)

    async def scan(
        self, *, cursor: int, match: str, count: int
    ) -> tuple[int, list[bytes]]:
        """Имитация ``SCAN MATCH`` — Redis glob: ``*`` матчит любые символы."""
        self.scan_log.append(match)
        keys = [k.encode() for k in self.store if fnmatch.fnmatchcase(k, match)]
        return (0, keys)

    async def unlink(self, *keys: bytes | str) -> int:
        removed = 0
        for key in keys:
            name = key.decode() if isinstance(key, bytes) else key
            if name in self.store:
                del self.store[name]
                removed += 1
        return removed


def _multitenant_store() -> dict[str, bytes]:
    """Ключи трёх tenant'ов с одинаковым subject id ``42``."""
    return {
        # tenant_A — цель удаления
        "tenant:tenant_A:user:42": b'{"name":"Alice"}',
        "tenant:tenant_A:session:42": b'{"token":"a"}',
        "tenant:tenant_A:cache:user:42": b'{"role":"admin"}',
        # tenant_B — НЕ трогать
        "tenant:tenant_B:user:42": b'{"name":"Bob"}',
        "tenant:tenant_B:session:42": b'{"token":"b"}',
        "tenant:tenant_B:auth:42": b'{"jwt":"b"}',
        # tenant_C — НЕ трогать
        "tenant:tenant_C:user:42": b'{"name":"Carol"}',
        # Соседний subject того же tenant_A — НЕ трогать
        "tenant:tenant_A:user:43": b'{"name":"Dave"}',
    }


async def _run(adapter: RedisErasureAdapter, subject_id: str = "42") -> Any:
    """Выполнить erasure с явным tenant_id."""
    return await adapter.execute(
        subject_id=subject_id,
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="corr-tenant-isolation",
        tenant_id="tenant_A",
    )


@pytest.mark.asyncio
async def test_bare_subject_id_never_deletes_other_tenant_keys() -> None:
    """ЯДРО РЕГРЕССИИ: subject_id без tenant-квалификации не трогает чужих.

    Именно этот сценарий проходил зелёным до фикса, стирая ключи
    ``tenant_B`` и ``tenant_C``.
    """
    fake = _FakeRedis(store=_multitenant_store())
    adapter = RedisErasureAdapter(redis_client=fake)

    result = await _run(adapter, subject_id="42")

    assert result.status == ErasureResultStatus.SUCCESS

    # Ключи других tenant'ов выжили.
    for key in (
        "tenant:tenant_B:user:42",
        "tenant:tenant_B:session:42",
        "tenant:tenant_B:auth:42",
        "tenant:tenant_C:user:42",
    ):
        assert key in fake.store, f"cross-tenant key was deleted: {key}"

    # Соседний subject того же tenant_A выжил.
    assert "tenant:tenant_A:user:43" in fake.store

    # Свои ключи tenant_A стёрты.
    assert "tenant:tenant_A:user:42" not in fake.store
    assert "tenant:tenant_A:session:42" not in fake.store
    assert "tenant:tenant_A:cache:user:42" not in fake.store


@pytest.mark.asyncio
async def test_no_tenant_context_fails_closed() -> None:
    """Без tenant и без opt-in — FAILED, ноль удалений, SCAN не вызывается."""
    from src.backend.core.tenancy import _current

    fake = _FakeRedis(store=_multitenant_store())
    adapter = RedisErasureAdapter(redis_client=fake)

    try:
        _current.set(None)
    except Exception:  # pragma: no cover — sentinel может отсутствовать
        pass

    result = await adapter.execute(
        subject_id="42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="corr-fail-closed",
    )

    assert result.status == ErasureResultStatus.FAILED
    assert result.records_affected == 0
    assert "allow_global_scan" in (result.error or "")
    assert len(fake.store) == len(_multitenant_store()), "что-то было удалено"
    assert fake.scan_log == [], "SCAN не должен вызываться при fail-closed"


@pytest.mark.asyncio
async def test_allow_global_scan_optin_erases_legacy_keys() -> None:
    """Явный opt-in сохраняет стирание legacy-ключей без tenant-префикса."""
    fake = _FakeRedis(
        store={
            "user:42:profile": b'{"name":"Alice"}',
            "session:42:token": b'{"token":"a"}',
            "user:43:profile": b'{"name":"Dave"}',
        }
    )
    adapter = RedisErasureAdapter(redis_client=fake, allow_global_scan=True)

    result = await _run(adapter, subject_id="42")

    assert result.status == ErasureResultStatus.SUCCESS
    assert "user:42:profile" not in fake.store
    assert "session:42:token" not in fake.store
    assert "user:43:profile" in fake.store


@pytest.mark.asyncio
async def test_allow_global_scan_optin_without_tenant_erases_global() -> None:
    """Opt-in без tenant — legacy-поведение, но только явно запрошенное."""
    from src.backend.core.tenancy import _current

    fake = _FakeRedis(
        store={"user:42:profile": b'{"name":"Alice"}', "user:43:profile": b"x"}
    )
    adapter = RedisErasureAdapter(redis_client=fake, allow_global_scan=True)

    try:
        _current.set(None)
    except Exception:  # pragma: no cover
        pass

    result = await adapter.execute(
        subject_id="42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="corr-optin-global",
    )

    assert result.status == ErasureResultStatus.SUCCESS
    assert "user:42:profile" not in fake.store
    assert "user:43:profile" in fake.store


def test_scan_patterns_are_tenant_scoped_by_default() -> None:
    """Контракт паттернов: при tenant — только tenant-scoped, глобальных нет."""
    adapter = RedisErasureAdapter(redis_client=None)

    patterns = adapter._build_scan_patterns("42", "tenant_A")

    assert patterns, "должен быть хотя бы один паттерн"
    assert all("tenant:tenant_A:" in p for p in patterns), (
        f"при разрешённом tenant все паттерны обязаны быть tenant-scoped: {patterns}"
    )
    # Глобальные паттерны не просочились.
    assert not any(p == "*user:42*" for p in patterns), patterns


def test_scan_patterns_include_global_only_with_optin() -> None:
    """С opt-in к tenant-scoped паттернам добавляются и глобальные."""
    adapter = RedisErasureAdapter(redis_client=None, allow_global_scan=True)

    patterns = adapter._build_scan_patterns("42", "tenant_A")

    assert "*tenant:tenant_A:user:42*" in patterns
    assert "*user:42*" in patterns
    assert len(patterns) == len(set(patterns)), "дубликаты паттернов недопустимы"
