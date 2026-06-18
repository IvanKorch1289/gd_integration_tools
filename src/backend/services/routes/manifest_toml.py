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
from src.backend.core.utils.route_timeout import RouteTimeoutSpec

__all__ = ("RouteManifestError", "RouteManifest", "load_route_manifest")


class _RouteTimeoutModel(BaseModel):
    """Pydantic-обёртка над :class:`RouteTimeoutSpec` для парсинга TOML.

    Использует ``extra="forbid"`` чтобы поймать опечатки в ``[timeout]``
    секции на этапе load (вместо silent ignore).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    connect: float | None = Field(default=None, gt=0)
    read: float | None = Field(default=None, gt=0)
    write: float | None = Field(default=None, gt=0)
    total: float | None = Field(default=None, gt=0)

    def to_spec(self) -> RouteTimeoutSpec:
        """S163 W24 fix: конвертация pydantic-модели → frozen dataclass.

        NOTE: после W17 (добавление _RouteTransportModel) to_spec случайно
        попал в неправильный класс. W24 переносит обратно.
        """
        return RouteTimeoutSpec(
            connect=self.connect, read=self.read, write=self.write, total=self.total
        )


class _RouteTransportModel(BaseModel):
    """S163 W17: per-transport overrides в ``[transport]`` секции route.toml.

    Override values для стандартных settings (WSSettings, GRPCSettings,
    GraphQLSettings и т.п.) на уровне route. Читаются handlers через
    ``DslService.get_route_overrides(route_id)``.

    Example route.toml::

        [transport]
        pool_size = 100              # WS max_connections, gRPC max_concurrent_streams
        message_timeout_s = 15.0     # WS per-message timeout
        max_message_size = 131072    # WS max_message_size
        default_timeout_s = 30.0     # gRPC unary call timeout
        max_message_size_bytes = 4194304  # gRPC max incoming message
        query_timeout_s = 10.0       # GraphQL query timeout

    Не все поля применимы ко всем transports (handlers фильтруют по имени).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Pool / concurrency.
    pool_size: int | None = Field(default=None, gt=0)

    # Timeouts (seconds).
    message_timeout_s: float | None = Field(default=None, gt=0)
    default_timeout_s: float | None = Field(default=None, gt=0)
    query_timeout_s: float | None = Field(default=None, gt=0)

    # Message size limits (bytes).
    max_message_size: int | None = Field(default=None, gt=0)
    max_message_size_bytes: int | None = Field(default=None, gt=0)


class RouteManifestError(ValueError):
    """Ошибка парсинга / валидации `route.toml`."""


class _IPRestrictionModel(BaseModel):
    """Pydantic-модель для ``[security.ip_restriction]`` в route.toml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_ips: tuple[str, ...] = Field(
        default_factory=tuple, description="Разрешённые IP/CIDR для доступа к маршруту."
    )
    enabled: bool = Field(default=True, description="Включено ли ограничение.")
    path_pattern: str | None = Field(
        default=None,
        description="Glob-паттерн пути. Если не задан — /api/v1/auto/<route_name>.",
    )


class _SecurityModel(BaseModel):
    """Pydantic-модель для секции ``[security]`` в route.toml.

    Использует ``extra="forbid"`` чтобы поймать опечатки в полях
    секции на этапе load.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    requires_permission: tuple[str, ...] = Field(
        default_factory=tuple,
        description=(
            'Список required permissions в формате "role:<role_name>" или '
            '"scope:<scope_name>". При route_authz_requires_permission=True '
            "AuthorizationGateway проверяет наличие всех перечисленных "
            "permissions у principal перед dispatch на route."
        ),
    )
    ip_restriction: _IPRestrictionModel | None = Field(
        default=None, description="Per-route IP-ограничения."
    )


class RouteManifest(BaseModel):
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
        security: Опц. секция ``[security]`` с requires_permission.
            K3 S19 W3: route_authz_requires_permission feature flag
            активирует проверку permissions через AuthorizationGateway.
        timeout: Конфигурация таймаутов (connect / read / write / total).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    requires_core: str = Field(min_length=1)
    requires_plugins: dict[str, str] = Field(default_factory=dict)
    requires_workflows: dict[str, str] = Field(default_factory=dict)
    tenant_aware: bool = False
    feature_flag: str | bool | None = None
    tags: tuple[str, ...] = ()
    description: str | None = None
    pipelines: tuple[str, ...] = Field(min_length=1)
    capabilities: tuple[CapabilityRef, ...] = ()
    security: _SecurityModel | None = None
    timeout: _RouteTimeoutModel | None = None
    transport: _RouteTransportModel | None = None  # S163 W17

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

    @field_validator("requires_workflows")
    @classmethod
    def _validate_workflow_specs(cls, value: dict[str, str]) -> dict[str, str]:
        """Валидирует каждый spec в ``requires_workflows`` как PEP-440 SemVer."""
        for workflow_name, spec in value.items():
            try:
                SpecifierSet(spec)
            except InvalidSpecifier as exc:
                raise ValueError(
                    f"Invalid requires_workflows spec for {workflow_name!r}: {spec!r}"
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

    def missing_workflows(self, available: dict[str, str]) -> dict[str, str]:
        """Возвращает workflows, которых не хватает или несовместимых.

        Args:
            available: ``{workflow_name: installed_version}``.

        Returns:
            ``{workflow_name: required_spec}`` для отсутствующих или
            не подходящих по spec'у workflows.
        """
        missing: dict[str, str] = {}
        for workflow_name, spec in self.requires_workflows.items():
            installed = available.get(workflow_name)
            if installed is None or not SpecifierSet(spec).contains(installed):
                missing[workflow_name] = spec
        return missing


def load_route_manifest(path: Path | str) -> RouteManifest:
    """Прочитать и валидировать ``route.toml``.

    Args:
        path: Путь к файлу манифеста.

    Returns:
        Валидированный :class:`RouteManifest`.

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
        return RouteManifest.model_validate(raw)
    except Exception as exc:
        raise RouteManifestError(
            f"Manifest validation failed for {file_path}: {exc}"
        ) from exc
