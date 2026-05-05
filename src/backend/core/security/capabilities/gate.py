"""ADR-044 — runtime :class:`CapabilityGate` + subset-checker.

Plugin/route декларирует свои capabilities при load; gate проверяет
каждый запрос ресурса на runtime через ``check(...)`` с LRU-кэшем.

Subset-проверка (route ⊆ plugins ∪ core_public) реализована статически
в :func:`check_capabilities_subset` и используется RouteLoader'ом до
активации маршрута.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Final

from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.vocabulary import (
    CapabilityVocabulary,
    build_default_vocabulary,
)

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

    Каждое ``check(...)``:

    1. Находит декларацию плагина: ``self._declarations[plugin][capability]``.
    2. Если декларации нет — :class:`CapabilityDeniedError`.
    3. Проверяет scope через :class:`ScopeMatcher` из vocabulary.
    4. Audit-callback (если задан) пишет outcome.
    """

    def __init__(
        self,
        *,
        vocabulary: CapabilityVocabulary | None = None,
        audit: AuditCallback | None = None,
        lru_size: int = _DEFAULT_LRU_SIZE,
    ) -> None:
        self._vocabulary = vocabulary or build_default_vocabulary()
        self._audit = audit
        self._declarations: dict[str, dict[str, CapabilityRef]] = {}
        self._cache: dict[tuple[str, str, str | None], bool] = {}
        self._lru_size = lru_size

    @property
    def vocabulary(self) -> CapabilityVocabulary:
        """Доступ к registry для админ-UI и DSL-Linter."""
        return self._vocabulary

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
            CapabilityDeniedError: Декларация отсутствует или scope
                не покрывается.
            CapabilityNotFoundError: Имя отсутствует в vocabulary.
        """
        cache_key = (plugin, capability, requested_scope)
        if cache_key in self._cache:
            self._emit_audit(plugin, capability, requested_scope, None, "granted")
            return

        declared = self._declarations.get(plugin, {}).get(capability)
        if declared is None:
            self._emit_audit(plugin, capability, requested_scope, None, "denied")
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
                plugin, capability, requested_scope, declared.scope, "granted"
            )
            return

        if requested_scope is None:
            self._emit_audit(
                plugin, capability, requested_scope, declared.scope, "denied"
            )
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=None,
                declared_scope=declared.scope,
            )

        # Mypy: declared.scope is not None потому что validate_ref
        # отвергает scope=None при scope_required=True.
        assert declared.scope is not None  # noqa: S101 — invariant
        if not definition.matcher.match(requested_scope, declared.scope):
            self._emit_audit(
                plugin, capability, requested_scope, declared.scope, "denied"
            )
            raise CapabilityDeniedError(
                plugin=plugin,
                capability=capability,
                requested_scope=requested_scope,
                declared_scope=declared.scope,
            )

        self._cache_granted(cache_key)
        self._emit_audit(plugin, capability, requested_scope, declared.scope, "granted")

    def declarations(self, plugin: str) -> tuple[CapabilityRef, ...]:
        """Возвращает текущий набор capabilities для плагина."""
        return tuple(self._declarations.get(plugin, {}).values())

    # ── private ──────────────────────────────────────────────────────

    def _cache_granted(self, key: tuple[str, str, str | None]) -> None:
        """Положить granted-результат в LRU (с ограничением размера)."""
        if len(self._cache) >= self._lru_size:
            # Простейший LRU: выбрасываем самый старый ключ
            # (порядок dict'а сохраняет insertion order).
            oldest = next(iter(self._cache))
            self._cache.pop(oldest, None)
        self._cache[key] = True

    def _invalidate_plugin(self, plugin: str) -> None:
        """Удалить из кэша все granted-записи для плагина."""
        self._cache = {key: v for key, v in self._cache.items() if key[0] != plugin}

    def _emit_audit(
        self,
        plugin: str,
        capability: str,
        requested_scope: str | None,
        declared_scope: str | None,
        outcome: str,
    ) -> None:
        """Вызвать audit-callback, если задан."""
        if self._audit is None:
            return
        self._audit(
            {
                "event": "capability.check",
                "plugin": plugin,
                "capability": capability,
                "requested_scope": requested_scope,
                "declared_scope": declared_scope,
                "outcome": outcome,
            }
        )


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
