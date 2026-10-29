"""CapabilityGate package (S54 W4 decomp from gate.py 629 LOC).

17 methods decomposed в 4 mixin files:
- ``declaration_mixin.py`` (5): declare, revoke, declare_tenant, revoke_tenant, list_allocated_tenant
- ``check_mixin.py`` (2): check, check_tenant (the BIG methods 132 + 128 LOC)
- ``cache_mixin.py`` (6): cache + invalidation (granted caches, plugin/tenant invalidation)
- ``audit_mixin.py`` (1): _emit_audit

Core (__init__ + vocabulary + policy) остается в __init__.py.

Backward-compat: ``from src.backend.core.security.capabilities.gate import CapabilityGate`` works.
"""

from __future__ import annotations

from collections.abc import Callable as Callable
from collections.abc import Iterable as Iterable
from functools import lru_cache
from threading import Lock as Lock
from typing import TYPE_CHECKING as TYPE_CHECKING
from typing import Final as Final

from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.models import CapabilityRef as CapabilityRef
from src.backend.core.security.capabilities.policy import (
    CapabilityPolicy as CapabilityPolicy,
)
from src.backend.core.security.capabilities.vocabulary import (
    CapabilityVocabulary,
    build_default_vocabulary,  # S79 W2 fix: S54 W4 decomp forgot import
)

if TYPE_CHECKING:
    pass

from src.backend.core.security.capabilities.gate.audit_mixin import (
    AuditMixin,  # S54 W4: MRO
)
from src.backend.core.security.capabilities.gate.cache_mixin import (
    CacheMixin,  # S54 W4: MRO
)
from src.backend.core.security.capabilities.gate.check_mixin import (
    CheckMixin,  # S54 W4: MRO
)
from src.backend.core.security.capabilities.gate.check_tenant_mixin import (
    CheckTenantMixin,  # S54 M2-#7: MRO
)
from src.backend.core.security.capabilities.gate.declaration_mixin import (
    DeclarationMixin,  # S54 W4: MRO
)

__all__ = (
    "CapabilityGate",
    "CheckMixin",
    "CheckTenantMixin",
    "CacheMixin",
    "DeclarationMixin",
    "get_capability_gate",
)


# --- Module-level constants (S54 W4 decomp: preserve original constants) ---
AuditCallback = Callable[[dict[str, object]], None]

_DEFAULT_LRU_SIZE: Final[int] = 1024

# --- End constants ---


class CapabilityGate(DeclarationMixin, CheckMixin, CacheMixin, AuditMixin):
    """Capability Gate (4 mixins = 14 methods + 3 core).

    S79 W2 fix: removed ``__slots__ = ()`` (S54 W4 decomp forgot про
    instance attrs ``_vocabulary`` etc). Same pattern as S74 W4
    NotebookExecutionService / S76 W3 AIPolicyEnforcer / S76 W4 fix.
    """

    _cache: dict[tuple[str, str, str | None], bool]
    _tenant_cache: dict[tuple[str, str, str, str | None], bool]
    _lock: Lock  # D-AUDIT-98 (S183 W1.1)

    def __init__(
        self,
        *,
        vocabulary: CapabilityVocabulary | None = None,
        audit: AuditCallback | None = None,
        lru_size: int = _DEFAULT_LRU_SIZE,
        policy: CapabilityPolicy | None = None,
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
        self._policy: CapabilityPolicy | None = policy
        # D-AUDIT-98 (S183 W1.1): guard _cache / _tenant_cache against
        # grant+revoke races that previously raised
        # "RuntimeError: dictionary changed size during iteration".
        self._lock: Lock = Lock()

    def check(self, plugin: str, capability: str, requested_scope: str | None) -> None:
        """Runtime-проверка capability (ADR-0397: actionable-сообщение).

        Перекрывает :meth:`CheckMixin.check`, чтобы сообщение об отказе
        называло **требуемый scope** и **где объявить** capability — иначе
        автор роута получает «Capability denied» без подсказки.

        Args:
            plugin: Имя плагина / роута (namespace декларации).
            capability: Имя capability.
            requested_scope: Scope, который требуется на runtime.

        Raises:
            CapabilityDeniedError: Декларация отсутствует или scope не
                покрывается. Сообщение дополнено подсказкой.

        """
        try:
            super().check(plugin, capability, requested_scope)
        except CapabilityDeniedError as exc:
            raise _with_declaration_hint(exc, plugin, capability) from exc

    @property
    def vocabulary(self) -> CapabilityVocabulary:
        """Доступ к registry для админ-UI и DSL-Linter."""
        return self._vocabulary

    @property
    def policy(self) -> CapabilityPolicy | None:
        """Опц. policy, интегрированная в gate (``None`` → no policy)."""
        return self._policy


@lru_cache(maxsize=1)
def get_capability_gate() -> CapabilityGate:
    """Вернуть process-wide singleton :class:`CapabilityGate`.

    Cycle 172 (Wave 5): функцию импортировал
    ``src/backend/dsl/engine/processors/agent_dsl/_base.py:207``, но её
    **не существовало** → ``ImportError`` → ``_resolve_capability_gate()``
    возвращал ``None`` → ``_check_capability()`` молча пропускал
    проверку. То есть 12 agent_dsl-процессоров (ai.invoke,
    ai.memory.read/write, pii.tokenize.reversible, skill.invoke,
    agent.run, mcp.call, ai.tool.dispatch) работали **без**
    capability-контроля — fail-open в обход ADR-044.

    Теперь singleton существует и отдаёт гейт с дефолтным
    vocabulary. Проверка становится fail-closed: capability, которую
    никто не задекларировал, будет отклонена.

    Гейт — **единственный** на процесс: в нём живут и baseline-декларации
    ядра (:mod:`core_declarations`), и декларации роутов/плагинов,
    которые добавляют ``plugin_loader`` и ``RouteLoader``. Раньше
    экземпляров было три (loader / facade / ai-provider), поэтому
    декларации роутов не были видны runtime-проверкам вообще.

    Returns:
        Процессный singleton-гейт.
    """
    from src.backend.core.security.capabilities.core_declarations import (
        core_capability_refs,
    )

    gate = CapabilityGate(vocabulary=build_default_vocabulary())
    gate.declare("core", core_capability_refs())
    # Cycle 172 (Wave 7a): production StorageFacade создаётся с
    # plugin="system" (composition root, service_setup._register_storage_facade),
    # а DSL-шаги S3 — с plugin=route_id. Без декларации для "system"
    # и для роутов реальный capability-gate превратил бы S3 в
    # blanket-deny (после того, как раньше он молча обходил gate).
    gate.declare("system", core_capability_refs())
    # "ai-agent" — plugin AI-слоя (core/ai/fs_facade.py:56,
    # core/ai/skill_registry.py, infrastructure/ai/e2b_sandbox.py:49).
    #
    # Оба — плагины ядра/инфраструктуры, а не пользовательские расширения:
    # их capability объявляет сама платформа. Пользовательские плагины
    # (extensions/*) по-прежнему обязаны объявлять свои capability
    # в plugin.toml — это не обход контроля, а baseline для
    # инфраструктурных capability.
    #
    # "extension" намеренно НЕ входит в baseline: изолированные инстансы
    # UnifiedCacheFacade с plugin="extension" создаются без capability_check
    # (services/cache/__init__.py:100-103), а фасады, которые его всё же
    # получают, обязаны объявить capability в plugin.toml.
    gate.declare("ai-agent", core_capability_refs())
    return gate


def _declaration_hint(capability: str, scope: str | None) -> str:
    """Подсказка «где и как объявить capability» (ADR-0397).

    Args:
        capability: Имя capability.
        scope: Требуемый scope (алиас ресурса) либо ``None``.

    Returns:
        Текст подсказки для сообщения об ошибке.

    """
    scope_hint = f'scope = "{scope}"' if scope else 'scope = "<scope>"'
    hint = (
        f'Объявите capability в routes/<route>/route.toml (или в plugin.toml '
        f'владельца): [[capabilities]] name = "{capability}" {scope_hint}'
    )
    if capability.startswith("db."):
        hint += (
            " — scope обязан совпасть с алиасом ресурса БД "
            "(профиль внешней БД или имя таблицы), который использует шаг"
        )
    return hint


def _with_declaration_hint(
    exc: CapabilityDeniedError, plugin: str, capability: str
) -> CapabilityDeniedError:
    """Дополнить :class:`CapabilityDeniedError` подсказкой по декларации.

    Args:
        exc: Исходная ошибка отказа.
        plugin: Имя плагина / роута.
        capability: Имя capability.

    Returns:
        Новая ошибка с тем же набором полей и расширенным сообщением.

    """
    enriched = CapabilityDeniedError(
        plugin=exc.plugin,
        capability=exc.capability,
        requested_scope=exc.requested_scope,
        declared_scope=exc.declared_scope,
        tenant=exc.tenant,
        principal=exc.principal,
        correlation_id=exc.correlation_id,
    )
    base = exc.args[0] if exc.args else str(exc)
    enriched.args = (
        f"{base}. {_declaration_hint(capability, exc.requested_scope)}",
    )
    del plugin  # plugin уже присутствует в тексте исходной ошибки
    return enriched


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
            покрывается объединением источников. Сообщение дополнено
            требуемым scope и местом декларации (ADR-0397).

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
        error = CapabilitySupersetError(route=route, offending=tuple(offending))
        names = ", ".join(f"{c.name}({c.scope!r})" for c in offending)
        hints = "; ".join(
            _declaration_hint(ref.name, ref.scope) for ref in offending
        )
        error.args = (
            f"Route {route!r} requests capabilities not covered by "
            f"requires_plugins or core public set: {names}. {hints}",
        )
        raise error


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
