"""ADR-044 — runtime :class:`CapabilityGate` + subset-checker.

Plugin/route декларирует свои capabilities при load; gate проверяет
каждый запрос ресурса на runtime через ``check(...)`` с LRU-кэшем.

Subset-проверка (route ⊆ plugins ∪ core_public) реализована статически
в :func:`check_capabilities_subset` и используется RouteLoader'ом до
активации маршрута.

Sprint 36 (V15 GAP, Subagent A) additions:

* Optional ``policy: CapabilityPolicy`` в ``__init__`` — consult policy
  *before* declaration-check; deny/allow/no_match semantics с tie-break
  deny > allow.
* Tenant-aware API: :meth:`check_tenant`, :meth:`declare_tenant`,
  :meth:`revoke_tenant`, :meth:`list_allocated_tenant` (per-tenant
  LRU cache, audit events ``capability.allocated`` /
  ``capability.revoked``).
* Default tenant = :data:`SYSTEM_TENANT_ID` (``"_system"``) — backward
  compat с existing call sites.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Final

from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.tenant import SYSTEM_TENANT_ID
from src.backend.core.security.capabilities.vocabulary import (
    CapabilityVocabulary,
    build_default_vocabulary,
)

if TYPE_CHECKING:
    from src.backend.core.security.capabilities.policy import CapabilityPolicy

__all__ = ("AuditCallback", "CapabilityGate", "check_capabilities_subset")

AuditCallback = Callable[[dict[str, object]], None]
"""Подпись audit-callback'а: принимает event dict, ничего не возвращает."""


_DEFAULT_LRU_SIZE: Final[int] = 1024


class CapabilityGate:
    """Runtime gate: проверяет, разрешён ли вызов capability с scope.

    Args:
        vocabulary: Registry capability-определений; если ``None`` —
            используется :func:`build_default_vocabulary`.
        audit: Опц. callback, вызываемый на каждый ``check(...)``.
            В audit-event пишутся:
            ``{"event": "capability.check", "plugin": ..., "capability": ...,
            "requested_scope": ..., "declared_scope": ..., "outcome": ...}``.
        lru_size: Размер LRU-кэша для granted-результатов
            (denied не кэшируется — это редкий путь).
        policy: Опц. :class:`CapabilityPolicy` — consult *before*
            declaration-check. ``None`` (default) — zero overhead, old
            behaviour preserved.

    Каждое ``check(...)``:

    1. Если ``policy`` задана → :meth:`CapabilityPolicy.evaluate`; deny →
       ``CapabilityDeniedError``; allow → skip declaration-check.
    2. Находит декларацию плагина: ``self._declarations[plugin][capability]``.
    3. Если декларации нет — :class:`CapabilityDeniedError`.
    4. Проверяет scope через :class:`ScopeMatcher` из vocabulary.
    5. Audit-callback (если задан) пишет outcome.
    """

    def __init__(
        self,
        *,
        vocabulary: CapabilityVocabulary | None = None,
        audit: AuditCallback | None = None,
        lru_size: int = _DEFAULT_LRU_SIZE,
        policy: "CapabilityPolicy | None" = None,
    ) -> None:
        self._vocabulary = vocabulary or build_default_vocabulary()
        self._audit = audit
        self._declarations: dict[str, dict[str, CapabilityRef]] = {}
        self._cache: dict[tuple[str, str, str | None], bool] = {}
        self._lru_size = lru_size
        # Per-tenant storage: tenant_id → principal_id → capability_name → ref.
        self._tenant_declarations: dict[str, dict[str, dict[str, CapabilityRef]]] = {}
        # Per-tenant LRU cache: (tenant, principal, capability, scope) → bool.
        self._tenant_cache: dict[tuple[str, str, str, str | None], bool] = {}
        self._policy: "CapabilityPolicy | None" = policy

    @property
    def vocabulary(self) -> CapabilityVocabulary:
        """Доступ к registry для админ-UI и DSL-Linter."""
        return self._vocabulary

    @property
    def policy(self) -> "CapabilityPolicy | None":
        """Опц. policy, интегрированная в gate (``None`` → no policy)."""
        return self._policy

    def declare(self, plugin: str, capabilities: Iterable[CapabilityRef]) -> None:
        """Декларировать capabilities плагина/route'а.

        Вызывается :class:`PluginLoader` / :class:`RouteLoader` после
        парсинга манифеста и **до** ``import_module(entry_class)``.

        Raises:
            CapabilityNotFoundError: Имя capability отсутствует в
                vocabulary.
            ValueError: Уже задекларировано для этого плагина (по имени
                capability).
        """
        bucket = self._declarations.setdefault(plugin, {})
        for ref in capabilities:
            self._vocabulary.validate_ref(ref)
            if ref.name in bucket:
                raise ValueError(
                    f"Capability {ref.name!r} already declared for {plugin!r}"
                )
            bucket[ref.name] = ref
        # Любая новая декларация инвалидирует кэш для этого плагина.
        self._invalidate_plugin(plugin)

    def revoke(self, plugin: str) -> None:
        """Отозвать все декларации плагина (на shutdown / unload)."""
        self._declarations.pop(plugin, None)
        self._invalidate_plugin(plugin)

    def check(self, plugin: str, capability: str, requested_scope: str | None) -> None:
        """Проверить, разрешён ли вызов; raise при denied.

        Args:
            plugin: Имя плагина / route'а.
            capability: Имя capability (``db.read``, и т.д.).
            requested_scope: Scope, который реально нужен runtime.

        Raises:
            CapabilityDeniedError: Декларация отсутствует, scope
                не покрывается, или policy вернула ``deny``.
            CapabilityNotFoundError: Имя отсутствует в vocabulary.
        """
        cache_key = (plugin, capability, requested_scope)
        if cache_key in self._cache:
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=None,
                outcome="granted",
            )
            return

        # Policy consultation (before declaration check).
        if self._policy is not None:
            decision = self._policy.evaluate(
                tenant=SYSTEM_TENANT_ID,
                principal=plugin,
                capability=capability,
                scope=requested_scope,
            )
            if decision.effect == "deny":
                self._emit_audit(
                    plugin=plugin,
                    capability=capability,
                    requested_scope=requested_scope,
                    declared_scope=None,
                    outcome="denied",
                    reason="policy",
                )
                raise CapabilityDeniedError(
                    plugin=plugin,
                    capability=capability,
                    requested_scope=requested_scope,
                    declared_scope=None,
                )
            if decision.effect == "allow":
                # Policy explicitly allows → skip declaration check.
                self._cache_granted(cache_key)
                self._emit_audit(
                    plugin=plugin,
                    capability=capability,
                    requested_scope=requested_scope,
                    declared_scope=None,
                    outcome="granted",
                    reason="policy",
                )
                return
            # no_match → fall through to declaration check.

        declared = self._declarations.get(plugin, {}).get(capability)
        if declared is None:
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=None,
                outcome="denied",
            )
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=None,
            )

        definition = self._vocabulary.get(capability)

        # Capability с `scope_required=False` принимает любой scope.
        if not definition.scope_required:
            self._cache_granted(cache_key)
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
                outcome="granted",
            )
            return

        if requested_scope is None:
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
                outcome="denied",
            )
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=None,
                declared_scope=declared.scope,
            )

        # Mypy: declared.scope is not None потому что validate_ref
        # отвергает scope=None при scope_required=True.
        assert declared.scope is not None
        if not definition.matcher.match(requested_scope, declared.scope):
            self._emit_audit(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
                outcome="denied",
            )
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
            )

        self._cache_granted(cache_key)
        self._emit_audit(
            plugin=plugin,
            capability=capability,
            requested_scope=requested_scope,
            declared_scope=declared.scope,
            outcome="granted",
        )

    # ── Tenant-aware API (Sprint 36 V15 GAP) ─────────────────────────

    def check_tenant(
        self, capability: str, tenant: str, principal: str, scope: str | None = None
    ) -> bool:
        """Tenant-aware check: возвращает ``bool`` (не raise).

        Args:
            capability: Имя capability (``db.read``, ``net.outbound``).
            tenant: Tenant-id (``"tenant_a"`` или :data:`SYSTEM_TENANT_ID`).
            principal: Principal-id (плагин/route).
            scope: Запрошенный scope (или ``None``).

        Returns:
            ``True`` если granted, ``False`` если denied.

        Notes:
            Семантика: ``deny`` от policy → ``False`` *до* declaration-check.
            ``allow`` → ``True`` (skip declaration). ``no_match`` →
            fallback to per-tenant declaration. Не выбрасывает
            :class:`CapabilityDeniedError` — caller сам решает.
        """
        cache_key = (tenant, principal, capability, scope)
        if cache_key in self._tenant_cache:
            cached = self._tenant_cache[cache_key]
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
                outcome="granted" if cached else "denied",
                tenant=tenant,
            )
            return cached

        # 1. Policy consultation.
        if self._policy is not None:
            decision = self._policy.evaluate(
                tenant=tenant, principal=principal, capability=capability, scope=scope
            )
            if decision.effect == "deny":
                self._tenant_cache[cache_key] = False
                self._emit_audit(
                    plugin=principal,
                    capability=capability,
                    requested_scope=scope,
                    declared_scope=None,
                    outcome="denied",
                    tenant=tenant,
                    reason="policy",
                )
                return False
            if decision.effect == "allow":
                self._tenant_cache[cache_key] = True
                self._emit_audit(
                    plugin=principal,
                    capability=capability,
                    requested_scope=scope,
                    declared_scope=None,
                    outcome="granted",
                    tenant=tenant,
                    reason="policy",
                )
                return True
            # no_match → fall through.

        # 2. Per-tenant declaration check.
        declared = (
            self._tenant_declarations.get(tenant, {}).get(principal, {}).get(capability)
        )
        if declared is None:
            self._tenant_cache[cache_key] = False
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=None,
                outcome="denied",
                tenant=tenant,
            )
            return False

        definition = self._vocabulary.get(capability)
        if not definition.scope_required:
            self._tenant_cache_granted(cache_key)
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=declared.scope,
                outcome="granted",
                tenant=tenant,
            )
            return True

        if scope is None:
            self._tenant_cache[cache_key] = False
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=declared.scope,
                outcome="denied",
                tenant=tenant,
            )
            return False

        assert declared.scope is not None
        if not definition.matcher.match(scope, declared.scope):
            self._tenant_cache[cache_key] = False
            self._emit_audit(
                plugin=principal,
                capability=capability,
                requested_scope=scope,
                declared_scope=declared.scope,
                outcome="denied",
                tenant=tenant,
            )
            return False

        self._tenant_cache_granted(cache_key)
        self._emit_audit(
            plugin=principal,
            capability=capability,
            requested_scope=scope,
            declared_scope=declared.scope,
            outcome="granted",
            tenant=tenant,
        )
        return True

    def declare_tenant(
        self, capability: CapabilityRef, tenant: str, principal: str
    ) -> None:
        """Декларировать capability для пары (tenant, principal).

        Args:
            capability: Capability для декларации.
            tenant: Tenant-id.
            principal: Principal-id (плагин/route) внутри tenant'а.

        Raises:
            CapabilityNotFoundError: Имя capability отсутствует в
                vocabulary.
            ValueError: Уже задекларировано для этой пары
                (tenant, principal).
        """
        self._vocabulary.validate_ref(capability)
        tenant_bucket = self._tenant_declarations.setdefault(tenant, {})
        principal_bucket = tenant_bucket.setdefault(principal, {})
        if capability.name in principal_bucket:
            raise ValueError(
                f"Capability {capability.name!r} already declared for "
                f"tenant={tenant!r}, principal={principal!r}"
            )
        principal_bucket[capability.name] = capability
        # Invalidate per-tenant cache for this (tenant, principal).
        self._invalidate_tenant(tenant, principal)
        # Audit: capability.allocated.
        self._emit_audit(
            plugin=principal,
            capability=capability.name,
            requested_scope=capability.scope,
            declared_scope=capability.scope,
            outcome="granted",
            tenant=tenant,
            event="capability.allocated",
        )

    def revoke_tenant(self, capability: str, tenant: str) -> None:
        """Отозвать декларацию capability для tenant'а (для всех principal'ов).

        Args:
            capability: Имя capability для отзыва.
            tenant: Tenant-id.
        """
        revoked = False
        tenant_bucket = self._tenant_declarations.get(tenant)
        if tenant_bucket is not None:
            for principal, principal_bucket in list(tenant_bucket.items()):
                if capability in principal_bucket:
                    principal_bucket.pop(capability, None)
                    revoked = True
        # Invalidate per-tenant cache.
        self._invalidate_tenant(tenant)
        if revoked:
            self._emit_audit(
                plugin=SYSTEM_TENANT_ID,
                capability=capability,
                requested_scope=None,
                declared_scope=None,
                outcome="granted",
                tenant=tenant,
                event="capability.revoked",
            )

    def list_allocated_tenant(self, tenant: str) -> tuple[CapabilityRef, ...]:
        """Список capabilities, задекларированных для tenant'а.

        Возвращает **все** декларации для tenant'а (через всех
        principal'ов). Дедупликация не выполняется — caller'у видны
        все (principal, capability) пары.

        Args:
            tenant: Tenant-id.

        Returns:
            Кортеж :class:`CapabilityRef` (может быть пустым).
        """
        result: list[CapabilityRef] = []
        tenant_bucket = self._tenant_declarations.get(tenant)
        if tenant_bucket is not None:
            for principal_bucket in tenant_bucket.values():
                result.extend(principal_bucket.values())
        return tuple(result)

    def declarations(self, plugin: str) -> tuple[CapabilityRef, ...]:
        """Возвращает текущий набор capabilities для плагина."""
        return tuple(self._declarations.get(plugin, {}).values())

    def list_allocated(self, plugin: str) -> tuple[str, ...]:
        """ADR-NEW-4 (S17): имена задекларированных capabilities плагина.

        Алиас для :meth:`declarations`, возвращающий только имена.
        Часть :class:`CapabilityGatewayProtocol` (``core.interfaces``).
        """
        return tuple(self._declarations.get(plugin, {}).keys())

    # ── private ──────────────────────────────────────────────────────

    def _cache_granted(self, key: tuple[str, str, str | None]) -> None:
        """Положить granted-результат в LRU (с ограничением размера)."""
        if len(self._cache) >= self._lru_size:
            # Простейший LRU: выбрасываем самый старый ключ
            # (порядок dict'а сохраняет insertion order).
            oldest = next(iter(self._cache))
            self._cache.pop(oldest, None)
        self._cache[key] = True

    def _tenant_cache_granted(self, key: tuple[str, str, str, str | None]) -> None:
        """Положить granted-результат в per-tenant LRU."""
        if len(self._tenant_cache) >= self._lru_size:
            oldest = next(iter(self._tenant_cache))
            self._tenant_cache.pop(oldest, None)
        self._tenant_cache[key] = True

    def _invalidate_plugin(self, plugin: str) -> None:
        """Удалить из кэша все granted-записи для плагина."""
        self._cache = {key: v for key, v in self._cache.items() if key[0] != plugin}

    def _invalidate_tenant(self, tenant: str, principal: str | None = None) -> None:
        """Удалить из per-tenant кэша записи для (tenant, principal).

        Если ``principal=None`` — удаляются все записи для tenant'а.
        """
        if principal is None:
            self._tenant_cache = {
                key: v for key, v in self._tenant_cache.items() if key[0] != tenant
            }
        else:
            self._tenant_cache = {
                key: v
                for key, v in self._tenant_cache.items()
                if not (key[0] == tenant and key[1] == principal)
            }

    def _emit_audit(
        self,
        *,
        plugin: str,
        capability: str,
        requested_scope: str | None,
        declared_scope: str | None,
        outcome: str,
        tenant: str | None = None,
        reason: str | None = None,
        event: str = "capability.check",
    ) -> None:
        """Вызвать audit-callback, если задан.

        Поля ``tenant``, ``reason``, ``event`` — опциональные
        (передаются только в tenant-aware путях или для указания
        причины ``"policy"``). Старые callers (без этих kwargs) получают
        тот же event-dict, что и раньше — backward compat preserved.
        """
        if self._audit is None:
            return
        payload: dict[str, object] = {
            "event": event,
            "plugin": plugin,
            "capability": capability,
            "requested_scope": requested_scope,
            "declared_scope": declared_scope,
            "outcome": outcome,
        }
        if tenant is not None:
            payload["tenant"] = tenant
        if reason is not None:
            payload["reason"] = reason
        self._audit(payload)


def check_capabilities_subset(
    *,
    route: str,
    route_caps: Iterable[CapabilityRef],
    plugin_caps_by_name: dict[str, tuple[CapabilityRef, ...]],
    vocabulary: CapabilityVocabulary,
) -> None:
    """Проверить инвариант ``route.capabilities ⊆ union(plugin) ∪ core_public``.

    Используется :class:`RouteLoader` при активации маршрута.

    Args:
        route: Имя маршрута (для сообщения об ошибке).
        route_caps: Capabilities, объявленные в `route.toml`.
        plugin_caps_by_name: Mapping ``plugin_name → tuple[CapabilityRef]``
            из манифестов всех плагинов из ``requires_plugins``.
        vocabulary: Registry; ``public_capabilities()`` берётся как
            «общедоступный» набор ядра.

    Raises:
        CapabilitySupersetError: Хотя бы одна capability route'а не
            покрывается объединением источников.
    """
    available: list[CapabilityRef] = []
    for caps in plugin_caps_by_name.values():
        available.extend(caps)
    # Public ядра представлены как CapabilityRef без scope (открытое
    # пространство); matcher для них трактует requested как разрешённый.
    public_names = {d.name for d in vocabulary.public_capabilities()}

    offending: list[CapabilityRef] = []
    for ref in route_caps:
        if ref.name in public_names:
            continue
        if not _is_covered(ref, available, vocabulary):
            offending.append(ref)
    if offending:
        raise CapabilitySupersetError(route=route, offending=tuple(offending))


def _is_covered(
    ref: CapabilityRef, available: list[CapabilityRef], vocabulary: CapabilityVocabulary
) -> bool:
    """Покрывается ли ``ref`` хотя бы одной capability из ``available``."""
    try:
        definition = vocabulary.get(ref.name)
    except CapabilityNotFoundError:
        return False
    for candidate in available:
        if candidate.name != ref.name:
            continue
        # Если capability scope_required=False, наличия имени достаточно.
        if not definition.scope_required:
            return True
        if candidate.scope is None or ref.scope is None:
            # public-без-scope vs scoped — несравнимы, считаем не-покрытием
            continue
        if definition.matcher.match(ref.scope, candidate.scope):
            return True
    return False
