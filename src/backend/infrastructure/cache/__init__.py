"""
Пакет инфраструктуры кэша.

Публикует синглтон ``cache_config_registry`` для регистрации источников
кэша по всему приложению и валидатор ``CacheLayerValidator`` для проверки
отсутствия двойного кэширования (ADR-004) на старте.
"""

from src.backend.infrastructure.cache.backends import (
    KeyDBBackend,
    MemoryBackend,
    RedisBackend,
)
from src.backend.infrastructure.cache.factory import create_cache_backend
from src.backend.infrastructure.cache.invalidator import (
    CacheBackendProtocol,
    CacheInvalidator,
    InMemoryCacheBackend,
    get_cache_invalidator,
    set_cache_invalidator,
)
from src.backend.infrastructure.cache.validator import (
    CacheConfigEntry,
    CacheConfigRegistry,
    CacheDuplicationError,
    CacheLayerValidator,
)

__all__ = (
    "cache_config_registry",
    "CacheBackendProtocol",
    "CacheConfigEntry",
    "CacheConfigRegistry",
    "CacheDuplicationError",
    "CacheInvalidator",
    "CacheLayerValidator",
    "InMemoryCacheBackend",
    "MemoryBackend",
    "RedisBackend",
    "KeyDBBackend",
    "create_cache_backend",
    "get_cache_invalidator",
    "set_cache_invalidator",
)

# Глобальный реестр конфигураций кэша для всего процесса. Сервисы и
# репозитории регистрируют в нём свой ``enabled`` флаг в момент импорта.
# Валидатор вызывается в ``lifespan`` стартапа.
cache_config_registry: CacheConfigRegistry = CacheConfigRegistry()
