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

__all__ = ("RouteManifest", "RouteManifestError", "load_route_manifest")

_FEATURE_FLAG_TABLE_KEYS = ("enabled", "gate", "name")
"""Допустимые ключи табличной формы ``feature_flag`` в route.toml."""


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


class _RouteSLOModel(BaseModel):
    """ADR-0079 — inline SLO-декларация маршрута в ``route.toml``.

    Поддерживает обе авторские формы:

    * Form A (плоская, ``slo = { p95_ms = 500, timeout_ms = 5000 }``);
    * Form B (секция ``[route.slo]`` — составные маршруты).

    Набор полей взят из ADR-0079: ``p95_ms`` (обязателен, > 0),
    ``p99_ms``, ``timeout_ms``, ``rps_target`` (опциональны, > 0).
    ``extra="forbid"`` — опечатка в ключе SLO валит load, а не
    молча игнорируется.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    p95_ms: int = Field(gt=0, description="SLO-цель: p95-латентность, мс.")
    p99_ms: int | None = Field(
        default=None, gt=0, description="SLO-цель: p99-латентность, мс."
    )
    timeout_ms: int | None = Field(
        default=None, gt=0, description="Жёсткий таймаут обработчика маршрута, мс."
    )
    rps_target: int | None = Field(
        default=None, gt=0, description="Целевой RPS (capacity planning)."
    )


class _RouteFeatureFlagsModel(BaseModel):
    """Секция ``[feature_flags]`` — список разрешённых feature-flags маршрута.

    Генерируется route-wizard'ом (``tools/wizards/route_templates.py``)
    вместе с плоским манифестом, поэтому модель обязана его принимать.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    default: tuple[str, ...] = Field(
        default_factory=tuple, description="Имена флагов, доступных маршруту."
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
        schedule: Планировщик запуска маршрута (``"never"`` — только
            on-demand вызов). R-V15-2 объявляет ``schedule`` частью
            манифеста; scaffold/wizard пишут ``schedule = "never"``.
        slo: ADR-0079 inline-SLO (``p95_ms`` обязателен, ``p99_ms`` /
            ``timeout_ms`` / ``rps_target`` опциональны).
        feature_flags: Секция ``[feature_flags]`` со списком
            разрешённых feature-flags маршрута (генерируется wizard'ом).

    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z][a-z0-9_]*$")
    version: str = Field(min_length=1)
    requires_core: str = Field(min_length=1)
    requires_plugins: dict[str, str] = Field(default_factory=dict)
    requires_workflows: dict[str, str] = Field(default_factory=dict)
    tenant_aware: bool = False
    feature_flag: str | bool | None = None
    feature_flags: _RouteFeatureFlagsModel | None = None
    tags: tuple[str, ...] = ()
    description: str | None = None
    pipelines: tuple[str, ...] = Field(min_length=1)
    capabilities: tuple[CapabilityRef, ...] = ()
    security: _SecurityModel | None = None
    timeout: _RouteTimeoutModel | None = None
    transport: _RouteTransportModel | None = None  # S163 W17
    schedule: str | None = None  # R-V15-2; "never" — только on-demand
    slo: _RouteSLOModel | None = None  # ADR-0079 inline-SLO

    @field_validator("feature_flag", mode="before")
    @classmethod
    def _normalize_feature_flag(cls, value: object) -> object:
        """Приводит табличную форму ``feature_flag`` к ``str``/``bool``.

        В репозитории сосуществуют четыре авторские формы:

        * ``feature_flag = "ROUTE_X_ENABLED"`` — строка (ADR-043, тесты);
        * ``feature_flag = true`` — статический вкл./выкл.;
        * ``feature_flag = { enabled = true, gate = "x_enabled" }`` —
          inline-таблица route-wizard'а
          (``tools/wizards/route_templates.py``);
        * ``[route.feature_flag] name = "..."`` — секция ADR-0079
          Form B (композитные маршруты).

        Маппинг выбран в пользу существующей семантики
        :meth:`RouteLoader._resolve_feature_flag`: идентификатор флага
        (``gate``/``name``) отдаётся строкой — резолвится через
        feature-flag-resolver (ENV / dotted-path), явный
        ``enabled = false`` — жёстким выключением. Неизвестные ключи
        таблицы отвергаются (строгость ``extra="forbid"`` не теряется).
        """
        if not isinstance(value, dict):
            return value
        unknown = set(value) - set(_FEATURE_FLAG_TABLE_KEYS)
        if unknown:
            raise ValueError(
                f"feature_flag table has unknown keys {sorted(unknown)}; "
                f"allowed: {list(_FEATURE_FLAG_TABLE_KEYS)}"
            )
        enabled = value.get("enabled")
        if isinstance(enabled, bool) and not enabled:
            return False
        for key in ("gate", "name"):
            flag = value.get(key)
            if isinstance(flag, str) and flag.strip():
                return flag
        if isinstance(enabled, bool):
            return enabled
        raise ValueError(
            "feature_flag table must declare 'enabled' (bool) or "
            "'gate'/'name' (str) — got keys "
            f"{sorted(value)}"
        )

    @field_validator("capabilities", mode="before")
    @classmethod
    def _normalize_capabilities(cls, value: object) -> object:
        """Приводит строковую форму ``capabilities`` к ``{name, scope}``.

        Поддерживаются обе авторские формы:

        * ``capabilities = ["net.outbound", "db.write"]`` — плоские строки
          (генерируются route-wizard'ом и ``tools/scaffold_route.py``);
        * ``capabilities = ["net.outbound:*.example.com"]`` — компактная
          форма ``"name:scope"``; разделитель — первое ``":"``, ровно как
          в ``tools/codegen_plugin.py`` (``cap.split(":", 1)``);
        * ``[[capabilities]] name/scope`` — табличная форма ADR-044
          (используется в ``plugin.toml`` и в тестах).

        Имя ДОЛЖНО соответствовать грамматике ``<resource>.<verb>``
        из :data:`CAPABILITY_NAME_PATTERN` — проверку выполняет
        :class:`CapabilityRef`. Многосегментные имена вида
        ``jupyter.hub.run`` в компактной строке недопустимы: их нельзя
        однозначно отличить от легальных vocabulary-имён
        (``pii.tokenize.reversible``), поэтому такие capability
        объявляются таблицей ``[[capabilities]]`` с явным ``scope``.
        """
        if not isinstance(value, (list, tuple)):
            return value
        normalized: list[object] = []
        for item in value:
            if not isinstance(item, str):
                normalized.append(item)  # таблица — валидирует CapabilityRef
                continue
            name, sep, scope = item.partition(":")
            name = name.strip()
            if not name:
                raise ValueError(f"Empty capability name in {item!r}")
            entry: dict[str, str] = {"name": name}
            if sep and scope.strip():
                entry["scope"] = scope.strip()
            normalized.append(entry)
        return normalized

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


def _unwrap_route_envelope(
    raw: dict[str, object], file_path: Path
) -> dict[str, object]:
    """Развернуть конверт ``[route]`` в плоский input для :class:`RouteManifest`.

    Поддерживаются две взаимно-исключающие формы манифеста:

    * **плоская** — поля верхнего уровня (``name``, ``version``, …);
      канонична для ADR-043, ``tools/wizards/route_templates.py`` и
      ``tools/migrate_dsl_routes_to_v11.py``;
    * **конверт ``[route]``** — всё внутри секции ``[route]``
      (``[route.slo]``, ``[route.feature_flag]``, …); канонична для
      ADR-0079 Form B и составных маршрутов.

    Args:
        raw: Разобранный TOML-верхний уровень.
        file_path: Путь к манифесту (для сообщений об ошибках).

    Returns:
        Плоский dict, готовый для :meth:`RouteManifest.model_validate`.

    Raises:
        RouteManifestError: Смешение форм, ``[route]`` не является
            таблицей, секция ``[route]`` пуста или не распознан ни
            одна из форм.

    """
    if "route" not in raw:
        if "name" not in raw:
            raise RouteManifestError(
                f"Manifest must be flat or wrapped in a [route] section, "
                f"got top-level keys {sorted(raw)}: {file_path}"
            )
        return raw

    envelope = raw["route"]
    if not isinstance(envelope, dict):
        raise RouteManifestError(
            f"Section [route] must be a TOML table, got "
            f"{type(envelope).__name__}: {file_path}"
        )
    outer = sorted(key for key in raw if key != "route")
    if outer:
        raise RouteManifestError(
            f"Manifest mixes flat fields {outer} with a [route] section; "
            f"use one form only: {file_path}"
        )
    if not envelope:
        raise RouteManifestError(f"Section [route] is empty: {file_path}")
    return envelope


def load_route_manifest(path: Path | str) -> RouteManifest:
    """Прочитать и валидировать ``route.toml``.

    Принимает обе авторские формы манифеста:

    * **плоскую** — поля верхнего уровня (``name``, ``version``,
      ``requires_core``, ``pipelines``, …). Канонична для ADR-043,
      ``tools/wizards/route_templates.py`` и тестов.
    * **конверт ``[route]``** — те же поля внутри секции ``[route]``
      (ADR-0079 Form B: ``[route.slo]``, ``[route.feature_flag]``).

    Табличная форма ``feature_flag`` (``{ enabled, gate }`` /
      ``{ name }``) сводится к ``str``/``bool``, строковые
      ``capabilities`` (``"name"`` / ``"name:scope"``) — к
      ``{name, scope}``; см. соответствующие валидаторы модели.

    Args:
        path: Путь к файлу манифеста.

    Returns:
        Валидированный :class:`RouteManifest`.

    Raises:
        RouteManifestError: Файл не найден, TOML невалиден, форма
            манифеста не распознана/смешана или модель не прошла
            pydantic-валидацию.

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
        flat = _unwrap_route_envelope(raw, file_path)
        return RouteManifest.model_validate(flat)
    except RouteManifestError:
        raise
    except Exception as exc:
        raise RouteManifestError(
            f"Manifest validation failed for {file_path}: {exc}"
        ) from exc
