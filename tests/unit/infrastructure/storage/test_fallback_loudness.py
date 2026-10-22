"""Regression tests для fail-open поведения ``FallbackObjectStorage``.

Cycle 171 audit (CRITICAL-01). До фикса дефолт ``fallback_exceptions`` был
``(Exception,)``, из-за чего:

* любой баг вызывающего кода (``ValueError``/``TypeError``) маскировался под
  «успешную» запись в secondary — данные оказывались на временном носителе, а
  дефект оставался невидимым;
* write-fallback логировался на уровне WARNING, без метрики и без алерта,
  хотя именно он означает риск потери данных при eviction пода;
* не было способа отличить объекты, ушедшие на pod-local диск, от обычных
  локальных файлов — нечего было перезаливать при восстановлении primary.

Здесь фиксируется инвертированное поведение:

* ``ValueError`` **пробрасывается** (fail-closed для ошибок кода);
* отказ инфраструктуры по-прежнему деградирует на secondary (fail-open для
  доступности), но попадает в карантин и логируется на ERROR;
* read-деградация остаётся WARNING и не попадает в карантин.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.errors import ServiceError
from src.backend.infrastructure.storage.fallback import (
    DEFAULT_FALLBACK_EXCEPTIONS,
    FallbackObjectStorage,
)


def _chain(primary_exc: BaseException, *, name: str = "test.chain") -> Any:
    """FallbackObjectStorage, где primary падает с ``primary_exc``."""
    primary = MagicMock()
    primary.supports_presigned = MagicMock(return_value=True)
    primary.upload = AsyncMock(side_effect=primary_exc)
    primary.download = AsyncMock(side_effect=primary_exc)
    primary.delete = AsyncMock(side_effect=primary_exc)
    primary.exists = AsyncMock(side_effect=primary_exc)
    primary.list_keys = AsyncMock(side_effect=primary_exc)
    primary.presigned_url = AsyncMock(side_effect=primary_exc)

    secondary = MagicMock()
    secondary.upload = AsyncMock(return_value="secondary://key")
    secondary.download = AsyncMock(return_value=b"from-secondary")
    secondary.delete = AsyncMock(return_value=None)
    secondary.exists = AsyncMock(return_value=True)
    secondary.list_keys = AsyncMock(return_value=["a"])
    secondary.presigned_url = AsyncMock(return_value="file:///a")

    return FallbackObjectStorage(primary, secondary, name=name)


# ── default exception set ────────────────────────────────────────────────


def test_default_set_excludes_bare_exception() -> None:
    """Дефолт больше не ``(Exception,)`` — иначе баги кода снова маскируются."""
    assert Exception not in DEFAULT_FALLBACK_EXCEPTIONS
    assert DEFAULT_FALLBACK_EXCEPTIONS == (ServiceError, OSError)


@pytest.mark.parametrize("exc", [ValueError, TypeError, KeyError, AttributeError])
@pytest.mark.asyncio
async def test_programming_error_is_not_swallowed(exc: type[Exception]) -> None:
    """Баг вызывающего кода обязан проброситься, а не записаться на диск."""
    storage = _chain(exc())

    with pytest.raises(exc):
        await storage.upload("uploads/report.pdf", b"payload")

    assert storage.quarantined == []
    assert storage.fallback_count["upload"] == 0


@pytest.mark.parametrize(
    "exc",
    [
        ServiceError("s3 unreachable"),
        ConnectionError("refused"),
        TimeoutError("timed out"),
        OSError("socket died"),
    ],
)
@pytest.mark.asyncio
async def test_infrastructure_failure_still_degrades(exc: BaseException) -> None:
    """Отказ инфраструктуры по-прежнему деградирует на secondary (доступность)."""
    storage = _chain(exc)

    result = await storage.upload("uploads/report.pdf", b"payload")

    assert result == "secondary://key"
    assert storage.fallback_count["upload"] == 1


# ── loudness + quarantine for writes ─────────────────────────────────────


@pytest.mark.asyncio
async def test_write_fallback_is_quarantined() -> None:
    """Объект, ушедший на временный носитель, должен быть найден для re-upload."""
    storage = _chain(ServiceError("s3 unreachable"))

    await storage.upload("uploads/contract.pdf", b"contract-bytes")

    entries = storage.quarantined
    assert len(entries) == 1
    assert entries[0].key == "uploads/contract.pdf"
    assert entries[0].operation == "upload"
    assert entries[0].size == len(b"contract-bytes")


@pytest.mark.asyncio
async def test_read_fallback_is_not_quarantined() -> None:
    """Деградация чтения — не потеря данных, карантин не растёт."""
    storage = _chain(ServiceError("s3 unreachable"))

    assert await storage.download("uploads/x.bin") == b"from-secondary"

    assert storage.quarantined == []
    assert storage.fallback_count["download"] == 1


@pytest.mark.asyncio
async def test_drain_quarantine_clears_entries() -> None:
    """Re-upload-воркер забирает записи; повторный drain пуст."""
    storage = _chain(ServiceError("down"))

    await storage.upload("uploads/a.bin", b"a")
    await storage.upload("uploads/b.bin", b"b")

    drained = storage.drain_quarantine()
    assert [e.key for e in drained] == ["uploads/a.bin", "uploads/b.bin"]
    assert storage.quarantined == []
    assert storage.drain_quarantine() == []


@pytest.mark.asyncio
async def test_quarantine_is_bounded() -> None:
    """Длинная деградация не съедает память процесса."""
    primary = MagicMock()
    primary.upload = AsyncMock(side_effect=ServiceError("down"))
    secondary = MagicMock()
    secondary.upload = AsyncMock(return_value="secondary://key")

    storage = FallbackObjectStorage(
        primary, secondary, name="bounded", quarantine_max=3
    )
    for i in range(10):
        await storage.upload(f"uploads/{i}.bin", b"x")

    assert len(storage.quarantined) == 3
    # Вытеснены самые старые.
    assert [e.key for e in storage.quarantined] == [
        "uploads/7.bin",
        "uploads/8.bin",
        "uploads/9.bin",
    ]


@pytest.mark.asyncio
async def test_quarantine_can_be_disabled() -> None:
    """Явный opt-out для потребителей, которым реестр не нужен."""
    primary = MagicMock()
    primary.upload = AsyncMock(side_effect=ServiceError("down"))
    secondary = MagicMock()
    secondary.upload = AsyncMock(return_value="secondary://key")

    storage = FallbackObjectStorage(primary, secondary, quarantine=False)
    await storage.upload("uploads/a.bin", b"x")

    assert storage.quarantined == []
    assert storage.fallback_count["upload"] == 1


# ── delete is a write too ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_fallback_is_counted_and_logged_as_write() -> None:
    """delete входит в ``_WRITE_OPS``: расхождение состояний — тоже потеря."""
    storage = _chain(ServiceError("down"))

    await storage.delete("uploads/gone.bin")

    assert storage.fallback_count["delete"] == 1
    assert [e.operation for e in storage.quarantined] == ["delete"]