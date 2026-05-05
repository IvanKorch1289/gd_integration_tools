"""ADR-042 (R1.2) — `plugin.toml` манифест V11.

Pydantic-модель + TOML-loader для V11-манифеста плагина. Параллельно
с Wave 4.4 :mod:`src.services.plugins.manifest` (`plugin.yaml`),
который остаётся deprecated-shim'ом на ≥ 1 minor-цикл (см. ADR-042
Migration path).

Этот модуль **не подключается** к :class:`PluginLoader` в текущей
итерации — Wave R1.2-импл произведёт дисcovery + интеграцию с
`CapabilityGate`.

Связанные ADR: ADR-042, ADR-043, ADR-044.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.backend.core.security.capabilities import CapabilityRef

__all__ = (
    "PluginManifestError",
    "PluginManifestV11",
    "PluginProvides",
    "load_plugin_manifest",
)


class PluginManifestError(ValueError):
    """Ошибка парсинга / валидации `plugin.toml`."""


class PluginProvides(BaseModel):
    """Декларативный inventory плагина.

    Перечисляет публичные имена, которые плагин зарегистрирует через
    lifecycle-хуки (:class:`BasePlugin.on_register_*`). Используется
    `PluginLoader` для проверки коллизий **до** активации плагина.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    actions: tuple[str, ...] = ()
    repositories: tuple[str, ...] = ()
    processors: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    sinks: tuple[str, ...] = ()
    schemas: tuple[str, ...] = ()


class PluginManifestV11(BaseModel):
    """Манифест плагина V11 (``extensions/<name>/plugin.toml``).

    См. ADR-042 для полного описания формата и migration-path.

    Attributes:
        name: snake_case-имя плагина; должно совпадать с каталогом
            ``extensions/<name>/``.
        version: SemVer-строка плагина.
        requires_core: PEP-440 SpecifierSet — диапазон версий ядра,
            с которыми совместим плагин (``">=0.2,<0.3"``).
        entry_class: Dotted path к :class:`BasePlugin`-наследнику.
        tenant_aware: Если ``True`` — плагин получит TenantContext-API
            от capability-фасадов; иначе фасад вернёт
            ``NoTenantError`` при запросе ``TenantFacade.current()``.
        description: Опциональная человекочитаемая аннотация.
        config_schema: Опциональный путь к JSON-Schema (относительно
            каталога плагина) для валидации :attr:`config`.
        capabilities: Декларация runtime-gate (см. ADR-044).
        provides: Декларативный inventory (см. :class:`PluginProvides`).
        config: Произвольный dict — передаётся в ``ctx.config``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    requires_core: str = Field(min_length=1)
    entry_class: str = Field(min_length=1)
    tenant_aware: bool = False
    description: str | None = None
    config_schema: str | None = None
    capabilities: tuple[CapabilityRef, ...] = ()
    provides: PluginProvides = Field(default_factory=PluginProvides)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("requires_core")
    @classmethod
    def _validate_core_spec(cls, value: str) -> str:
        """Валидирует ``requires_core`` как PEP-440 SpecifierSet."""
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(f"Invalid requires_core spec: {value!r}") from exc
        return value

    def is_compatible_with_core(self, core_version: str) -> bool:
        """Совместим ли плагин с заданной версией ядра."""
        return core_version in SpecifierSet(self.requires_core)


def load_plugin_manifest(path: Path | str) -> PluginManifestV11:
    """Прочитать и валидировать ``plugin.toml``.

    Args:
        path: Путь к файлу манифеста.

    Returns:
        Валидированный :class:`PluginManifestV11`.

    Raises:
        PluginManifestError: Файл не найден, TOML невалиден или
            модель не прошла pydantic-валидацию.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise PluginManifestError(f"Manifest not found: {file_path}")
    try:
        raw = tomllib.loads(file_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PluginManifestError(f"Invalid TOML in {file_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PluginManifestError(
            f"Manifest must be a TOML table, got {type(raw).__name__}: {file_path}"
        )
    try:
        return PluginManifestV11.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError → wrap
        raise PluginManifestError(
            f"Manifest validation failed for {file_path}: {exc}"
        ) from exc
