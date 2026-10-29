"""Wave 18 (ADR-0391): лимит размера значения в ``UnifiedCacheFacade``.

Дефект 7 (medium): ``set_ns`` / ``CacheWriteProcessor`` писали в Redis
произвольный orjson-дамп — без лимита размера. Один большой ответ LLM
(десятки МБ) забивал Redis.

Контракт: значение больше ``cache_settings.max_value_bytes`` → понятная
ошибка ``ValueError`` (значение не пишется ни в один tier).
"""

from __future__ import annotations

import pytest

from src.backend.core.config.services.cache import cache_settings
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.services.cache.facade import UnifiedCacheFacade


@pytest.fixture()
def facade() -> UnifiedCacheFacade:
    """Фасад только с memory-tier (primary достаточно для проверки лимита)."""
    return UnifiedCacheFacade(primary=MemoryBackend(maxsize=10))


@pytest.mark.asyncio
async def test_set_ns_rejects_oversized_value(facade: UnifiedCacheFacade) -> None:
    """Значение больше лимита → ValueError с понятным сообщением."""
    oversized = b"x" * (cache_settings.max_value_bytes + 1)

    with pytest.raises(ValueError, match="max_value_bytes"):
        await facade.set_ns("k", oversized)


@pytest.mark.asyncio
async def test_set_ns_rejects_oversized_value_via_abc(
    facade: UnifiedCacheFacade,
) -> None:
    """ABC-метод ``set`` тоже защищён лимитом."""
    oversized = b"x" * (cache_settings.max_value_bytes + 1)

    with pytest.raises(ValueError, match="max_value_bytes"):
        await facade.set("k", oversized)


@pytest.mark.asyncio
async def test_set_ns_allows_value_at_limit(facade: UnifiedCacheFacade) -> None:
    """Значение ровно на границе лимита — записывается."""
    at_limit = b"x" * cache_settings.max_value_bytes

    await facade.set_ns("k", at_limit)

    result = await facade.get_ns("k")
    assert result.hit is True
    assert result.value == at_limit


@pytest.mark.asyncio
async def test_oversized_value_is_not_written_to_memory(
    facade: UnifiedCacheFacade,
) -> None:
    """Превышение лимита не оставляет мусор в memory-tier."""
    oversized = b"x" * (cache_settings.max_value_bytes + 1)

    with pytest.raises(ValueError):
        await facade.set_ns("k", oversized)

    assert (await facade.get_ns("k")).hit is False


@pytest.mark.unit
def test_max_value_bytes_setting_is_positive() -> None:
    """Лимит размера значения — положительная константа."""
    assert cache_settings.max_value_bytes > 0
