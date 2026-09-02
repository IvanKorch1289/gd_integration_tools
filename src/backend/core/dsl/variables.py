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
from typing import Any

from src.backend.core.logging import get_logger

# S62 M2-#3: VariableBackend Protocol + 3 implementations
# (InMemory, Consul, Postgres) extracted в :mod:`variable_backend`.
# Re-exported ниже для backward-compat public API.
from src.backend.core.dsl.variable_backend import (  # noqa: E402,F401
    ConsulVariableBackend,
    InMemoryVariableBackend,
    PostgresVariableBackend,
    VariableBackend,
)

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
    def global_scope(cls) -> VariableScope:
        """Вернуть singleton scope 'global' (process-wide)."""
        return cls(kind="global")

    @classmethod
    def for_tenant(cls, tenant_id: str) -> VariableScope:
        """Вернуть scope, изолированный по tenant_id."""
        return cls(kind="tenant", identifier=tenant_id)

    @classmethod
    def for_route(cls, route_id: str) -> VariableScope:
        """Вернуть scope, изолированный по route_id."""
        return cls(kind="route", identifier=route_id)

    @classmethod
    def parse(cls, raw: str) -> VariableScope:
        """Parse scope string. Examples: `"global"`, `"tenant:acme"`.

        Raises:
            ValueError: если ``raw`` имеет неизвестный формат (например,
                `"hello-world"` без `:`). Pre-fix: silently fall back к
                global scope, что могло замаскировать misconfig в YAML.

        """
        if raw == "global":
            return cls.global_scope()
        if ":" in raw:
            kind, ident = raw.split(":", 1)
            if not kind or not ident:
                raise ValueError(
                    f"Invalid VariableScope: {raw!r} (both kind and identifier required)"
                )
            return cls(kind=kind, identifier=ident)
        raise ValueError(
            f"Invalid VariableScope: {raw!r} (expected 'global' or 'kind:identifier')"
        )


class VariableNotFoundError(KeyError):
    """Reserved exception class for missing variables across all backends.

    Currently NOT raised by the implementation (which returns ``None`` for
    missing keys). Kept exported as part of public API for callers that
    want strict-missing semantics (e.g. ``if store.get(k) is None: raise VariableNotFoundError(k)``).

    Subclass of ``KeyError`` so existing ``except KeyError`` handlers
    continue to work transparently.
    """


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
    def get_default(cls) -> DSLVariableStore:
        """Singleton с дефолтным backend (in-memory).

        В production переопределите через `configure()` в lifespan.py.
        """
        if not _default_instance:
            _default_instance.append(cls(backends=[InMemoryVariableBackend()]))
        return _default_instance[0]

    @classmethod
    def configure(cls, backends: list[VariableBackend]) -> DSLVariableStore:
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
        """Удалить ``key`` из ``scope``; вернуть True если существовал."""
        scope_obj = (
            scope if isinstance(scope, VariableScope) else VariableScope.parse(scope)
        )
        deleted = False
        for backend in self.backends:
            if await backend.delete(key, scope_obj):
                deleted = True
        return deleted

    async def list_keys(self, scope: VariableScope | str = "global") -> list[str]:
        """Вернуть список ключей в ``scope``."""
        scope_obj = (
            scope if isinstance(scope, VariableScope) else VariableScope.parse(scope)
        )
        keys: set[str] = set()
        for backend in self.backends:
            keys.update(await backend.list_keys(scope_obj))
        return sorted(keys)


_default_instance: list[DSLVariableStore] = []
