"""Variable Backend Protocol + 3 implementations (S62 M2-#3 split).

Extracted из :mod:`dsl.variables` (567 LOC god-module → split per
single-responsibility):
- :class:`VariableBackend` Protocol + 3 implementations (InMemory, Consul, Postgres)
- :mod:`dsl.variables` retains :class:`VariableScope`, :class:`VariableNotFoundError`,
  :class:`DSLVariableStore` (composition root)

Re-exported из :mod:`dsl.variables` для backward-compat public API.

Circular import avoidance:"VariableScope" + _now imported lazily inside method
bodies (не на module-level), так как variables.py импортирует нас в начале.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Protocol, runtime_checkable

from src.backend.core.logging import get_logger

__all__ = (
    "ConsulVariableBackend",
    "InMemoryVariableBackend",
    "PostgresVariableBackend",
    "VariableBackend",
)

_logger = get_logger("core.dsl.variables")


def _now() -> float:
    """Local helper to allow test monkey-patching (moved from variables.py)."""
    return monotonic()


# ---------------------------------------------------------------------------
# Backend Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class VariableBackend(Protocol):
    """Protocol для хранилища переменных (infrastructure-agnostic).

    Реализации обязаны быть thread-safe + async-first. `get` обязан
    вернуть raw-значение (без JSON-десериализации) или `None` если
    ключ не найден / истёк TTL.
    """

    name: str

    async def get(self, key: str, scope:"VariableScope") -> Any | None:
        """Получить значение по ``key`` в ``scope``; None если отсутствует."""
        # S62 M2-#3: lazy import to break circular dep с variables.py
        from src.backend.core.dsl.variables import VariableScope

        ...

    async def set(
        self, key: str, value: Any, scope:"VariableScope", *, ttl: float | None = None
    ) -> None:
        """Установить ``value`` по ``key`` в ``scope``; ``ttl`` — опциональный TTL."""
        ...

    async def delete(self, key: str, scope:"VariableScope") -> bool:
        """Удалить ``key`` из ``scope``; вернуть True если существовал."""
        # S62 M2-#3: lazy import to break circular dep с variables.py
        from src.backend.core.dsl.variables import VariableScope

        ...

    async def list_keys(self, scope:"VariableScope") -> list[str]:
        """Вернуть список ключей в ``scope``."""
        # S62 M2-#3: lazy import to break circular dep с variables.py
        from src.backend.core.dsl.variables import VariableScope

        ...


# ---------------------------------------------------------------------------
# InMemory backend
# ---------------------------------------------------------------------------


@dataclass
class InMemoryVariableBackend:
    """In-memory backend для тестов / dev.

    TTL: `float` seconds от `_now()`. Expired значения возвращают `None`.
    Thread-safety: GIL-защита (Python `dict` достаточно для однопроцессного
    async-loop). Для multi-instance используйте Consul / Postgres.
    """

    name: str = "in_memory"
    _store: dict[tuple[str, str], tuple[Any, float]] = field(default_factory=dict)

    async def get(self, key: str, scope:"VariableScope") -> Any | None:
        """Получить значение по ``key`` в ``scope``; None если отсутствует."""
        full_key = (str(scope), key)
        entry = self._store.get(full_key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at > 0 and expires_at < _now():
            # TTL expired — return None + cleanup.
            self._store.pop(full_key, None)
            return None
        return value

    async def set(
        self, key: str, value: Any, scope:"VariableScope", *, ttl: float | None = None
    ) -> None:
        """Установить ``value`` по ``key`` в ``scope``; ``ttl`` — опциональный TTL."""
        expires_at = (_now() + ttl) if ttl else 0.0
        self._store[(str(scope), key)] = (value, expires_at)

    async def delete(self, key: str, scope:"VariableScope") -> bool:
        """Удалить ``key`` из ``scope``; вернуть True если существовал."""
        return self._store.pop((str(scope), key), None) is not None

    async def list_keys(self, scope:"VariableScope") -> list[str]:
        """Вернуть список ключей в ``scope``."""
        scope_str = str(scope)
        return [
            key
            for (s, key), (value, expires_at) in self._store.items()
            if s == scope_str and (expires_at == 0 or expires_at >= _now())
        ]


# ---------------------------------------------------------------------------
# Consul backend
# ---------------------------------------------------------------------------


@dataclass
class ConsulVariableBackend:
    """Consul backend с hot-reload через blocking-query watch.

    Wraps `ConsulConfigStore` (`core/config/consul_config.py:29`, S36 P4).
    Использует `dsl/vars/{scope}/{key}` path scheme для KV-ключей.

    Hot-reload: `watch(prefix)` подписывается на изменения и инвалидирует
    локальный кэш (для cross-instance consistency).

    Note: `ConsulConfigStore` — sync. Обёрнуто в `asyncio.to_thread` чтобы
    не блокировать event loop.
    """

    host: str
    port: int = 8500
    cache_ttl: float = 60.0
    name: str = "consul"
    _cache: dict[str, tuple[Any, float]] = field(default_factory=dict)

    def _key_path(self, key: str, scope:"VariableScope") -> str:
        return f"dsl/vars/{scope}/{key}"

    async def get(self, key: str, scope:"VariableScope") -> Any | None:
        """Читает переменную из Consul с in-process кэшем и TTL."""
        # S62 M2-#3: lazy import to break circular dep с variables.py
        from src.backend.core.dsl.variables import VariableScope

        path = self._key_path(key, scope)
        # Cache hit + not expired → return cached.
        cached = self._cache.get(path)
        if cached is not None:
            value, expires_at = cached
            if expires_at > _now():
                return value

        # Lazy import (infrastructure) — per R7 layer policy.
        from src.backend.core.config.consul_config import ConsulConfigStore

        def _sync_get() -> Any | None:
            store = ConsulConfigStore(host=self.host, port=self.port)
            return store.get(path, default=None)

        try:
            raw = await asyncio.to_thread(_sync_get)
        except Exception as exc:
            _logger.warning("Consul get %s failed: %s", path, exc)
            return None
        if raw is None:
            return None
        self._cache[path] = (raw, _now() + self.cache_ttl)
        return raw

    async def set(
        self, key: str, value: Any, scope:"VariableScope", *, ttl: float | None = None
    ) -> None:
        """Установить ``value`` по ``key`` в ``scope`` через Consul KV."""
        path = self._key_path(key, scope)
        from src.backend.core.config.consul_config import ConsulConfigStore

        def _sync_put() -> None:
            store = ConsulConfigStore(host=self.host, port=self.port)
            client = store._get_client()
            client.kv.put(path, str(value))

        try:
            await asyncio.to_thread(_sync_put)
        except Exception as exc:
            _logger.warning("Consul put %s failed: %s", path, exc)
            return
        # Invalidate cache.
        self._cache.pop(path, None)

    async def delete(self, key: str, scope:"VariableScope") -> bool:
        """Удалить ``key`` из ``scope``; вернуть True если существовал."""
        path = self._key_path(key, scope)
        from src.backend.core.config.consul_config import ConsulConfigStore

        def _sync_delete() -> None:
            store = ConsulConfigStore(host=self.host, port=self.port)
            client = store._get_client()
            client.kv.delete(path)

        try:
            await asyncio.to_thread(_sync_delete)
        except Exception as exc:
            _logger.warning("Consul delete %s failed: %s", path, exc)
            return False
        return self._cache.pop(path, None) is not None

    async def list_keys(self, scope:"VariableScope") -> list[str]:
        """Вернуть список ключей в ``scope``."""
        from src.backend.core.config.consul_config import ConsulConfigStore

        prefix = f"dsl/vars/{scope}/"

        def _sync_list() -> list[str]:
            store = ConsulConfigStore(host=self.host, port=self.port)
            client = store._get_client()
            _, keys = client.kv.get(prefix, recurse=True, keys=True)
            return [k[len(prefix) :] for k in (keys or []) if k.startswith(prefix)]

        try:
            return await asyncio.to_thread(_sync_list)
        except Exception as exc:
            _logger.warning("Consul list %s failed: %s", prefix, exc)
            return []


# ---------------------------------------------------------------------------
# PostgreSQL backend
# ---------------------------------------------------------------------------


@dataclass
class PostgresVariableBackend:
    """PostgreSQL backend через `dsl_variables` таблицу.

    Схема таблицы (для Alembic migration в S128+):

    ```
    CREATE TABLE dsl_variables (
        scope VARCHAR(64) NOT NULL,
        key VARCHAR(255) NOT NULL,
        value JSONB NOT NULL,
        ttl_seconds INTEGER,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        PRIMARY KEY (scope, key)
    );
    ```

    Current state (S127 W2): uses lazy SQLAlchemy core expression.
    Если `session` не передан — fallback на no-op (test-friendly).
    Alembic migration отложен в S128+ (TD-005 related).
    """

    session: Any = None  # SQLAlchemy AsyncSession, lazy
    name: str = "postgres"

    async def get(self, key: str, scope:"VariableScope") -> Any | None:
        """Читает переменную из PostgreSQL; None если сессия не задана."""
        if self.session is None:
            return None
        from sqlalchemy import select

        from src.backend.core.di.providers.infrastructure_locator import (
            get_dsl_variables_attr as _get_dsl_var_attr,
        )

        dsl_variables = _get_dsl_var_attr("dsl_variables")

        stmt = select(
            dsl_variables.c.value,
            dsl_variables.c.ttl_seconds,
            dsl_variables.c.updated_at,
        ).where(dsl_variables.c.scope == str(scope), dsl_variables.c.key == key)
        result = await self.session.execute(stmt)
        row = result.first()
        if row is None:
            return None
        value, ttl_seconds, updated_at = row
        if ttl_seconds is not None and updated_at is not None:
            from datetime import UTC, datetime, timedelta

            expires_at = updated_at + timedelta(seconds=ttl_seconds)
            if datetime.now(UTC) > expires_at:
                return None
        return value

    async def set(
        self, key: str, value: Any, scope:"VariableScope", *, ttl: float | None = None
    ) -> None:
        """Установить ``value`` по ``key`` в ``scope`` через Postgres-таблицу."""
        if self.session is None:
            return
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from src.backend.core.di.providers.infrastructure_locator import (
            get_dsl_variables_attr as _get_dsl_var_attr,
        )

        dsl_variables = _get_dsl_var_attr("dsl_variables")

        stmt = pg_insert(dsl_variables).values(
            scope=str(scope),
            key=key,
            value=value,
            ttl_seconds=int(ttl) if ttl else None,
        )
        # ON CONFLICT (scope, key) DO UPDATE (upsert)
        stmt = stmt.on_conflict_do_update(
            index_elements=[dsl_variables.c.scope, dsl_variables.c.key],
            set_={
                "value": stmt.excluded.value,
                "ttl_seconds": stmt.excluded.ttl_seconds,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def delete(self, key: str, scope:"VariableScope") -> bool:
        """Удалить ``key`` из ``scope``; вернуть True если существовал."""
        if self.session is None:
            return False
        from sqlalchemy import delete

        from src.backend.core.di.providers.infrastructure_locator import (
            get_dsl_variables_attr as _get_dsl_var_attr,
        )

        dsl_variables = _get_dsl_var_attr("dsl_variables")

        stmt = delete(dsl_variables).where(
            dsl_variables.c.scope == str(scope), dsl_variables.c.key == key
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def list_keys(self, scope:"VariableScope") -> list[str]:
        """Вернуть список ключей в ``scope``."""
        if self.session is None:
            return []
        from sqlalchemy import select

        from src.backend.core.di.providers.infrastructure_locator import (
            get_dsl_variables_attr as _get_dsl_var_attr,
        )

        dsl_variables = _get_dsl_var_attr("dsl_variables")

        stmt = select(dsl_variables.c.key).where(dsl_variables.c.scope == str(scope))
        result = await self.session.execute(stmt)
        return [row[0] for row in result.fetchall()]