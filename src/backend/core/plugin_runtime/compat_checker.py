"""Sprint 14 W1 — runtime-проверка матрицы совместимости плагинов.

Назначение:
    Дополняет :mod:`semver_checker` (одиночный плагин vs ядро) проверкой
    cross-plugin compatibility (см. ``PluginManifestV11.compatibility``).
    Вызывается :class:`PluginLoaderV11` после parse всех ``plugin.toml``,
    но до ``on_load``. Если найден конфликт — оба плагина уходят в
    статус ``"failed"`` с reason ``compat_conflict``.

Использование:
    from src.backend.core.plugin_runtime.compat_checker import check_compatibility

    violations = check_compatibility(manifests, core_version="0.2.5")
    if violations:
        for v in violations:
            logger.warning("compat conflict: %s", v)

Алгоритм:
    Для каждой пары (manifest, other_manifest) проверяет:

    1. ``other.name in manifest.compatibility.incompatible_with`` →
       hard conflict (любая версия).
    2. ``other.name in manifest.compatibility.incompatible_plugin_specs``
       и ``other.version`` соответствует spec → version conflict.
    3. ``core_version in manifest.compatibility.incompatible_core_versions``
       (PEP-440 SpecifierSet) → core conflict.
    4. Для каждого ``required_plugin`` в ``manifest.compatibility.requires_plugins``:
       если плагин отсутствует ИЛИ его версия не соответствует spec →
       missing-dependency conflict.

Зависимости:
    - packaging (PEP-440 specifiers + Version);
    - PluginManifestV11 (из services/plugins/manifest_v11.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from src.backend.services.plugins.manifest_v11 import PluginManifestV11

__all__ = (
    "CompatViolation",
    "PluginConflictError",
    "check_compatibility",
)


ConflictKind = Literal[
    "hard_incompatible",
    "version_incompatible",
    "core_incompatible",
    "missing_dependency",
    "dependency_version_mismatch",
]


@dataclass(frozen=True, slots=True)
class CompatViolation:
    """Описание одного нарушения матрицы совместимости.

    Attributes:
        plugin: Имя плагина, чья ``compatibility``-декларация
            спровоцировала нарушение.
        conflicting_plugin: Имя противоположного плагина (или
            ``"<core>"`` для конфликтов с версией ядра).
        kind: Тип нарушения (см. :data:`ConflictKind`).
        reason: Человекочитаемая причина с подробностями.
    """

    plugin: str
    conflicting_plugin: str
    kind: ConflictKind
    reason: str


class PluginConflictError(RuntimeError):
    """Нарушение compatibility matrix; содержит :class:`CompatViolation`."""

    def __init__(self, violation: CompatViolation) -> None:
        self.violation = violation
        super().__init__(
            f"plugin compatibility conflict: {violation.plugin!r} vs "
            f"{violation.conflicting_plugin!r} — {violation.kind}: {violation.reason}"
        )


def _try_parse_version(value: str) -> Version | None:
    """Безопасный parsing PEP-440 версии; ``None`` при ошибке."""
    try:
        return Version(value)
    except InvalidVersion:
        return None


def _try_parse_spec(value: str) -> SpecifierSet | None:
    """Безопасный parsing PEP-440 SpecifierSet; ``None`` при ошибке."""
    if not value:
        return None
    try:
        return SpecifierSet(value)
    except InvalidSpecifier:
        return None


def _check_pair(
    manifest: PluginManifestV11,
    other: PluginManifestV11,
) -> list[CompatViolation]:
    """Проверяет одну пару (manifest, other) на pair-wise конфликты."""
    violations: list[CompatViolation] = []
    compat = manifest.compatibility

    if other.name in compat.incompatible_with:
        violations.append(
            CompatViolation(
                plugin=manifest.name,
                conflicting_plugin=other.name,
                kind="hard_incompatible",
                reason=(
                    f"{manifest.name!r} declares incompatible_with "
                    f"{other.name!r} (any version)"
                ),
            )
        )

    spec_str = compat.incompatible_plugin_specs.get(other.name)
    if spec_str is not None:
        spec = _try_parse_spec(spec_str)
        ver = _try_parse_version(other.version)
        if spec is not None and ver is not None and ver in spec:
            violations.append(
                CompatViolation(
                    plugin=manifest.name,
                    conflicting_plugin=other.name,
                    kind="version_incompatible",
                    reason=(
                        f"{manifest.name!r} marks {other.name}=={other.version} "
                        f"incompatible (spec {spec_str!r})"
                    ),
                )
            )
    return violations


def _check_core(
    manifest: PluginManifestV11,
    core_version: str | None,
) -> CompatViolation | None:
    """Проверяет дополнительный `incompatible_core_versions` ограничитель."""
    if not core_version:
        return None
    spec = _try_parse_spec(manifest.compatibility.incompatible_core_versions)
    if spec is None:
        return None
    ver = _try_parse_version(core_version)
    if ver is None or ver not in spec:
        return None
    return CompatViolation(
        plugin=manifest.name,
        conflicting_plugin="<core>",
        kind="core_incompatible",
        reason=(
            f"{manifest.name!r} declares core {core_version} incompatible "
            f"(spec {manifest.compatibility.incompatible_core_versions!r})"
        ),
    )


def _check_required(
    manifest: PluginManifestV11,
    by_name: dict[str, PluginManifestV11],
) -> list[CompatViolation]:
    """Проверяет обязательные ``requires_plugins`` ссылки."""
    violations: list[CompatViolation] = []
    for required_name, required_spec in manifest.compatibility.requires_plugins.items():
        target = by_name.get(required_name)
        if target is None:
            violations.append(
                CompatViolation(
                    plugin=manifest.name,
                    conflicting_plugin=required_name,
                    kind="missing_dependency",
                    reason=(
                        f"{manifest.name!r} requires {required_name!r} "
                        f"(spec {required_spec!r}) but it is not installed"
                    ),
                )
            )
            continue
        spec = _try_parse_spec(required_spec)
        ver = _try_parse_version(target.version)
        if spec is None or ver is None or ver not in spec:
            violations.append(
                CompatViolation(
                    plugin=manifest.name,
                    conflicting_plugin=required_name,
                    kind="dependency_version_mismatch",
                    reason=(
                        f"{manifest.name!r} requires {required_name} {required_spec!r} "
                        f"but installed version is {target.version!r}"
                    ),
                )
            )
    return violations


def check_compatibility(
    manifests: Sequence[PluginManifestV11] | Iterable[PluginManifestV11],
    *,
    core_version: str | None = None,
) -> tuple[CompatViolation, ...]:
    """Полный обход матрицы совместимости.

    Args:
        manifests: Все распарсенные манифесты (loaded + skipped).
        core_version: Текущая версия ядра для проверки
            ``incompatible_core_versions``. ``None`` — пропустить.

    Returns:
        Кортеж нарушений (пустой при отсутствии конфликтов).
    """
    materialised = tuple(manifests)
    by_name: dict[str, PluginManifestV11] = {m.name: m for m in materialised}
    violations: list[CompatViolation] = []

    for manifest in materialised:
        core_violation = _check_core(manifest, core_version)
        if core_violation is not None:
            violations.append(core_violation)

        for other in materialised:
            if other.name == manifest.name:
                continue
            violations.extend(_check_pair(manifest, other))

        violations.extend(_check_required(manifest, by_name))

    return tuple(violations)
