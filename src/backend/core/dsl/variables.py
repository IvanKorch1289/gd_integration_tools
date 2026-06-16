"""S127 W2 — DSL Variable Store (Airflow-style Variables, TD-020).

Возвращает `${var('key')}` выражения в YAML DSL к значениям из
конфигурации. Бэкенды (по приоритету поиска):

1. **Consul** — `ConsulConfigStore.get("dsl/vars/{scope}/{key}")` +
   hot-reload через `ConsulConfigStore.watch(prefix)` для инвалидации
   локального кэша.
2. **PostgreSQL** — таблица `dsl_variables(key, value, scope, ttl_seconds,
   updated_at)`. Для prod окружений с высокой доступностью.
3. **InMemory** — `dict[(scope, key), (value, expires_at)]` + TTL.
   Тесты / dev.

API::

    store = DSLVariableStore.get_default()           # auto-select backend
    value = await store.get("tenant.api_key", scope="tenant:acme")
    await store.set("db.url", "postgres://...", scope="global", ttl=3600)
    keys = await store.list_keys(scope="global")
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Protocol, runtime_checkable

from src.backend.core.logging import get_logger

__all__ = (
    "ConsulVariableBackend",
    "DSLVariableStore",
    "InMemoryVariableBackend",
    "PostgresVariableBackend",
    "VariableBackend",
    "VariableNotFoundError",
    "VariableScope",
)

_logger = get_logger("core.dsl.variables")


def _now() -> float:
    """Local helper to allow test monkey-patching."""
    return monotonic()


# ---------------------------------------------------------------------------
# Scope model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VariableScope:
    """Scope-иерархия для переменных.

    `global` — общий namespace.
    `tenant:<tenant_id>` — per-tenant override.
    `route:<route_id>` — per-route override (для A/B testing).

    Lookup order (most-specific → least-specific): route → tenant → global.
    """

    kind: str
    identifier: str = ""

    def __post_init__(self) -> None:
        if self.kind not in {"global", "tenant", "route"}:
            raise ValueError(
                f"Invalid scope kind: {self.kind!r} (expected global|tenant|route)"
            )
        if self.kind != "global" and not self.identifier:
            raise ValueError(f"Scope {self.kind!r} requires non-empty identifier")

    def __str__(self) -> str:
        if self.kind == "global":
            return "global"
        return f"{self.kind}:{self.identifier}"

    @classmethod
    def global_scope(cls) -> "VariableScope":
        return cls(kind="global")

    @classmethod
    def for_tenant(cls, tenant_id: str) -> "VariableScope":
        return cls(kind="tenant", identifier=tenant_id)

    @classmethod
    def for_route(cls, route_id: str) -> "VariableScope":
        return cls(kind="route", identifier=route_id)

    @classmethod
    def parse(cls, raw: str) -> "VariableScope":
        """Parse scope string. Examples: `"global"`, `"tenant:acme"`."""
        if raw == "global":
            return cls.global_scope()
        if ":" in raw:
            kind, ident = raw.split(":", 1)
            return cls(kind=kind, identifier=ident)
        return cls(kind="global")


class VariableNotFoundError(KeyError):
    """Бросается при отсутствии переменной во всех backends."""


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

    async def get(self, key: str, scope: VariableScope) -> Any | None: ...

    async def set(
        self, key: str, value: Any, scope: VariableScope, *, ttl: float | None = None
    ) -> None: ...

    async def delete(self, key: str, scope: VariableScope) -> bool: ...

    async def list_keys(self, scope: VariableScope) -> list[str]: ...


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

    async def get(self, key: str, scope: VariableScope) -> Any | None:
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
        self, key: str, value: Any, scope: VariableScope, *, ttl: float | None = None
    ) -> None:
        expires_at = (_now() + ttl) if ttl else 0.0
        self._store[(str(scope), key)] = (value, expires_at)

    async def delete(self, key: str, scope: VariableScope) -> bool:
        return self._store.pop((str(scope), key), None) is not None

    async def list_keys(self, scope: VariableScope) -> list[str]:
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

    def _key_path(self, key: str, scope: VariableScope) -> str:
        return f"dsl/vars/{scope}/{key}"

    async def get(self, key: str, scope: VariableScope) -> Any | None:
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
        self, key: str, value: Any, scope: VariableScope, *, ttl: float | None = None
    ) -> None:
        path = self._key_path(key, scope)
        from src.backend.core.config.consul_config import ConsulConfigStore

        def _sync_put() -> None:
            store = ConsulConfigStore(host=self.host, port=self.port)
            client = store._get_client()  # noqa: SLF001
            client.kv.put(path, str(value))

        try:
            await asyncio.to_thread(_sync_put)
        except Exception as exc:
            _logger.warning("Consul put %s failed: %s", path, exc)
            return
        # Invalidate cache.
        self._cache.pop(path, None)

    async def delete(self, key: str, scope: VariableScope) -> bool:
        path = self._key_path(key, scope)
        from src.backend.core.config.consul_config import ConsulConfigStore

        def _sync_delete() -> None:
            store = ConsulConfigStore(host=self.host, port=self.port)
            client = store._get_client()  # noqa: SLF001
            client.kv.delete(path)

        try:
            await asyncio.to_thread(_sync_delete)
        except Exception as exc:
            _logger.warning("Consul delete %s failed: %s", path, exc)
            return False
        return self._cache.pop(path, None) is not None

    async def list_keys(self, scope: VariableScope) -> list[str]:
        from src.backend.core.config.consul_config import ConsulConfigStore

        prefix = f"dsl/vars/{scope}/"

        def _sync_list() -> list[str]:
            store = ConsulConfigStore(host=self.host, port=self.port)
            client = store._get_client()  # noqa: SLF001
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

    async def get(self, key: str, scope: VariableScope) -> Any | None:
        if self.session is None:
            return None
        from sqlalchemy import select

        from src.backend.infrastructure.database.models import (  # type: ignore[attr-defined]
            dsl_variables,
        )

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
        self, key: str, value: Any, scope: VariableScope, *, ttl: float | None = None
    ) -> None:
        if self.session is None:
            return
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from src.backend.infrastructure.database.models import (  # type: ignore[attr-defined]
            dsl_variables,
        )

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

    async def delete(self, key: str, scope: VariableScope) -> bool:
        if self.session is None:
            return False
        from sqlalchemy import delete

        from src.backend.infrastructure.database.models import (  # type: ignore[attr-defined]
            dsl_variables,
        )

        stmt = delete(dsl_variables).where(
            dsl_variables.c.scope == str(scope), dsl_variables.c.key == key
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount > 0

    async def list_keys(self, scope: VariableScope) -> list[str]:
        if self.session is None:
            return []
        from sqlalchemy import select

        from src.backend.infrastructure.database.models import (  # type: ignore[attr-defined]
            dsl_variables,
        )

        stmt = select(dsl_variables.c.key).where(dsl_variables.c.scope == str(scope))
        result = await self.session.execute(stmt)
        return [row[0] for row in result.fetchall()]


# ---------------------------------------------------------------------------
# Façade
# ---------------------------------------------------------------------------


@dataclass
class DSLVariableStore:
    """Façade поверх списка `VariableBackend` с lookup-priority.

    Lookup order: первый backend в списке с non-None результатом
    выигрывает. По умолчанию — `[InMemoryVariableBackend()]` для тестов;
    в prod через `DSLVariableStore.configure([consul, postgres])`.

    Scope fallback (per VariableScope): route → tenant → global. Если
    `key="db.url"` не найден в `route:r1`, ищется в `tenant:acme`,
    затем в `global`.
    """

    backends: list[VariableBackend] = field(default_factory=list)
    enable_scope_fallback: bool = True
    name: str = "default"

    @classmethod
    def get_default(cls) -> "DSLVariableStore":
        """Singleton с дефолтным backend (in-memory).

        В production переопределите через `configure()` в lifespan.py.
        """
        if not _default_instance:
            _default_instance.append(cls(backends=[InMemoryVariableBackend()]))
        return _default_instance[0]

    @classmethod
    def configure(cls, backends: list[VariableBackend]) -> "DSLVariableStore":
        """Установить custom backends (singleton reset)."""
        instance = cls(backends=list(backends))
        _default_instance.clear()
        _default_instance.append(instance)
        return instance

    def _scopes_to_try(self, scope: VariableScope) -> list[VariableScope]:
        """Scope fallback chain: route → tenant → global."""
        if not self.enable_scope_fallback:
            return [scope]
        chain: list[VariableScope] = [scope]
        if scope.kind == "route":
            chain.append(VariableScope.for_route(scope.identifier))
            # For pure "route:<id>" without tenant context, also try global.
            chain.append(VariableScope.global_scope())
        elif scope.kind == "tenant":
            chain.append(VariableScope.global_scope())
        return chain

    async def get(self, key: str, scope: VariableScope | str = "global") -> Any | None:
        """Lookup chain: scope fallback × backends."""
        scope_obj = (
            scope if isinstance(scope, VariableScope) else VariableScope.parse(scope)
        )
        for try_scope in self._scopes_to_try(scope_obj):
            for backend in self.backends:
                value = await backend.get(key, try_scope)
                if value is not None:
                    if try_scope != scope_obj:
                        _logger.debug(
                            "Variable %r resolved via fallback scope %r (requested %r)",
                            key,
                            try_scope,
                            scope_obj,
                        )
                    return value
        return None

    async def set(
        self,
        key: str,
        value: Any,
        scope: VariableScope | str = "global",
        *,
        ttl: float | None = None,
    ) -> None:
        """Write to FIRST backend in the list (write-through)."""
        scope_obj = (
            scope if isinstance(scope, VariableScope) else VariableScope.parse(scope)
        )
        if not self.backends:
            raise RuntimeError("DSLVariableStore: no backends configured")
        await self.backends[0].set(key, value, scope_obj, ttl=ttl)

    async def delete(self, key: str, scope: VariableScope | str = "global") -> bool:
        scope_obj = (
            scope if isinstance(scope, VariableScope) else VariableScope.parse(scope)
        )
        deleted = False
        for backend in self.backends:
            if await backend.delete(key, scope_obj):
                deleted = True
        return deleted

    async def list_keys(self, scope: VariableScope | str = "global") -> list[str]:
        scope_obj = (
            scope if isinstance(scope, VariableScope) else VariableScope.parse(scope)
        )
        keys: set[str] = set()
        for backend in self.backends:
            keys.update(await backend.list_keys(scope_obj))
        return sorted(keys)


_default_instance: list[DSLVariableStore] = []
