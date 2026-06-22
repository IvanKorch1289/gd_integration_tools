"""Кэш результатов SQL-запросов (S38.2).

Поверх любого :class:`core.interfaces.CacheBackend` (Redis / KeyDB / Memory).
Поддерживает:
* сериализацию через pickle/json/orjson;
* инвалидацию по таблицам (reverse-index в том же бэкенде);
* TTL per-key;
* tenant-agnostic (tenant должен быть частью ``profile``).

Пример::

    cache = QueryResultCache(backend=create_cache_backend())
    result = await cache.get("main", "SELECT * FROM users WHERE id=:id", {"id": 1})
    if result is None:
        rows = await fetch_all(...)
        await cache.set("main", sql, {"id": 1}, rows, tables=["users"])
        result = rows
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pickle
from typing import Any, Protocol

from src.backend.core.interfaces.cache import CacheBackend
from src.backend.core.logging import get_logger
__all__ = (
    "QueryResultCache",
    "PickleSerializer",
    "JsonSerializer",
    "OrjsonSerializer",
    "get_default_serializer",
)

logger = get_logger("infrastructure.database.query_result_cache")


class _Serializer(Protocol):
    """Протокол сериализатора для QueryResultCache."""

    def dumps(self, obj: Any) -> bytes: ...
    def loads(self, data: bytes) -> Any: ...


class PickleSerializer:
    """Pickle serializer (default, universal)."""

    def dumps(self, obj: Any) -> bytes:
        """Serialize object to bytes.

        Args:
            obj: Object to serialize.

        Returns:
            Serialized bytes.
        """
        return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)

    def loads(self, data: bytes) -> Any:
        """Deserialize bytes to object.

        Args:
            data: Serialized bytes.

        Returns:
            Deserialized object.
        """
        # S301: pickle используется для сериализации собственных данных
        # из доверенного CacheBackend; входные данные контролируются приложением.
        return pickle.loads(data)  # noqa: S301


class JsonSerializer:
    """JSON serializer (human-readable, limited types)."""

    def dumps(self, obj: Any) -> bytes:
        """Serialize object to JSON bytes.

        Args:
            obj: Object to serialize.

        Returns:
            JSON bytes.
        """
        return json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")

    def loads(self, data: bytes) -> Any:
        """Deserialize JSON bytes to object.

        Args:
            data: JSON bytes.

        Returns:
            Deserialized object.
        """
        return json.loads(data)


class OrjsonSerializer:
    """Orjson serializer (fast, optional)."""

    def __init__(self) -> None:
        import orjson  # noqa: PLC0415

        self._mod = orjson

    def dumps(self, obj: Any) -> bytes:
        """Serialize object to orjson bytes.

        Args:
            obj: Object to serialize.

        Returns:
            Serialized bytes.
        """
        return self._mod.dumps(obj)

    def loads(self, data: bytes) -> Any:
        """Deserialize orjson bytes to object.

        Args:
            data: Serialized bytes.

        Returns:
            Deserialized object.
        """
        return self._mod.loads(data)


def get_default_serializer() -> _Serializer:
    """Возвращает лучший доступный сериализатор (orjson → json → pickle)."""
    if importlib.util.find_spec("orjson") is not None:
        return OrjsonSerializer()
    # pickle — универсальный fallback, используем его как default
    return PickleSerializer()


class QueryResultCache:
    """Кэш SQL-результатов поверх :class:`CacheBackend`.

    Args:
        backend: Реализация ``CacheBackend``.
        prefix: Префикс всех ключей (по умолчанию ``qrc``).
        default_ttl: TTL в секундах при отсутствии явного ``ttl`` в ``set()``.
        serializer: Экземпляр сериализатора; по умолчанию — ``get_default_serializer()``.
    """

    def __init__(
        self,
        backend: CacheBackend,
        *,
        prefix: str = "qrc",
        default_ttl: int = 60,
        serializer: _Serializer | None = None,
    ) -> None:
        self._backend = backend
        self._prefix = prefix
        self._default_ttl = default_ttl
        self._serializer = serializer or get_default_serializer()

    # ------------------------------------------------------------------ #
    # Key generation
    # ------------------------------------------------------------------ #
    def _make_key(
        self,
        profile: str,
        sql: str,
        params: dict[str, Any] | tuple[Any, ...] | list[Any] | None,
    ) -> str:
        normalized = " ".join(sql.split())
        param_hash = hashlib.sha256(
            json.dumps(params, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
        digest = hashlib.sha256(
            f"{profile}:{normalized}:{param_hash}".encode("utf-8")
        ).hexdigest()[:32]
        return f"{self._prefix}:{profile}:{digest}"

    def _index_key(self, profile: str, table: str) -> str:
        return f"{self._prefix}:idx:{profile}:{table}"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def get(
        self,
        profile: str,
        sql: str,
        params: dict[str, Any] | tuple[Any, ...] | list[Any] | None = None,
    ) -> Any | None:
        """Get cached query result.

        Args:
            profile: Database profile name.
            sql: SQL query string.
            params: Query parameters.

        Returns:
            Cached result or None if not found.
        """
        key = self._make_key(profile, sql, params)
        raw = await self._backend.get(key)
        if raw is None:
            return None
        try:
            return self._serializer.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qrc_deserialize_failed key=%s exc=%s", key, exc)
            await self._backend.delete(key)
            return None

    async def set(
        self,
        profile: str,
        sql: str,
        params: dict[str, Any] | tuple[Any, ...] | list[Any] | None = None,
        result: Any = None,
        *,
        ttl: int | None = None,
        tables: list[str] | None = None,
    ) -> None:
        """Сохранить результат в кэш.

        Args:
            profile: Имя профиля БД (``main``, ``oracle_legacy`` и т.д.).
            sql: SQL-запрос.
            params: Параметры запроса.
            result: Результат для кэширования.
            ttl: TTL в секундах (``None`` → ``default_ttl``).
            tables: Список затронутых таблиц для reverse-index инвалидации.
        """
        key = self._make_key(profile, sql, params)
        raw = self._serializer.dumps(result)
        await self._backend.set(key, raw, ttl=ttl or self._default_ttl)
        if tables:
            await self._index_add(profile, tables, key)

    async def invalidate_table(self, profile: str, table: str) -> int:
        """Invalidate all keys associated with a table.

        Args:
            profile: Database profile name.
            table: Table name.

        Returns:
            Number of deleted keys.
        """
        idx_key = self._index_key(profile, table)
        raw = await self._backend.get(idx_key)
        if not raw:
            return 0
        try:
            keys: list[str] = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qrc_index_corrupt", idx_key=idx_key, exc=str(exc))
            await self._backend.delete(idx_key)
            return 0

        if keys:
            await self._backend.delete(*keys)
        await self._backend.delete(idx_key)
        logger.info(
            "qrc_invalidate_table", profile=profile, table=table, count=len(keys)
        )
        return len(keys)

    async def invalidate_profile(self, profile: str) -> None:
        """Invalidate all cache entries for a profile.

        Args:
            profile: Database profile name.
        """
        pattern = f"{self._prefix}:{profile}:*"
        await self._backend.delete_pattern(pattern)
        # Также чистим индексы
        idx_pattern = f"{self._prefix}:idx:{profile}:*"
        await self._backend.delete_pattern(idx_pattern)
        logger.info("qrc_invalidate_profile", profile=profile)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    async def _index_add(self, profile: str, tables: list[str], key: str) -> None:
        for table in tables:
            idx_key = self._index_key(profile, table)
            raw = await self._backend.get(idx_key)
            try:
                keys: list[str] = json.loads(raw) if raw else []
            except Exception:  # noqa: BLE001,S110
                keys = []
            if key not in keys:
                keys.append(key)
                await self._backend.set(
                    idx_key, json.dumps(keys).encode("utf-8"), ttl=None
                )
