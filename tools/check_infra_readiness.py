#!/usr/bin/env python3
"""Гейт готовности инфраструктуры prod (ADR-0441, чек-лист п.4.2).

Проверяет 6 инфраструктурных действий владельца платформы **по конфигурации**
(``config_profiles/{profile}.yml`` + переменные окружения) — без обращения
к живому прод-окружению: Vault/сеть/JWKS-сервис не нужны, живость не
проверяется. Гейт fail-closed: небезопасное или несогласованное значение
конфигурации блокирует релиз.

Пункты чек-листа (``docs/ops/infra-release-checklist.md``):

1. ``jwks`` — keypair + JWKS-сервис (**https**) → ``SEC_JWKS_URL``,
   ``SEC_ALGORITHM=RS256``;
2. ``snapshot_service_role`` — роль БД с ``BYPASSRLS`` + ``SNAPSHOT_SERVICE_DSN``
   (режим ``service-role``);
3. ``clickhouse`` — ClickHouse в проде (``CLICKHOUSE_HOST/HTTP_PORT/ENABLED``);
4. ``open_webui`` — OpenWebUI (``OPEN_WEBUI_BASE_URL/API_KEY``) + согласованность
   с ``ai_providers.fallback_chain`` прод-профиля;
5. ``jupyter_hub`` — JupyterHub (``JUPYTER_HUB_ENABLED/BASE_URL/API_TOKEN``);
6. ``db_replica_dsn`` — ``database.replica_dsn`` (``null`` — допустимо;
   непустое — валидный не-loopback хост реплики).

Семантика severities
--------------------

* ``fail`` — небезопасное/некорректное значение или противоречие конфигурации
  (``http://`` в JWKS-URL, loopback-хост ClickHouse в prod, провайдер в
  fallback-цепочке без endpoint). Блокирует гейт во всех режимах;
* ``warning`` — невыполненное инфра-действие или отсутствующий секрет
  (секреты живут в Vault, поэтому их отсутствие в CI — не нарушение).
  Блокирует только с ``--strict``;
* ``ok`` — пункт закрыт.

Использование::

    python tools/check_infra_readiness.py                    # профиль prod
    python tools/check_infra_readiness.py --profile prod --strict
    python tools/check_infra_readiness.py --json

Exit codes
----------
    0 — нарушений нет (``warning`` не блокирует);
    1 — есть ``fail`` (или ``warning`` при ``--strict``);
    2 — ошибка запуска (профиль/YAML не читаются).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_PROFILES_DIR: Final[Path] = PROJECT_ROOT / "config_profiles"
DEFAULT_PROFILE: Final[str] = "prod"

#: Env-имена (ADR-0372: env приоритетнее YAML; секреты — только из Vault).
ENV_ALGORITHM: Final[str] = "SEC_ALGORITHM"
ENV_JWKS_URL: Final[str] = "SEC_JWKS_URL"
ENV_SNAPSHOT_MODE: Final[str] = "SNAPSHOT_MODE"
ENV_SNAPSHOT_SERVICE_DSN: Final[str] = "SNAPSHOT_SERVICE_DSN"
ENV_CLICKHOUSE_ENABLED: Final[str] = "CLICKHOUSE_ENABLED"
ENV_CLICKHOUSE_HOST: Final[str] = "CLICKHOUSE_HOST"
ENV_CLICKHOUSE_HTTP_PORT: Final[str] = "CLICKHOUSE_HTTP_PORT"
ENV_OPEN_WEBUI_BASE_URL: Final[str] = "OPEN_WEBUI_BASE_URL"
ENV_OPEN_WEBUI_API_KEY: Final[str] = "OPEN_WEBUI_API_KEY"
ENV_JUPYTER_HUB_ENABLED: Final[str] = "JUPYTER_HUB_ENABLED"
ENV_JUPYTER_HUB_BASE_URL: Final[str] = "JUPYTER_HUB_BASE_URL"
ENV_JUPYTER_HUB_API_TOKEN: Final[str] = "JUPYTER_HUB_API_TOKEN"  # noqa: S105 — имя env, не секрет
ENV_DB_REPLICA_DSN: Final[str] = "DB_REPLICA_DSN"

#: Алгоритмы подписи JWT (Literal в ``core/config/security.py``).
ALLOWED_ALGORITHMS: Final[frozenset[str]] = frozenset(
    {"HS256", "HS384", "HS512", "RS256", "ES256"}
)
#: Асимметричные алгоритмы — требуют JWKS-endpoint (ADR-0411).
ASYMMETRIC_ALGORITHMS: Final[frozenset[str]] = frozenset({"RS256", "ES256"})

#: Режимы межtenant-снапшота (ADR-0413).
SNAPSHOT_MODES: Final[frozenset[str]] = frozenset(
    {"single-tenant", "per-tenant", "service-role"}
)

#: Хосты, непригодные для внешнего сервиса в prod (ADR-0412/ADR-0407).
NON_ROUTABLE_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "0.0.0.0", "::", "::1"}
)

_TRUE_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})


class Severity(StrEnum):
    """Уровень значимости результата проверки инфра-готовности."""

    OK = "ok"
    WARNING = "warning"
    FAIL = "fail"


class InfraFinding(BaseModel):
    """Результат одной проверки инфраструктурной готовности.

    Attributes:
        check: Идентификатор проверки (``jwks``, ``clickhouse``, ...).
        severity: Уровень значимости (``ok`` / ``warning`` / ``fail``).
        message: Человекочитаемое описание результата.
        hint: Что нужно сделать владельцу инфраструктуры (опционально).

    """

    model_config = ConfigDict(frozen=True)

    check: str
    severity: Severity
    message: str
    hint: str = ""


class InfraCheck(BaseModel):
    """Описание одной проверки инфраструктурной готовности (реестр чек-листа).

    Attributes:
        id: Идентификатор проверки (совпадает с пунктом чек-листа).
        title: Человекочитаемое название пункта.
        run: Функция проверки: (merged-конфиг, env) → список результатов.

    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    id: str
    title: str
    run: Callable[[dict[str, Any], Mapping[str, str]], list[InfraFinding]]


def _section(config: Mapping[str, Any], name: str) -> dict[str, Any]:
    """Возвращает YAML-секцию конфигурации (пустой dict, если её нет)."""
    value = config.get(name)
    return value if isinstance(value, dict) else {}


def _env_or_profile(env: Mapping[str, str], env_name: str, profile_value: Any) -> str:
    """Эффективное значение настройки: env → YAML → пустая строка.

    Пустое значение env считается «не задано»: секреты приходят из Vault
    уже в рантайме, и их отсутствие в окружении гейта — не нарушение.

    Args:
        env: Переменные окружения.
        env_name: Имя env-переменной.
        profile_value: Значение из YAML-профиля.

    Returns:
        Непустая строка-значение либо ``""``.

    """
    raw = env.get(env_name)
    if raw is not None and raw.strip():
        return raw.strip()
    if profile_value is None:
        return ""
    return str(profile_value).strip()


def _env_bool(env: Mapping[str, str], env_name: str, default: bool) -> bool:
    """Читает булеву настройку из env, иначе берёт значение из YAML.

    Args:
        env: Переменные окружения.
        env_name: Имя env-переменной.
        default: Значение из YAML-профиля.

    Returns:
        Итоговое булево значение (нераспознанное значение env → YAML).

    """
    raw = (env.get(env_name) or "").strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    return default


def _is_non_routable_host(host: str) -> bool:
    """Является ли хост непригодным для внешнего сервиса (loopback и т.п.)."""
    cleaned = host.strip().lower().strip("[]")
    if cleaned in NON_ROUTABLE_HOSTS:
        return True
    return cleaned.startswith("127.")


def _dsn_problem(dsn: str) -> str | None:
    """Проверяет DSN на пригодность для внешнего сервиса.

    Args:
        dsn: Значение DSN.

    Returns:
        Текст проблемы либо ``None``, если DSN корректен.

    """
    parsed = urlparse(dsn)
    if not parsed.scheme:
        return "значение не является DSN (нет схемы)"
    if not parsed.scheme.startswith("postgresql"):
        return f"неожиданная схема DSN {parsed.scheme!r} (ожидается postgresql+asyncpg)"
    host = parsed.hostname or ""
    if not host:
        return "DSN не содержит хоста"
    if _is_non_routable_host(host):
        return f"хост {host!r} — loopback (каждый pod использовал бы свой локальный экземпляр)"
    return None


def check_jwks(config: dict[str, Any], env: Mapping[str, str]) -> list[InfraFinding]:
    """Пункт 1 чек-листа: keypair + JWKS-сервис (только https).

    Args:
        config: Слияние ``base.yml`` + overlay профиля.
        env: Переменные окружения.

    Returns:
        Список результатов проверки (пустой — нарушений нет).

    """
    security = _section(config, "security")
    algorithm = _env_or_profile(env, ENV_ALGORITHM, security.get("algorithm"))
    jwks_url = _env_or_profile(env, ENV_JWKS_URL, security.get("jwks_url"))

    if algorithm not in ALLOWED_ALGORITHMS:
        return [
            InfraFinding(
                check="jwks",
                severity=Severity.FAIL,
                message=(
                    f"алгоритм подписи {algorithm!r} не поддерживается "
                    f"(допустимы: {', '.join(sorted(ALLOWED_ALGORITHMS))})"
                ),
                hint=f"Задать {ENV_ALGORITHM}=RS256 вместе с {ENV_JWKS_URL}.",
            )
        ]

    if jwks_url and not jwks_url.lower().startswith("https://"):
        return [
            InfraFinding(
                check="jwks",
                severity=Severity.FAIL,
                message=(
                    f"{ENV_JWKS_URL} обязан использовать схему https:// "
                    "(http:// отклоняется JwksConfigurationError — SSRF-guard)"
                ),
                hint="Поднять JWKS-сервис за TLS и указать https-URL.",
            )
        ]

    if algorithm in ASYMMETRIC_ALGORITHMS:
        if not jwks_url:
            return [
                InfraFinding(
                    check="jwks",
                    severity=Severity.FAIL,
                    message=(
                        f"алгоритм {algorithm} требует JWKS-endpoint, но "
                        f"{ENV_JWKS_URL} не задан — проверять подпись нечем"
                    ),
                    hint=(
                        "Сгенерировать keypair (tools/generate_jwks_keypair.py), "
                        f"отдать jwks.json в ConfigMap/Secret и задать {ENV_JWKS_URL}."
                    ),
                )
            ]
        return [
            InfraFinding(
                check="jwks",
                severity=Severity.OK,
                message=f"JWKS сконфигурирован: алгоритм {algorithm}, https-endpoint задан.",
            )
        ]

    if jwks_url:
        return [
            InfraFinding(
                check="jwks",
                severity=Severity.OK,
                message=f"JWKS-endpoint (https) задан; алгоритм подписи — {algorithm}.",
            )
        ]
    return [
        InfraFinding(
            check="jwks",
            severity=Severity.WARNING,
            message=(
                f"миграция на асимметричную подпись не выполнена: алгоритм "
                f"{algorithm}, {ENV_JWKS_URL} не задан"
            ),
            hint=(
                "Инфра-задача владельца: keypair + JWKS-сервис (https), "
                f"{ENV_ALGORITHM}=RS256."
            ),
        )
    ]


def check_snapshot_service_role(
    config: dict[str, Any], env: Mapping[str, str]
) -> list[InfraFinding]:
    """Пункт 2 чек-листа: роль БД с ``BYPASSRLS`` + ``SNAPSHOT_SERVICE_DSN``.

    Args:
        config: Слияние ``base.yml`` + overlay профиля.
        env: Переменные окружения.

    Returns:
        Список результатов проверки (пустой — нарушений нет).

    """
    snapshot = _section(config, "snapshot")
    mode = _env_or_profile(env, ENV_SNAPSHOT_MODE, snapshot.get("mode"))
    mode = mode or "single-tenant"
    dsn = _env_or_profile(env, ENV_SNAPSHOT_SERVICE_DSN, snapshot.get("service_dsn"))

    if mode not in SNAPSHOT_MODES:
        return [
            InfraFinding(
                check="snapshot_service_role",
                severity=Severity.FAIL,
                message=(
                    f"неизвестный режим снапшота {mode!r} "
                    f"(допустимы: {', '.join(sorted(SNAPSHOT_MODES))})"
                ),
                hint=f"Задать {ENV_SNAPSHOT_MODE} одним из допустимых значений.",
            )
        ]

    if mode != "service-role":
        if dsn:
            return [
                InfraFinding(
                    check="snapshot_service_role",
                    severity=Severity.WARNING,
                    message=(
                        f"{ENV_SNAPSHOT_SERVICE_DSN} задан, но режим снапшота — "
                        f"{mode!r}: DSN используется только в режиме 'service-role'"
                    ),
                    hint=(
                        "Либо переключить режим на 'service-role', либо убрать DSN "
                        "из окружения."
                    ),
                )
            ]
        return [
            InfraFinding(
                check="snapshot_service_role",
                severity=Severity.OK,
                message=(
                    f"режим снапшота — {mode!r}: служебная роль с BYPASSRLS не требуется."
                ),
            )
        ]

    if not dsn:
        return [
            InfraFinding(
                check="snapshot_service_role",
                severity=Severity.WARNING,
                message=(
                    "режим 'service-role' требует DSN служебной роли с BYPASSRLS, "
                    f"но {ENV_SNAPSHOT_SERVICE_DSN} не задан (снапшоты не создаются)"
                ),
                hint=(
                    "Применить ops/sql/bypassrls_role.sql и выдать "
                    f"{ENV_SNAPSHOT_SERVICE_DSN} из Vault."
                ),
            )
        ]

    problem = _dsn_problem(dsn)
    if problem:
        return [
            InfraFinding(
                check="snapshot_service_role",
                severity=Severity.FAIL,
                message=f"{ENV_SNAPSHOT_SERVICE_DSN} некорректен: {problem}.",
                hint="Указать DSN служебной роли с реальным хостом БД.",
            )
        ]
    return [
        InfraFinding(
            check="snapshot_service_role",
            severity=Severity.OK,
            message="режим 'service-role' сконфигурирован: DSN служебной роли задан.",
        )
    ]


def check_clickhouse(
    config: dict[str, Any], env: Mapping[str, str]
) -> list[InfraFinding]:
    """Пункт 3 чек-листа: ClickHouse в проде.

    Args:
        config: Слияние ``base.yml`` + overlay профиля.
        env: Переменные окружения.

    Returns:
        Список результатов проверки (пустой — нарушений нет).

    """
    features = _section(config, "features")
    clickhouse = _section(config, "clickhouse")
    audit_enabled = bool(features.get("audit_clickhouse_enabled", False))
    enabled = _env_bool(
        env, ENV_CLICKHOUSE_ENABLED, bool(clickhouse.get("enabled", False))
    )
    host = _env_or_profile(env, ENV_CLICKHOUSE_HOST, clickhouse.get("host"))
    http_port = _env_or_profile(
        env, ENV_CLICKHOUSE_HTTP_PORT, clickhouse.get("http_port")
    )

    if not audit_enabled and not enabled:
        return [
            InfraFinding(
                check="clickhouse",
                severity=Severity.OK,
                message="ClickHouse не используется — действие владельца не требуется.",
            )
        ]

    if audit_enabled and not enabled:
        return [
            InfraFinding(
                check="clickhouse",
                severity=Severity.FAIL,
                message=(
                    "features.audit_clickhouse_enabled=true, но ClickHouse выключен "
                    f"({ENV_CLICKHOUSE_ENABLED}=false / clickhouse.enabled=false) — "
                    "трейл audit-событий не пишется"
                ),
                hint=(
                    f"Задать {ENV_CLICKHOUSE_ENABLED}=true, {ENV_CLICKHOUSE_HOST} "
                    f"и {ENV_CLICKHOUSE_HTTP_PORT} (внешний DSN или сервис в compose.prod)."
                ),
            )
        ]

    if not host:
        return [
            InfraFinding(
                check="clickhouse",
                severity=Severity.FAIL,
                message=f"ClickHouse включён, но {ENV_CLICKHOUSE_HOST} не задан.",
                hint=f"Задать {ENV_CLICKHOUSE_HOST} адресом внешнего сервиса.",
            )
        ]

    if _is_non_routable_host(host):
        return [
            InfraFinding(
                check="clickhouse",
                severity=Severity.FAIL,
                message=(
                    f"ClickHouse включён, но хост {host!r} — в prod писать в "
                    "localhost нельзя (каждый pod писал бы в свой локальный экземпляр)"
                ),
                hint=(
                    f"Задать {ENV_CLICKHOUSE_HOST} адресом внешнего ClickHouse "
                    "(service-DNS или внешний DSN)."
                ),
            )
        ]

    try:
        port = int(http_port)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        return [
            InfraFinding(
                check="clickhouse",
                severity=Severity.FAIL,
                message=(
                    f"{ENV_CLICKHOUSE_HTTP_PORT} = {http_port!r} — не корректный "
                    "HTTP-порт (ожидается 1..65535)"
                ),
                hint=f"Задать {ENV_CLICKHOUSE_HTTP_PORT} (обычно 8123).",
            )
        ]

    return [
        InfraFinding(
            check="clickhouse",
            severity=Severity.OK,
            message=(f"ClickHouse сконфигурирован: хост {host!r}, HTTP-порт {port}."),
        )
    ]


def check_open_webui(
    config: dict[str, Any], env: Mapping[str, str]
) -> list[InfraFinding]:
    """Пункт 4 чек-листа: OpenWebUI + согласованность с ``fallback_chain``.

    Args:
        config: Слияние ``base.yml`` + overlay профиля.
        env: Переменные окружения.

    Returns:
        Список результатов проверки (пустой — нарушений нет).

    """
    providers = _section(config, "ai_providers")
    open_webui = _section(config, "open_webui")
    chain = providers.get("fallback_chain") or []
    in_chain = "open_webui" in chain
    base_url = _env_or_profile(env, ENV_OPEN_WEBUI_BASE_URL, open_webui.get("base_url"))
    api_key = _env_or_profile(env, ENV_OPEN_WEBUI_API_KEY, open_webui.get("api_key"))

    if not in_chain:
        if api_key:
            return [
                InfraFinding(
                    check="open_webui",
                    severity=Severity.WARNING,
                    message=(
                        "OpenWebUI настроен (API-ключ задан), но провайдер не "
                        "включён в ai_providers.fallback_chain прод-профиля"
                    ),
                    hint=(
                        "После развёртывания сервиса добавить 'open_webui' в "
                        "ai_providers.fallback_chain."
                    ),
                )
            ]
        return [
            InfraFinding(
                check="open_webui",
                severity=Severity.WARNING,
                message=(
                    "OpenWebUI не подключён: провайдер не в fallback-цепочке, "
                    f"{ENV_OPEN_WEBUI_API_KEY} не задан"
                    + (f" (endpoint в профиле: {base_url})" if base_url else "")
                ),
                hint=(
                    "Инфра-задача владельца: развернуть OpenWebUI, задать "
                    f"{ENV_OPEN_WEBUI_BASE_URL} и {ENV_OPEN_WEBUI_API_KEY}, "
                    "затем добавить провайдера в fallback_chain."
                ),
            )
        ]

    if not base_url:
        return [
            InfraFinding(
                check="open_webui",
                severity=Severity.FAIL,
                message=(
                    "провайдер 'open_webui' в fallback-цепочке, но "
                    f"{ENV_OPEN_WEBUI_BASE_URL} не задан — откат ушёл бы "
                    "на несуществующий endpoint"
                ),
                hint=f"Задать {ENV_OPEN_WEBUI_BASE_URL} (service-DNS).",
            )
        ]

    if _is_non_routable_host(urlparse(base_url).hostname or ""):
        return [
            InfraFinding(
                check="open_webui",
                severity=Severity.FAIL,
                message=(
                    f"{ENV_OPEN_WEBUI_BASE_URL} указывает на loopback — в prod "
                    "откат ушёл бы на сервис, которого нет (ADR-0407/ADR-0412)"
                ),
                hint="Указать service-DNS адрес развёрнутого OpenWebUI.",
            )
        ]

    if not api_key:
        return [
            InfraFinding(
                check="open_webui",
                severity=Severity.WARNING,
                message=(
                    f"провайдер 'open_webui' в fallback-цепочке, но "
                    f"{ENV_OPEN_WEBUI_API_KEY} не задан"
                ),
                hint=f"Выдать {ENV_OPEN_WEBUI_API_KEY} из Vault.",
            )
        ]

    return [
        InfraFinding(
            check="open_webui",
            severity=Severity.OK,
            message="OpenWebUI сконфигурирован и включён в fallback-цепочку.",
        )
    ]


def check_jupyter_hub(
    config: dict[str, Any], env: Mapping[str, str]
) -> list[InfraFinding]:
    """Пункт 5 чек-листа: JupyterHub.

    Args:
        config: Слияние ``base.yml`` + overlay профиля.
        env: Переменные окружения.

    Returns:
        Список результатов проверки (пустой — нарушений нет).

    """
    jupyter = _section(config, "jupyter_hub")
    enabled = _env_bool(
        env, ENV_JUPYTER_HUB_ENABLED, bool(jupyter.get("enabled", False))
    )
    base_url = _env_or_profile(env, ENV_JUPYTER_HUB_BASE_URL, jupyter.get("base_url"))
    api_token = _env_or_profile(
        env, ENV_JUPYTER_HUB_API_TOKEN, jupyter.get("api_token")
    )

    if not enabled:
        return [
            InfraFinding(
                check="jupyter_hub",
                severity=Severity.WARNING,
                message=(f"JupyterHub не развёрнут ({ENV_JUPYTER_HUB_ENABLED}=false)"),
                hint=(
                    "Инфра-задача владельца: развернуть JupyterHub и задать "
                    f"{ENV_JUPYTER_HUB_ENABLED}=true, {ENV_JUPYTER_HUB_BASE_URL}, "
                    f"{ENV_JUPYTER_HUB_API_TOKEN}."
                ),
            )
        ]

    if not base_url:
        return [
            InfraFinding(
                check="jupyter_hub",
                severity=Severity.FAIL,
                message=(
                    f"JupyterHub включён, но {ENV_JUPYTER_HUB_BASE_URL} не задан."
                ),
                hint=f"Задать {ENV_JUPYTER_HUB_BASE_URL} адресом JupyterHub.",
            )
        ]

    if _is_non_routable_host(urlparse(base_url).hostname or ""):
        return [
            InfraFinding(
                check="jupyter_hub",
                severity=Severity.FAIL,
                message=(
                    f"{ENV_JUPYTER_HUB_BASE_URL} указывает на loopback — в prod "
                    "это сам pod, а не JupyterHub"
                ),
                hint="Указать service-DNS адрес JupyterHub.",
            )
        ]

    if not api_token:
        return [
            InfraFinding(
                check="jupyter_hub",
                severity=Severity.WARNING,
                message=(
                    f"JupyterHub включён, но {ENV_JUPYTER_HUB_API_TOKEN} не задан "
                    "(при enabled=true токен обязателен)"
                ),
                hint=f"Выдать {ENV_JUPYTER_HUB_API_TOKEN} из Vault.",
            )
        ]

    return [
        InfraFinding(
            check="jupyter_hub",
            severity=Severity.OK,
            message="JupyterHub сконфигурирован: URL и API-токен заданы.",
        )
    ]


def check_db_replica_dsn(
    config: dict[str, Any], env: Mapping[str, str]
) -> list[InfraFinding]:
    """Пункт 6 чек-листа: ``database.replica_dsn`` (null — допустимо).

    Args:
        config: Слияние ``base.yml`` + overlay профиля.
        env: Переменные окружения.

    Returns:
        Список результатов проверки (пустой — нарушений нет).

    """
    database = _section(config, "database")
    dsn = _env_or_profile(env, ENV_DB_REPLICA_DSN, database.get("replica_dsn"))

    if not dsn:
        return [
            InfraFinding(
                check="db_replica_dsn",
                severity=Severity.OK,
                message=(
                    "реплика не развёрнута: replica_dsn=null — допустимое "
                    "прод-значение (ADR-0407)"
                ),
            )
        ]

    problem = _dsn_problem(dsn)
    if problem:
        return [
            InfraFinding(
                check="db_replica_dsn",
                severity=Severity.FAIL,
                message=f"{ENV_DB_REPLICA_DSN} задан, но {problem}.",
                hint=(
                    "Оставить database.replica_dsn: null либо указать реальный "
                    "DSN реплики (postgresql+asyncpg://user:pwd@pg-replica:5432/db)."
                ),
            )
        ]

    return [
        InfraFinding(
            check="db_replica_dsn",
            severity=Severity.OK,
            message="DSN реплики задан и указывает на реальный хост.",
        )
    ]


#: Реестр проверок (порядок = порядок пунктов чек-листа).
INFRA_CHECKS: tuple[InfraCheck, ...] = (
    InfraCheck(id="jwks", title="keypair + JWKS-сервис (https)", run=check_jwks),
    InfraCheck(
        id="snapshot_service_role",
        title="роль БД с BYPASSRLS + DSN снапшота",
        run=check_snapshot_service_role,
    ),
    InfraCheck(id="clickhouse", title="ClickHouse в проде", run=check_clickhouse),
    InfraCheck(
        id="open_webui", title="OpenWebUI + fallback_chain", run=check_open_webui
    ),
    InfraCheck(id="jupyter_hub", title="JupyterHub", run=check_jupyter_hub),
    InfraCheck(
        id="db_replica_dsn", title="database.replica_dsn", run=check_db_replica_dsn
    ),
)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Рекурсивно сливает overlay в base (как рантайм-слияние профилей)."""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    """Читает YAML-файл конфигурации.

    Args:
        path: Путь к YAML-файлу.

    Returns:
        Разобранный mapping (пустой dict для пустого файла).

    Raises:
        FileNotFoundError: Файла нет.
        ValueError: YAML невалиден или не является mapping'ом.

    """
    if not path.is_file():
        raise FileNotFoundError(f"файл не найден: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"невалидный YAML {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML должен быть mapping'ом: {path}")
    return data


def load_merged_profile(
    profile: str, profiles_dir: Path = DEFAULT_PROFILES_DIR
) -> dict[str, Any]:
    """Читает ``base.yml`` + overlay профиля и сливает их (как в рантайме).

    Args:
        profile: Имя профиля (``prod``/``staging``/...).
        profiles_dir: Каталог с YAML-профилями.

    Returns:
        Итоговый конфиг после слияния.

    Raises:
        FileNotFoundError: Нет ``base.yml`` или overlay-файла профиля.
        ValueError: YAML невалиден.

    """
    base = _load_yaml(profiles_dir / "base.yml")
    overlay = _load_yaml(profiles_dir / f"{profile}.yml")
    return _deep_merge(base, overlay)


def run_checks(
    config: dict[str, Any], env: Mapping[str, str] | None = None
) -> list[InfraFinding]:
    """Прогоняет все проверки инфраструктурной готовности.

    Args:
        config: Слияние ``base.yml`` + overlay профиля.
        env: Переменные окружения (по умолчанию — ``os.environ``).

    Returns:
        Список результатов по всем пунктам чек-листа.

    """
    environment = os.environ if env is None else env
    findings: list[InfraFinding] = []
    for check in INFRA_CHECKS:
        findings.extend(check.run(config, environment))
    return findings


def _counts(findings: list[InfraFinding]) -> dict[str, int]:
    """Считает результаты по severity."""
    return {
        severity.value: sum(1 for f in findings if f.severity is severity)
        for severity in Severity
    }


def _render(profile: str, findings: list[InfraFinding]) -> str:
    """Человекочитаемый отчёт по результатам проверок."""
    titles = {check.id: check.title for check in INFRA_CHECKS}
    lines = [f"[check-infra-readiness] профиль: {profile}"]
    for finding in findings:
        marker = {Severity.OK: "OK  ", Severity.WARNING: "WARN", Severity.FAIL: "FAIL"}[
            finding.severity
        ]
        lines.append(
            f"  [{marker}] {finding.check} ({titles.get(finding.check, '')}): "
            f"{finding.message}"
        )
        if finding.hint:
            lines.append(f"         → {finding.hint}")
    counts = _counts(findings)
    lines.append(
        "итого: "
        f"fail={counts[Severity.FAIL.value]} "
        f"warning={counts[Severity.WARNING.value]} "
        f"ok={counts[Severity.OK.value]}"
    )
    return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Собирает CLI-парсер гейта."""
    parser = argparse.ArgumentParser(
        description="Проверка готовности инфраструктуры прод-профиля."
    )
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        help="Имя профиля конфигурации (по умолчанию: prod).",
    )
    parser.add_argument(
        "--profiles-dir",
        default=str(DEFAULT_PROFILES_DIR),
        help="Каталог с YAML-профилями (по умолчанию: config_profiles).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Блокировать гейт и на warning (невыполненные инфра-действия).",
    )
    parser.add_argument(
        "--json", action="store_true", help="JSON-вывод (для CI-интеграции)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа гейта.

    Args:
        argv: Аргументы CLI (по умолчанию — ``sys.argv[1:]``).

    Returns:
        0 — нарушений нет; 1 — есть fail (или warning при ``--strict``);
        2 — ошибка запуска.

    """
    args = _build_arg_parser().parse_args(argv)
    profiles_dir = Path(args.profiles_dir)

    try:
        config = load_merged_profile(args.profile, profiles_dir)
    except (OSError, ValueError) as exc:
        print(
            f"ERROR: не удалось прочитать профиль {args.profile!r}: {exc}",
            file=sys.stderr,
        )
        return 2

    findings = run_checks(config)
    has_fail = any(f.severity is Severity.FAIL for f in findings)
    has_warning = any(f.severity is Severity.WARNING for f in findings)
    rc = 1 if has_fail or (args.strict and has_warning) else 0

    if args.json:
        payload = {
            "profile": args.profile,
            "strict": bool(args.strict),
            "ok": rc == 0,
            "exit_code": rc,
            "counts": _counts(findings),
            "checks": [
                {
                    "id": finding.check,
                    "severity": finding.severity.value,
                    "message": finding.message,
                    "hint": finding.hint,
                }
                for finding in findings
            ],
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        print(_render(args.profile, findings))

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
