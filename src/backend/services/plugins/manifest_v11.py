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
from typing import Any, Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.backend.core.security.capabilities import CapabilityRef

__all__ = (
    "PluginCompatibility",
    "PluginManifestError",
    "PluginManifestV11",
    "PluginProvides",
    "PluginSandbox",
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


class PluginCompatibility(BaseModel):
    """Sprint 14 W1 — декларация совместимости плагина.

    Расширяет ``requires_core`` (минимальный диапазон ядра) полем
    ``incompatible_with`` для конфликта с конкретными плагинами и
    ``requires_plugins`` для обязательных зависимостей. Применяется
    при load через :mod:`core.plugin_runtime.compat_checker`.

    Attributes:
        incompatible_with: Список имён плагинов, не совместимых ни в
            какой версии (любая комбинация → conflict).
        incompatible_plugin_specs: Mapping ``plugin_name → PEP-440 spec``;
            конфликт возникает, если установлен ``plugin_name`` с
            версией внутри ``spec``.
        incompatible_core_versions: Дополнительный PEP-440 SpecifierSet —
            диапазон версий ядра, заведомо несовместимых даже при
            прохождении ``requires_core``. Пустая строка — нет
            дополнительных ограничений.
        requires_plugins: Mapping ``plugin_name → PEP-440 spec`` —
            обязательные плагины, без которых текущий не загрузится.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    incompatible_with: tuple[str, ...] = ()
    incompatible_plugin_specs: dict[str, str] = Field(default_factory=dict)
    incompatible_core_versions: str = ""
    requires_plugins: dict[str, str] = Field(default_factory=dict)

    @field_validator("incompatible_plugin_specs", "requires_plugins")
    @classmethod
    def _validate_specifier_map(cls, value: dict[str, str]) -> dict[str, str]:
        """Все значения должны быть валидными PEP-440 SpecifierSet."""
        for plugin_name, spec in value.items():
            try:
                SpecifierSet(spec)
            except InvalidSpecifier as exc:
                raise ValueError(
                    f"Invalid PEP-440 specifier for plugin {plugin_name!r}: {spec!r}"
                ) from exc
        return dict(value)

    @field_validator("incompatible_core_versions")
    @classmethod
    def _validate_core_versions(cls, value: str) -> str:
        """Пустая строка — отсутствие ограничения; иначе PEP-440 SpecifierSet."""
        if not value:
            return value
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(
                f"Invalid incompatible_core_versions specifier: {value!r}"
            ) from exc
        return value


class PluginSandbox(BaseModel):
    """Sprint 14 W2 — декларация sandbox-профиля плагина.

    Активирует изолированное исполнение через ``e2b`` backend
    (см. :mod:`infrastructure.ai.e2b_sandbox`). Совместно с
    ``capabilities = [{ name = "code.execute" }]`` требуется явное
    разрешение Capability Gate.

    Attributes:
        enabled: Включить sandbox-обёртку для плагина (default OFF).
        mode: ``"e2b"`` — делегация в e2b backend; ``"none"`` — без
            sandbox (только декларативно). RestrictedPython не
            подключаем (нет wheels для Python 3.14).
        max_memory_mb: Лимит RSS-памяти (psutil enforcement).
        max_cpu_seconds: Лимит CPU-времени на одно исполнение.
        allow_imports: Whitelist модулей, импорт которых разрешён в
            sandbox. Пустой кортеж — стандартный набор e2b.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    mode: Literal["e2b", "none"] = "e2b"
    max_memory_mb: int = Field(default=512, ge=16, le=8192)
    max_cpu_seconds: int = Field(default=30, ge=1, le=600)
    allow_imports: tuple[str, ...] = ()


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
    compatibility: PluginCompatibility = Field(default_factory=PluginCompatibility)
    sandbox: PluginSandbox | None = None

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
