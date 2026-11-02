"""Merged-валидация профиля конфигурации (ADR-0375, wave 14 — ЧАСТЬ B).

Зачем
-----
``manage.py validate-profile`` проверял ТОЛЬКО overlay-файл профиля. Но
приложение читает СЛИЯННЫЙ конфиг (``base.yml`` + overlay через
``_deep_merge`` в ``YamlConfigSettingsLoader``), поэтому инварианты,
объявленные в ``base.yml`` (например ``http.ssl_verify``,
``vault.addr``, ``graphql.enable_introspection``), были не видны
валидатору — «зелёный» отчёт не означал «конфиг валиден».

Этот модуль собирает merged-конфиг ровно так же, как это делает рантайм,
и прогоняет по нему :class:`ConfigValidator`.

Особенности
-----------
* секреты не нужны: секции собираются через ``model_construct`` — берутся
  значения из YAML, а отсутствующие (секретные) поля остаются на дефолтах
  модели; ``model_construct`` не валидирует, поэтому ``ValidationError``
  из-за отсутствующих ``password``/``secret_key`` не возникает;
* ``features`` — отдельная группа (в корневом ``Settings`` её нет),
  поэтому контейнер настроек профиля объявляет её явно;
* секция ``constants`` проверяется ОТДЕЛЬНО (ADR-0377): у неё нет
  ограничений уровня «контейнера» — значения применяются к глобальному
  синглтону ``consts``, поэтому невалидное значение роняет старт;
* ADR-0407 — контракты прод-значений: WAF-allowlist обязан покрывать
  внешние интеграции, loopback в allowlist оправдан локальной
  зависимостью, ``database.replica_dsn=null`` допустим (реплика не
  развёрнута).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, ValidationError, create_model
from pydantic_settings import BaseSettings

from src.backend.core.config.base import AppBaseSettings
from src.backend.core.config.config_loader import _deep_merge, repo_root
from src.backend.core.config.constants_settings import ConstantsSettings
from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.external_databases.registry import (
    ExternalDatabasesSettings,
)
from src.backend.core.config.features import FeatureFlags
from src.backend.core.config.security import SecureSettings
from src.backend.core.config.services.cache import RedisSettings
from src.backend.core.config.validator._helpers import ConfigSeverity, ConfigViolation
from src.backend.core.config.vault import VaultSettings
from src.backend.core.config.waf import WafSettings

__all__ = (
    "ProfileSettings",
    "build_profile_settings",
    "load_profile_yaml",
    "merge_profile_yaml",
    "validate_profile_config",
)

#: Loopback-хосты, недоступные в prod (ADR-0403).
_LOOPBACK_HOSTNAMES: frozenset[str] = frozenset(
    {"localhost", "127.0.0.1", "0.0.0.0", "::1", "0:0:0:0:0:0:0:1"}
)

#: Окружения с прод-контрактами значений (ADR-0407).
_PRODUCTION_LIKE_ENVIRONMENTS: Final[frozenset[str]] = frozenset(
    {"production", "staging"}
)

#: Внешние интеграции (``src/backend/services/integrations/**``) и их
#: endpoint'ы в merged-конфиге. Хост каждого endpoint'а обязан быть в
#: ``waf.allow_hosts`` при ``waf.strict=true`` (ADR-0407).
_EXTERNAL_INTEGRATION_ENDPOINTS: Final[tuple[tuple[str, str], ...]] = (
    ("skb", "prod_url"),
    ("dadata", "base_url"),
)

#: Локальные (sidecar) зависимости, обслуживаемые через loopback
#: (ADR-0407). Формат: (секция, ключ endpoint'а, ключ флага включения).
#: Loopback-запись в ``waf.allow_hosts`` оправдана, только если хотя бы одна
#: из них включена и указывает на loopback-хост.
_LOCAL_ENDPOINT_PROBES: Final[tuple[tuple[str, str, str], ...]] = (
    ("waf", "clamav_host", "clamav_enabled"),
    ("app", "opentelemetry_endpoint", ""),
)

_CONSTANTS_PROBE: type[BaseModel] = create_model(
    "ConstantsProbe",
    __config__=ConfigDict(extra="ignore"),
    **{
        name: (field.annotation, field)
        for name, field in ConstantsSettings.model_fields.items()
    },
)
"""Модель-зонд для секции ``constants`` (ADR-0377).

Отдельная модель — намеренно: у :class:`ConstantsSettings` есть
``model_post_init``, который применяет значения к глобальному синглтону
``consts``. Валидатор профиля не имеет права менять рантайм-состояние,
поэтому зонд собран из тех же полей (с теми же ограничениями), но без
post-init. ``extra="ignore"`` повторяет поведение YAML-источника:
неизвестные ключи отбрасываются с warning'ом, а не роняют валидацию.
"""


class ProfileSettings(BaseSettings):
    """Минимальный контейнер секций, которые проверяет ``ConfigValidator``.

    Собран из merged-YAML через ``model_construct`` — без валидации и без
    обращения к env/Vault: CLI-валидация профиля не должна требовать
    секретов (их подставляет рантайм).
    """

    app: AppBaseSettings
    secure: SecureSettings
    vault: VaultSettings
    database: DatabaseConnectionSettings
    external_databases: ExternalDatabasesSettings
    redis: RedisSettings
    features: FeatureFlags


def _profiles_dir(profiles_dir: Path | None = None) -> Path:
    """Каталог с YAML-профилями.

    Args:
        profiles_dir: Явный каталог (для тестов). По умолчанию —
            ``<repo_root>/config_profiles``.

    Returns:
        Путь к каталогу профилей.
    """
    return profiles_dir if profiles_dir is not None else repo_root() / "config_profiles"


def load_profile_yaml(profile: str, profiles_dir: Path | None = None) -> dict[str, Any]:
    """Читает overlay-файл профиля.

    Args:
        profile: Имя профиля (``dev``/``dev_light``/``staging``/``prod``).
        profiles_dir: Каталог профилей (по умолчанию — репозиторный).

    Returns:
        Разобранный mapping (пустой dict для пустого файла).

    Raises:
        FileNotFoundError: Файла профиля нет.
        RuntimeError: YAML невалиден.

    """
    import yaml

    path = _profiles_dir(profiles_dir) / f"{profile}.yml"
    if not path.is_file():
        raise FileNotFoundError(str(path))
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Profile must be a YAML mapping: {path}")
    return data


def merge_profile_yaml(
    profile: str, profiles_dir: Path | None = None
) -> dict[str, Any]:
    """Сливает ``base.yml`` + overlay профиля (как в ``config_loader``).

    Args:
        profile: Имя профиля.
        profiles_dir: Каталог профилей (по умолчанию — репозиторный).

    Returns:
        Итоговый конфиг после слияния.

    Raises:
        FileNotFoundError: Нет base.yml или overlay-файла профиля.

    """
    directory = _profiles_dir(profiles_dir)
    base_path = directory / "base.yml"
    if not base_path.is_file():
        raise FileNotFoundError(str(base_path))
    import yaml

    with base_path.open("r", encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    if not isinstance(base, dict):
        raise RuntimeError(f"Base profile must be a YAML mapping: {base_path}")
    return _deep_merge(base, load_profile_yaml(profile, profiles_dir))


def _construct(model_cls: type[Any], section: dict[str, Any] | None) -> Any:
    """Собирает экземпляр модели из YAML-секции (без валидации).

    Args:
        model_cls: Pydantic-модель настроек.
        section: YAML-секция (может быть пустой).

    Returns:
        Экземпляр модели с значениями из YAML и дефолтами модели.
    """
    values = {
        key: value
        for key, value in (section or {}).items()
        if key in model_cls.model_fields
    }
    return model_cls.model_construct(**values)


def build_profile_settings(merged: dict[str, Any]) -> ProfileSettings:
    """Собирает контейнер настроек профиля из merged-конфига.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Экземпляр :class:`ProfileSettings` для :class:`ConfigValidator`.

    """
    return ProfileSettings.model_construct(
        app=_construct(AppBaseSettings, merged.get("app")),
        secure=_construct(SecureSettings, merged.get("security")),
        vault=_construct(VaultSettings, merged.get("vault")),
        database=_construct(DatabaseConnectionSettings, merged.get("database")),
        external_databases=_construct(
            ExternalDatabasesSettings, merged.get("external_databases")
        ),
        redis=_construct(RedisSettings, merged.get("redis")),
        features=_construct(FeatureFlags, merged.get("features")),
    )


def _validate_model_section(
    model_cls: type[Any], section: dict[str, Any] | None, section_name: str
) -> tuple[ConfigViolation, ...]:
    """Валидирует секцию merged-конфига pydantic-моделью (ADR-0385, A9).

    ``ProfileSettings`` собирается через ``model_construct`` (без
    валидации — CLI не должен требовать секреты), поэтому ограничения
    полей секций БД (``pool_size >= 1``, ``port < 65536``, ``extra=forbid``)
    не проверялись: битые значения проходили с exit 0 и роняли старт.

    Args:
        model_cls: Pydantic-модель секции.
        section: YAML-секция merged-конфига (может быть пустой).
        section_name: Имя секции (для кода нарушения и подсказки).

    Returns:
        Кортеж нарушений (по одному на ошибочное поле).

    """
    if not section:
        return ()
    try:
        model_cls.model_validate(section)
    except ValidationError as exc:
        return tuple(
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code=f"{section_name}.invalid",
                message=(
                    f"Некорректное значение в секции {section_name}: "
                    f"{_field_path(error['loc'])} — {error['msg']}"
                ),
                field=f"{section_name}.{_field_path(error['loc'])}",
                recommendation=(
                    f"Исправить значение в секции {section_name} файла "
                    "config_profiles/base.yml (или overlay профиля)."
                ),
                context={"input": error.get("input")},
            )
            for error in exc.errors()
        )
    return ()


def _validate_constants_section(section: dict[str, Any]) -> tuple[ConfigViolation, ...]:
    """Валидирует секцию ``constants`` merged-конфига.

    Ограничения полей (``ge=0``, ``gt=0.0``, …) проверяются моделью
    :class:`ConstantsSettings`; рантайм применяет эти значения к
    синглтону ``consts`` при создании модели, поэтому невалидное
    значение роняет старт процесса — валидатор профиля обязан ловить
    его ДО деплоя (ADR-0377).

    Args:
        section: Секция ``constants`` merged-конфига (может быть пустой).

    Returns:
        Кортеж нарушений (по одному на ошибочное поле).

    """
    if not section:
        return ()
    try:
        _CONSTANTS_PROBE.model_validate(section)
    except ValidationError as exc:
        return tuple(
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="constants.invalid",
                message=(
                    "Некорректное значение в секции constants: "
                    f"{_field_path(error['loc'])} — {error['msg']}"
                ),
                field=f"constants.{_field_path(error['loc'])}",
                recommendation=(
                    "Исправить значение в секции constants файла "
                    "config_profiles/base.yml."
                ),
                context={"input": error.get("input")},
            )
            for error in exc.errors()
        )
    return ()


def _field_path(location: tuple[Any, ...]) -> str:
    """Собирает dot-path из ``loc`` ошибки pydantic-валидации.

    Args:
        location: Кортеж частей пути из ``ValidationError.errors()``.

    Returns:
        Dot-path вида ``field`` / ``section.field``.

    """
    return ".".join(str(part) for part in location)


def _check_db_call_procedure_flag(
    merged: dict[str, Any],
) -> tuple[ConfigViolation, ...]:
    """ADR-0389: внешняя БД в профиле, а флаг ``db_call_procedure`` выключен.

    Флаг ``db_call_procedure_enabled`` — default-OFF (ADR-0380), поэтому
    вызовы stored procedure в профиле без явного включения флага молча
    пропускаются (``skipped``). Чтобы это было видно ДО деплоя, профиль с
    объявленными внешними БД и выключенным флагом даёт WARNING.

    Сигналом служат сами внешние подключения: в конфигурации нет отдельного
    поля «процедура», а ``schema`` профиля — это контейнер
    view/procedure/function (``ExternalDatabaseItemSettings.db_schema``).

    Severity — WARNING, а не CRITICAL: профиль может объявлять внешнюю БД
    вовсе без вызовов процедур (тогда флаг выключен правильно).

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Кортеж нарушений (пустой — если нарушения нет).

    """
    features = merged.get("features") or {}
    if features.get("db_call_procedure_enabled"):
        return ()
    connections = (merged.get("external_databases") or {}).get("connections") or []
    profiles = [
        str(connection.get("profile_name") or connection.get("name"))
        for connection in connections
        if isinstance(connection, dict) and connection.get("enabled", True)
    ]
    if not profiles:
        return ()
    return (
        ConfigViolation(
            severity=ConfigSeverity.WARNING,
            code="feature_flag.db_call_procedure_disabled",
            message=(
                "В профиле объявлены внешние БД ("
                f"{', '.join(profiles)}), но feature-флаг "
                "'db_call_procedure_enabled' выключен (default-OFF, ADR-0389): "
                "шаги db_call_procedure будут пропущены (skipped) без ошибки."
            ),
            field="features.db_call_procedure_enabled",
            recommendation=(
                "Если вызовы stored procedure нужны — включите флаг в overlay "
                "профиля (features.db_call_procedure_enabled: true) либо env "
                "FEATURE_DB_CALL_PROCEDURE_ENABLED=true. Если не нужны — "
                "оставьте флаг выключенным и удалите внешние БД из профиля."
            ),
            context={"external_db_profiles": profiles},
        ),
    )


def _check_capability_gate_policy(
    merged: dict[str, Any],
) -> tuple[ConfigViolation, ...]:
    """ADR-0393: capability-гейт в prod/staging обязан быть включён.

    Политика (ADR-0393, «Политика capability-гейта»):

    * ``dsl_capability_gate_enabled`` — runtime-enforcement capability-гейта
      DSL-процессоров (ADR-0366). В prod/staging обязан быть ``true``:
      иначе отказ capability-гейта неотличим от «сломанного шага», а
      БД-шаги (без ``required_capability``) читают/пишут любую БД;
    * ``dsl_capability_core_baseline_enabled`` — выдача capability ядра всем
      роутам подряд. В prod/staging обязан быть ``false`` (least
      privilege): baseline маскирует отсутствие деклараций в route.toml.

    Проверяется по merged-конфигу (base + overlay) — как в рантайме.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Кортеж нарушений (пустой — если нарушений нет).

    """
    app = merged.get("app") or {}
    environment = str(app.get("environment") or "").lower()
    if environment not in {"production", "staging"}:
        return ()

    features = merged.get("features") or {}
    violations: list[ConfigViolation] = []

    if not features.get("dsl_capability_gate_enabled"):
        violations.append(
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="feature_flag.dsl_capability_gate_disabled",
                message=(
                    "В профиле '%s' выключен capability-гейт DSL-процессоров "
                    "(features.dsl_capability_gate_enabled=false): БД- и "
                    "RPA-шаги не проходят авторизацию, а отказ capability-гейта "
                    "неотличим от «сломанного шага» (ADR-0393)."
                ),
                field="features.dsl_capability_gate_enabled",
                recommendation=(
                    "Включите features.dsl_capability_gate_enabled: true в "
                    "overlay профиля (или env FEATURE_DSL_CAPABILITY_GATE_ENABLED=true)."
                ),
                context={"environment": environment},
            )
        )

    if features.get("dsl_capability_core_baseline_enabled"):
        violations.append(
            ConfigViolation(
                severity=ConfigSeverity.WARNING,
                code="feature_flag.dsl_capability_core_baseline_enabled",
                message=(
                    "В профиле '%s' включён core-baseline capability-гейта: "
                    "любой роут получает capability ядра (в т.ч. rpa.*) без "
                    "декларации в route.toml — это least-privilege-нарушение "
                    "(ADR-0393)."
                ),
                field="features.dsl_capability_core_baseline_enabled",
                recommendation=(
                    "Выключите features.dsl_capability_core_baseline_enabled "
                    "после того, как роуты объявят нужные capability явно."
                ),
                context={"environment": environment},
            )
        )

    return tuple(violations)


def _check_graphql_introspection_policy(
    merged: dict[str, Any],
) -> tuple[ConfigViolation, ...]:
    """ADR-0400: в prod/staging интроспекция GraphQL обязана быть выключена.

    Ключ ``graphql.enable_introspection`` декларативен (base/prod/staging.yml),
    но раньше его значение никто не проверял — «выключено в конфиге» и
    «разрешено в рантайме» могли разойтись (раньше ``graphql_guards``
    смотрел только на окружение). Интроспекция — recon-поверхность,
    поэтому в prod/staging значение ``true`` — CRITICAL.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Кортеж нарушений (пустой — если нарушения нет).

    """
    app = merged.get("app") or {}
    environment = str(app.get("environment") or "").lower()
    if environment not in {"production", "staging"}:
        return ()
    graphql_cfg = merged.get("graphql") or {}
    if not graphql_cfg.get("enable_introspection", False):
        return ()
    return (
        ConfigViolation(
            severity=ConfigSeverity.CRITICAL,
            code="graphql.introspection_enabled_in_prod",
            message=(
                "В профиле '%s' включена интроспекция GraphQL "
                "(graphql.enable_introspection=true): recon-поверхность "
                "в production (ADR-0400)."
            ),
            field="graphql.enable_introspection",
            recommendation=(
                "Установите graphql.enable_introspection: false в "
                "config_profiles/base.yml (или в overlay профиля)."
            ),
            context={"environment": environment},
        ),
    )


def _is_production(merged: dict[str, Any]) -> bool:
    """Ты ли окружение — production.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        ``True`` — если ``app.environment == "production"``.

    """
    app = merged.get("app") or {}
    return str(app.get("environment") or "").lower() == "production"


def _is_production_like(merged: dict[str, Any]) -> bool:
    """Окружение с прод-контрактами значений (production или staging).

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        ``True`` — если окружение production-подобное.

    """
    app = merged.get("app") or {}
    environment = str(app.get("environment") or "").lower()
    return environment in _PRODUCTION_LIKE_ENVIRONMENTS


def _endpoint_host(value: str) -> str:
    """Хост endpoint'а: URL или голый host (с необязательным портом).

    Args:
        value: Значение endpoint'а (``https://host/path`` / ``host`` / ``host:port``).

    Returns:
        Хост в нижнем регистре (пустая строка — хост не разобран).

    """
    text = value.strip()
    if not text:
        return ""
    if "://" in text:
        return (urlparse(text).hostname or "").lower()
    if text.startswith("["):
        closing = text.find("]")
        return (text[1:closing] if closing > 0 else text[1:]).lower()
    return text.split(":", 1)[0].strip().lower()


def _external_integration_hosts(merged: dict[str, Any]) -> dict[str, str]:
    """Хосты внешних интеграций из merged-конфига.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Мапа ``"<section>.<key>"`` → хост интеграции (lowercase).

    """
    hosts: dict[str, str] = {}
    for section, key in _EXTERNAL_INTEGRATION_ENDPOINTS:
        raw = (merged.get(section) or {}).get(key)
        if not raw:
            continue
        host = (urlparse(str(raw)).hostname or "").lower()
        if host:
            hosts[f"{section}.{key}"] = host
    return hosts


def _has_local_loopback_dependency(merged: dict[str, Any]) -> bool:
    """Есть ли в профиле локальная (loopback) зависимость.

    Локальные зависимости prod/staging — sidecar'ы (``clamd``, otel-collector).
    Именно они оправдывают loopback-запись в ``waf.allow_hosts``: без них
    такая запись либо мёртвая, либо внешняя интеграция молча указывает на
    localhost (ADR-0407).

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        ``True`` — если есть включённая зависимость на loopback.

    """
    for section, key, enabled_key in _LOCAL_ENDPOINT_PROBES:
        config = merged.get(section) or {}
        if enabled_key and not config.get(enabled_key):
            continue
        raw = config.get(key)
        if not raw:
            continue
        if _endpoint_host(str(raw)) in _LOOPBACK_HOSTNAMES:
            return True
    return False


def _check_waf_allowlist_covers_integrations(
    merged: dict[str, Any],
) -> tuple[ConfigViolation, ...]:
    """ADR-0407: allowlist WAF обязан покрывать внешние интеграции.

    При ``waf.strict=true`` исходящий запрос к хосту вне ``waf.allow_hosts``
    блокируется (``core/net/waf.py`` → ``WafBypassError``). Запросы
    интеграций (``services/integrations/**``) идут напрямую, минуя WAF-шлюз
    ``http.waf_url``, поэтому непокрытый хост означает полностью сломанную
    интеграцию (СКБ-Техно / DaData).

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Кортеж нарушений (пустой — если нарушения нет).

    """
    if not _is_production_like(merged):
        return ()
    waf = merged.get("waf") or {}
    if not waf.get("strict"):
        return ()  # strict=false — allowlist не ограничивает исходящие запросы
    allowed = {str(host).strip().lower() for host in (waf.get("allow_hosts") or [])}
    missing = {
        field: host
        for field, host in _external_integration_hosts(merged).items()
        if host not in allowed
    }
    if not missing:
        return ()
    return (
        ConfigViolation(
            severity=ConfigSeverity.CRITICAL,
            code="waf.allow_hosts_missing_integration_hosts",
            message=(
                "В профиле с waf.strict=true хосты внешних интеграций не "
                "покрыты allowlist'ом ("
                + ", ".join(f"{field}={host}" for field, host in missing.items())
                + "): исходящие запросы к ним будут заблокированы "
                "(WafBypassError) — интеграция в проде не работает."
            ),
            field="waf.allow_hosts",
            recommendation=(
                "Добавить host'ы внешних интеграций в waf.allow_hosts "
                "overlay'а профиля (config_profiles/prod.yml, staging.yml)."
            ),
            context={"missing": missing, "allow_hosts": sorted(allowed)},
        ),
    )


def _check_waf_loopback_allowlist(
    merged: dict[str, Any],
) -> tuple[ConfigViolation, ...]:
    """ADR-0407: loopback в allowlist WAF — только ради локальной зависимости.

    Loopback-хост в ``waf.allow_hosts`` оправдан, только если в профиле есть
    включённая локальная зависимость (sidecar ``clamd``/otel). Иначе запись
    либо мёртвая, либо (хуже) внешняя интеграция молча указывает на
    localhost: запрос уйдёт на хост, которого в проде нет.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Кортеж нарушений (пустой — если нарушения нет).

    """
    if not _is_production_like(merged):
        return ()
    waf = merged.get("waf") or {}
    loopback_entries = sorted(
        {
            str(host).strip().lower()
            for host in (waf.get("allow_hosts") or [])
            if str(host).strip().lower() in _LOOPBACK_HOSTNAMES
        }
    )
    if not loopback_entries:
        return ()
    if _has_local_loopback_dependency(merged):
        return ()
    return (
        ConfigViolation(
            severity=ConfigSeverity.CRITICAL,
            code="waf.allow_hosts_loopback_without_local_dependency",
            message=(
                "В prod/staging allowlist WAF содержит loopback-хост(ы) "
                + ", ".join(loopback_entries)
                + ", но в профиле нет включённой локальной зависимости "
                "(sidecar clamd/otel): запись мёртвая либо внешняя интеграция "
                "молча указывает на localhost (ADR-0407)."
            ),
            field="waf.allow_hosts",
            recommendation=(
                "Убрать loopback-хосты из waf.allow_hosts либо включить "
                "локальный sidecar (waf.clamav_enabled=true + "
                "waf.clamav_host на loopback)."
            ),
            context={"loopback_hosts": loopback_entries},
        ),
    )


def _check_replica_dsn_contract(merged: dict[str, Any]) -> tuple[ConfigViolation, ...]:
    """ADR-0407: ``database.replica_dsn`` — null допустим, непустое — реальный хост.

    ``null`` означает «реплика не развёрнута»: весь трафик идёт на primary,
    и это **не** нарушение прод-конфигурации. Непустое значение — только
    реальный (не loopback) хост: реплика на loopback означала бы, что каждый
    pod пишет в свой локальный экземпляр. Само значение — секрет и
    маскируется в дампах (ADR-0378 / ADR-0381).

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Кортеж нарушений (пустой — если нарушения нет).

    """
    if not _is_production_like(merged):
        return ()
    raw = (merged.get("database") or {}).get("replica_dsn")
    if raw is None:
        return ()  # реплики нет — штатное состояние
    text = str(raw).strip()
    host = (urlparse(text).hostname or "").lower() if text else ""
    if host and host not in _LOOPBACK_HOSTNAMES:
        return ()
    reason = (
        "указан loopback-хост реплики — каждый pod использовал бы свой "
        "локальный экземпляр"
        if host
        else "значение не является DSN с хостом реплики"
    )
    return (
        ConfigViolation(
            severity=ConfigSeverity.CRITICAL,
            code="database.replica_dsn_invalid",
            message=(
                "В prod/staging database.replica_dsn задан, но "
                f"{reason}. null (реплика не развёрнута) — допустимое "
                "значение (ADR-0407)."
            ),
            field="database.replica_dsn",
            recommendation=(
                "Оставить database.replica_dsn: null (трафик идёт на primary) "
                "либо указать реальный DSN реплики "
                "(postgresql+asyncpg://user:pwd@pg-replica:5432/main_db)."
            ),
            context={"host": host},
        ),
    )


def _secret_source_guaranteed(merged: dict[str, Any]) -> bool:
    """Есть ли гарантированный источник JWT-секрета.

    Источники (в порядке приоритета рантайма):

    * ``security.secret_key`` в YAML профиля — явное значение;
    * env ``SEC_SECRET_KEY`` — переменная окружения рантайма;
    * Vault (``vault.enabled`` + ``addr`` + ``secret_path``) — секреты
      приходят из корпоративного хранилища (ADR-0372).

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        ``True`` — секрет гарантированно поступает в рантайм.

    """
    security = merged.get("security") or {}
    if str(security.get("secret_key") or "").strip():
        return True
    if os.environ.get("SEC_SECRET_KEY", "").strip():
        return True
    vault = merged.get("vault") or {}
    return bool(
        vault.get("enabled")
        and str(vault.get("addr") or "").strip()
        and str(vault.get("secret_path") or "").strip()
    )


def _check_jwt_algorithm_secret_policy(
    merged: dict[str, Any],
) -> tuple[ConfigViolation, ...]:
    """ADR-0403: в prod симметричный JWT-алгоритм требует гарантированного секрета.

    ``security.algorithm: HS256`` подписывает токены симметричным ключом:
    без ключа выпуск/проверка JWT не работает, а со слабым — подбирается
    перебором. Раньше алгоритм и наличие секрета никто не сверял:
    «HS256 в prod» и «секрет приходит из Vault» были независимыми
    утверждениями.

    Политика алгоритма валидатор НЕ меняет (переход на RS256 — задача
    владельца, ADR-0371/OWNER_TASKS § 3): проверка только сообщает.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Кортеж нарушений (пустой — если нарушения нет).

    """
    if not _is_production(merged):
        return ()
    security = merged.get("security") or {}
    algorithm = str(security.get("algorithm") or "").strip().upper()
    if not algorithm.startswith("HS"):
        return ()  # RS256/ES256 — асимметричные, симметричный секрет не нужен
    if _secret_source_guaranteed(merged):
        return ()
    return (
        ConfigViolation(
            severity=ConfigSeverity.CRITICAL,
            code="security.jwt_symmetric_algorithm_without_secret",
            message=(
                f"В prod выбран симметричный алгоритм подписи JWT "
                f"(security.algorithm={algorithm}), но источник секрета не "
                "гарантирован: нет ни security.secret_key в YAML, ни env "
                "SEC_SECRET_KEY, ни включённого Vault (vault.enabled + addr + "
                "secret_path)."
            ),
            field="security.algorithm",
            recommendation=(
                "Задать секрет (env SEC_SECRET_KEY либо Vault "
                "vault.secret_path) либо перейти на асимметричный алгоритм "
                "(security.algorithm=RS256 + JWKS/IdP — owner-задача)."
            ),
            context={"algorithm": algorithm, "environment": "production"},
        ),
    )


def _default_fallback_chain() -> list[str]:
    """Fallback-цепочка AI по умолчанию (из модели настроек).

    Returns:
        Список имён провайдеров из default'а :class:`AIProvidersSettings`.

    """
    from src.backend.core.config.ai import AIProvidersSettings

    default = AIProvidersSettings.model_fields["fallback_chain"].default
    return list(default) if isinstance(default, list) else []


def _check_ai_fallback_chain_hosts(
    merged: dict[str, Any],
) -> tuple[ConfigViolation, ...]:
    """ADR-0403: в prod fallback-цепочка AI не должна уходить на loopback.

    ``open_webui`` (в базовом профиле — ``http://localhost:3000``) в
    fallback-цепочке означает молчаливый откат на локальный инференс в
    production: при недоступности внешнего провайдера запросы уйдут на
    хост, которого в проде нет, и деградация будет выглядеть как «LLM
    отвечает», а ответ будет пустым/ошибочным.

    Состав цепочки валидатор НЕ меняет (prod-профиль open_webui уже
    исключил — ADR-0371): проверка только сообщает.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Кортеж нарушений (пустой — если нарушения нет).

    """
    if not _is_production(merged):
        return ()
    providers_cfg = merged.get("ai_providers") or {}
    chain = providers_cfg.get("fallback_chain")
    if chain is None:
        chain = _default_fallback_chain()
    if not isinstance(chain, list):
        return ()

    offenders: list[tuple[str, str]] = []
    for provider in chain:
        name = str(provider)
        section = merged.get(name)
        if not isinstance(section, dict):
            continue
        base_url = str(section.get("base_url") or "")
        if not base_url:
            continue
        host = (urlparse(base_url).hostname or "").lower()
        if host in _LOOPBACK_HOSTNAMES:
            offenders.append((name, base_url))
    if not offenders:
        return ()
    return (
        ConfigViolation(
            severity=ConfigSeverity.CRITICAL,
            code="ai_providers.fallback_chain_localhost",
            message=(
                "В prod fallback-цепочка AI содержит провайдера с "
                "loopback-адресом ("
                + ", ".join(f"{name} ({url})" for name, url in offenders)
                + "): при недоступности внешнего провайдера запросы молча "
                "уйдут на локальный хост, которого в prod нет."
            ),
            field="ai_providers.fallback_chain",
            recommendation=(
                "Исключить loopback-провайдера из ai_providers.fallback_chain "
                "в prod-профиле либо задать ему реальный prod-endpoint."
            ),
            context={
                "providers": [name for name, _ in offenders],
                "chain": list(chain),
            },
        ),
    )


def validate_profile_config(
    profile: str, profiles_dir: Path | None = None
) -> tuple[ConfigViolation, ...]:
    """Валидирует MERGED-конфиг профиля (base + overlay).

    Args:
        profile: Имя профиля.
        profiles_dir: Каталог профилей (по умолчанию — репозиторный).

    Returns:
        Кортеж нарушений, отсортированный по severity
        (CRITICAL → WARNING → INFO).

    """
    from src.backend.core.config.validator import ConfigValidator

    merged = merge_profile_yaml(profile, profiles_dir)
    settings = build_profile_settings(merged)
    waf = _construct(WafSettings, merged.get("waf"))
    try:
        violations = list(ConfigValidator().validate(settings, waf))
    except AttributeError as exc:
        # Профиль неполон: обязательное поле отсутствует в YAML (например,
        # ``app.enable_swagger``). Это дефект конфигурации, а не сбой CLI —
        # сообщаем его как CRITICAL, а не роняем команду трейсбеком.
        return (
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="profile.incomplete",
                message=(
                    f"Профиль {profile} неполон: отсутствует обязательное поле ({exc})."
                ),
                field=str(exc),
                recommendation=(
                    "Дополнить config_profiles/base.yml (или overlay профиля) "
                    "недостающими полями."
                ),
            ),
        )
    violations.extend(_validate_constants_section(merged.get("constants") or {}))
    # ADR-0385 (A9): секции БД валидируются моделями — битые значения
    # (``pool_size: 0``, ``port: 99999``, опечатки в подключениях) больше
    # не проходят с exit 0.
    violations.extend(
        _validate_model_section(
            DatabaseConnectionSettings, merged.get("database"), "database"
        )
    )
    violations.extend(
        _validate_model_section(
            ExternalDatabasesSettings,
            merged.get("external_databases"),
            "external_databases",
        )
    )
    # ADR-0389: внешняя БД в профиле + выключенный feature-флаг
    # ``db_call_procedure_enabled`` → WARNING (вызовы процедур молча
    # пропускались бы). Не CRITICAL: внешняя БД может быть и без вызовов
    # процедур.
    violations.extend(_check_db_call_procedure_flag(merged))
    # ADR-0393: явная политика capability-гейта в prod/staging.
    violations.extend(_check_capability_gate_policy(merged))
    # ADR-0400: интроспекция GraphQL в prod/staging — только выключенной.
    violations.extend(_check_graphql_introspection_policy(merged))
    # ADR-0403: prod-политика безопасности — симметричный JWT-алгоритм
    # требует гарантированного секрета; fallback-цепочка AI не должна
    # уходить на loopback-хост.
    violations.extend(_check_jwt_algorithm_secret_policy(merged))
    violations.extend(_check_ai_fallback_chain_hosts(merged))
    # ADR-0407: контракты прод-значений — WAF-allowlist покрывает внешние
    # интеграции, loopback в allowlist оправдан локальной зависимостью,
    # ``database.replica_dsn=null`` допустим (реплика не развёрнута).
    violations.extend(_check_waf_allowlist_covers_integrations(merged))
    violations.extend(_check_waf_loopback_allowlist(merged))
    violations.extend(_check_replica_dsn_contract(merged))
    return tuple(
        sorted(
            violations,
            key=lambda v: (
                0
                if v.severity == ConfigSeverity.CRITICAL
                else 1
                if v.severity == ConfigSeverity.WARNING
                else 2
            ),
        )
    )
