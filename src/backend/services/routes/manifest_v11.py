"""ADR-043 (R1.2a) — `route.toml` манифест маршрута V11.

Pydantic-модель + TOML-loader для V11-манифеста маршрута. Маршруты
живут в ``routes/<name>/route.toml`` + ``*.dsl.yaml`` (multi-pipeline
поддерживается через ``pipelines``).

Этот модуль **не подключается** к DSL-движку в текущей итерации —
:class:`RouteLoader` будет реализован в Wave R1.2a-импл и
интегрирован в lifespan после :class:`PluginLoader`.

Связанные ADR: ADR-042, ADR-043, ADR-044.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.backend.core.security.capabilities import CapabilityRef

__all__ = ("RouteManifestError", "RouteManifestV11", "load_route_manifest")


class RouteManifestError(ValueError):
    """Ошибка парсинга / валидации `route.toml`."""


class RouteManifestV11(BaseModel):
    """Манифест маршрута V11 (``routes/<name>/route.toml``).

    См. ADR-043 для полного описания формата, lifecycle и
    invariant'а ``route.capabilities ⊆ union(plugins.capabilities)``.

    Attributes:
        name: snake_case-имя маршрута; совпадает с каталогом
            ``routes/<name>/``.
        version: SemVer-строка маршрута.
        requires_core: PEP-440 SpecifierSet — диапазон версий ядра.
        requires_plugins: Mapping ``plugin_name → SemVer-spec`` для
            плагинов, чьи Processor/Source/Sink/Action использует
            pipeline.
        tenant_aware: Если ``True`` — pipeline сознательно работает
            в TenantContext.
        feature_flag: ``True``/``False`` (статически вкл./выкл.),
            ``str`` (имя ENV или dotted-path к
            ``IFeatureFlagProvider``), ``None`` (по умолчанию вкл.).
        tags: Тэги для admin-grouping и DSL-Linter.
        description: Опц. человекочитаемая аннотация.
        pipelines: Список path'ей ``*.dsl.yaml`` относительно
            ``routes/<name>/`` (главный — первый, остальные — fragments).
        capabilities: Декларация runtime-gate (см. ADR-044).
            Должна быть подмножеством объединения capabilities
            требуемых плагинов + публичных capabilities ядра
            (проверка в :class:`RouteLoader`, а не в pydantic).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    requires_core: str = Field(min_length=1)
    requires_plugins: dict[str, str] = Field(default_factory=dict)
    tenant_aware: bool = False
    feature_flag: str | bool | None = None
    tags: tuple[str, ...] = ()
    description: str | None = None
    pipelines: tuple[str, ...] = Field(min_length=1)
    capabilities: tuple[CapabilityRef, ...] = ()

    @field_validator("requires_core")
    @classmethod
    def _validate_core_spec(cls, value: str) -> str:
        """Валидирует ``requires_core`` как PEP-440 SpecifierSet."""
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError(f"Invalid requires_core spec: {value!r}") from exc
        return value

    @field_validator("requires_plugins")
    @classmethod
    def _validate_plugin_specs(cls, value: dict[str, str]) -> dict[str, str]:
        """Валидирует каждый spec в ``requires_plugins`` как PEP-440."""
        for plugin_name, spec in value.items():
            try:
                SpecifierSet(spec)
            except InvalidSpecifier as exc:
                raise ValueError(
                    f"Invalid requires_plugins spec for {plugin_name!r}: {spec!r}"
                ) from exc
        return value

    def is_compatible_with_core(self, core_version: str) -> bool:
        """Совместим ли маршрут с заданной версией ядра."""
        return core_version in SpecifierSet(self.requires_core)

    def missing_plugins(self, available: dict[str, str]) -> dict[str, str]:
        """Возвращает плагины, которых не хватает или несовместимых.

        Args:
            available: ``{plugin_name: installed_version}``.

        Returns:
            ``{plugin_name: required_spec}`` для отсутствующих или
            не подходящих по spec'у плагинов.
        """
        missing: dict[str, str] = {}
        for plugin_name, spec in self.requires_plugins.items():
            installed = available.get(plugin_name)
            if installed is None or installed not in SpecifierSet(spec):
                missing[plugin_name] = spec
        return missing


def load_route_manifest(path: Path | str) -> RouteManifestV11:
    """Прочитать и валидировать ``route.toml``.

    Args:
        path: Путь к файлу манифеста.

    Returns:
        Валидированный :class:`RouteManifestV11`.

    Raises:
        RouteManifestError: Файл не найден, TOML невалиден или
            модель не прошла pydantic-валидацию.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise RouteManifestError(f"Manifest not found: {file_path}")
    try:
        raw = tomllib.loads(file_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RouteManifestError(f"Invalid TOML in {file_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RouteManifestError(
            f"Manifest must be a TOML table, got {type(raw).__name__}: {file_path}"
        )
    try:
        return RouteManifestV11.model_validate(raw)
    except Exception as exc:
        raise RouteManifestError(
            f"Manifest validation failed for {file_path}: {exc}"
        ) from exc
