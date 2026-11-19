"""Контракты prod-инфраструктуры: compose-сервисы ↔ prod-профиль ↔ env.

Волна 33, OWNER_TASKS §18 (п. 7) — «инфраструктурные 6 действий»: часть
кода закрыта (env-имена, настройки, валидатор), часть — инфраструктура.
Этот файл фиксирует связку, которая раньше отсутствовала:

* ``ops/compose/docker-compose.prod.yml`` — сервисы ``clickhouse``,
  ``open-webui``, ``jupyterhub`` (pinned-образы, healthcheck, restart,
  resource limits, общая сеть, без хардкода секретов);
* ``config_profiles/prod.yml`` — несекретные ключи (хосты/порты/enabled/
  base_url), совпадающие с именами compose-сервисов (ADR-0412 service-DNS);
* ``.env.example`` — только секреты (ADR-0373), пустые значения.

Проверки офлайн (без Docker): ``yaml.safe_load`` + сверка структуры.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final
from unittest.mock import patch

import pytest
import yaml

from src.backend.core.config.ai import OpenWebUISettings
from src.backend.core.config.clickhouse import ClickHouseSettings
from src.backend.core.config.services.jupyter_hub import JupyterHubSettings

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
PROD_COMPOSE: Final[Path] = PROJECT_ROOT / "ops" / "compose" / "docker-compose.prod.yml"
PROD_PROFILE: Final[Path] = PROJECT_ROOT / "config_profiles" / "prod.yml"
ENV_EXAMPLE: Final[Path] = PROJECT_ROOT / ".env.example"
JUPYTERHUB_CONFIG: Final[Path] = (
    PROJECT_ROOT / "ops" / "compose" / "jupyterhub" / "jupyterhub_config.py"
)

#: Ключ сети в compose-файлах. ВАЖНО: он должен совпадать с НЕЯВНОЙ сетью
#: base-файла (``default``) — иначе merge prod+base даёт ДВЕ сети: сервисы
#: prod-файла не видят сервисы base-файла (app не достучался до
#: mongo/kafka/minio/vault). Имя сети на диске — ``compose_prod_network``.
COMPOSE_NETWORK: Final[str] = "default"
COMPOSE_NETWORK_NAME: Final[str] = "compose_prod_network"

INFRA_SERVICES: Final[tuple[str, ...]] = ("clickhouse", "open-webui", "jupyterhub")

#: Имена хостов, которые клиенты приложения адресуют по service-DNS.
SERVICE_DNS_HOSTS: Final[dict[str, str]] = {
    "clickhouse": "clickhouse",
    "open-webui": "open-webui",
    "jupyterhub": "jupyterhub",
}

#: Секреты инфраструктуры: env → ожидаемое наличие в ``.env.example``.
INFRA_SECRETS: Final[tuple[str, ...]] = (
    "CLICKHOUSE_PASSWORD",
    "OPEN_WEBUI_API_KEY",
    "OPEN_WEBUI_SECRET_KEY",
    "JUPYTER_HUB_API_TOKEN",
)

#: Ключи env, значение которых не должно быть литералом (секрет/пароль).
SECRET_ENV_MARKERS: Final[tuple[str, ...]] = (
    "PASSWORD",
    "SECRET",
    "TOKEN",
    "API_KEY",
    "CREDENTIAL",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Читает YAML-файл.

    Args:
        path: Путь к YAML-файлу.

    Returns:
        Разобранный mapping (пустой dict для пустого файла).

    """
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    assert isinstance(data, dict)
    return data


def _compose_services() -> dict[str, Any]:
    """Сервисы prod-compose.

    Returns:
        Mapping ``имя сервиса → описание``.

    """
    return _load_yaml(PROD_COMPOSE)["services"]


def _prod_profile() -> dict[str, Any]:
    """Overlay prod-профиля.

    Returns:
        Разобранный mapping профиля.

    """
    return _load_yaml(PROD_PROFILE)


def _env_example() -> dict[str, str]:
    """Переменные из ``.env.example``.

    Returns:
        Mapping ``имя переменной → значение``.

    """
    result: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        result[name.strip()] = value.strip()
    return result


def _host_of(url: str) -> str:
    """Хост URL (без схемы и порта).

    Args:
        url: URL или голый host.

    Returns:
        Хост в нижнем регистре (пустая строка — хост не разобран).

    """
    text = str(url).strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    return text.split(":", 1)[0].split("/", 1)[0].strip().lower()


class TestProdComposeInfraServices:
    """Сервисы ClickHouse / OpenWebUI / JupyterHub в prod-compose."""

    @pytest.mark.parametrize("service", INFRA_SERVICES)
    def test_service_declared(self, service: str) -> None:
        """Сервис объявлен в prod-compose."""
        assert service in _compose_services()

    @pytest.mark.parametrize("service", INFRA_SERVICES)
    def test_image_is_pinned(self, service: str) -> None:
        """Образ закреплён на конкретной версии (без ``latest``)."""
        image = str(_compose_services()[service].get("image", ""))

        assert image, f"{service}: образ не задан"
        assert "latest" not in image, f"{service}: образ не закреплён ({image})"
        assert re.search(r":v?\d", image), f"{service}: нет версии в теге ({image})"

    @pytest.mark.parametrize("service", INFRA_SERVICES)
    def test_healthcheck_present(self, service: str) -> None:
        """У сервиса есть healthcheck."""
        healthcheck = _compose_services()[service].get("healthcheck")

        assert isinstance(healthcheck, dict), f"{service}: нет healthcheck"
        assert healthcheck.get("test"), f"{service}: healthcheck без test"

    @pytest.mark.parametrize("service", INFRA_SERVICES)
    def test_restart_policy(self, service: str) -> None:
        """Restart policy — ``unless-stopped`` (как у соседних сервисов)."""
        assert _compose_services()[service].get("restart") == "unless-stopped"

    @pytest.mark.parametrize("service", INFRA_SERVICES)
    def test_resource_limits(self, service: str) -> None:
        """Заданы resource limits (cpus + memory)."""
        limits = (
            _compose_services()[service]
            .get("deploy", {})
            .get("resources", {})
            .get("limits", {})
        )

        assert limits.get("cpus"), f"{service}: нет лимита cpus"
        assert limits.get("memory"), f"{service}: нет лимита memory"

    @pytest.mark.parametrize("service", INFRA_SERVICES)
    def test_uses_compose_network(self, service: str) -> None:
        """Сервис подключён к общей сети compose-стека."""
        networks = _compose_services()[service].get("networks") or []

        assert COMPOSE_NETWORK in networks

    def test_all_services_share_one_network(self) -> None:
        """Все сервисы стека — в одной сети (иначе app не видит инфраструктуру).

        Сервис без явного ``networks`` попадает в неявную сеть ``default`` —
        это тоже корректно; важно, чтобы НИ ОДИН сервис не был уведён в
        другую сеть (merge prod+base с разными ключами давал две сети).
        """
        services = _compose_services()

        for name, spec in services.items():
            networks = spec.get("networks") or []
            if not networks:
                continue  # неявная сетя default
            assert COMPOSE_NETWORK in networks, (
                f"{name}: сервис вне общей сети {COMPOSE_NETWORK!r} — "
                "merge compose-файлов разорвал сеть"
            )

    def test_network_name_is_stable(self) -> None:
        """Имя сети на диске фиксировано (compose_prod_network)."""
        compose = yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))

        networks = compose.get("networks") or {}

        assert COMPOSE_NETWORK in networks
        assert networks[COMPOSE_NETWORK].get("name") == COMPOSE_NETWORK_NAME

    @pytest.mark.parametrize("service", INFRA_SERVICES)
    def test_no_hardcoded_secrets(self, service: str) -> None:
        """Значения env с «секретным» именем — только ссылки на переменные."""
        environment = _compose_services()[service].get("environment") or {}

        for name, value in environment.items():
            if not any(marker in str(name).upper() for marker in SECRET_ENV_MARKERS):
                continue
            assert str(value).startswith("${"), (
                f"{service}.{name}: секрет задан литералом ({value!r})"
            )

    def test_required_secrets_use_fail_closed_syntax(self) -> None:
        """Обязательные секреты — через ``${VAR:?msg}`` (fail-closed)."""
        services = _compose_services()

        assert services["clickhouse"]["environment"]["CLICKHOUSE_PASSWORD"].startswith(
            "${CLICKHOUSE_PASSWORD:?"
        )
        assert services["open-webui"]["environment"]["WEBUI_SECRET_KEY"].startswith(
            "${OPEN_WEBUI_SECRET_KEY:?"
        )

    def test_clickhouse_applies_audit_migrations(self) -> None:
        """DDL audit-таблиц подкладывается в init-каталог ClickHouse."""
        volumes = _compose_services()["clickhouse"].get("volumes") or []

        assert any(
            "audit/migrations" in str(volume)
            and "/docker-entrypoint-initdb.d" in str(volume)
            for volume in volumes
        ), "миграции audit не смонтированы в docker-entrypoint-initdb.d"

    def test_jupyterhub_config_is_mounted(self) -> None:
        """Конфиг JupyterHub (регистрация API-токена) смонтирован в сервис."""
        volumes = _compose_services()["jupyterhub"].get("volumes") or []

        assert any("jupyterhub_config.py" in str(volume) for volume in volumes), (
            "jupyterhub_config.py не смонтирован"
        )

    def test_open_webui_port_matches_profile(self) -> None:
        """Порт OpenWebUI в compose совпадает с портом в prod-профиле."""
        ports = _compose_services()["open-webui"].get("ports") or []

        assert any("3000:3000" in str(port) for port in ports)


class TestProdProfileInfraKeys:
    """Несекретные ключи prod-профиля соответствуют compose-сервисам."""

    def test_clickhouse_points_to_compose_service(self) -> None:
        """``clickhouse.host`` — service-DNS имя compose-сервиса."""
        clickhouse = _prod_profile()["clickhouse"]

        assert clickhouse["enabled"] is True
        assert clickhouse["host"] == SERVICE_DNS_HOSTS["clickhouse"]
        assert clickhouse["http_port"] == 8123
        assert clickhouse["port"] == 9000

    def test_jupyter_hub_points_to_compose_service(self) -> None:
        """``jupyter_hub.base_url`` — service-DNS имя compose-сервиса."""
        jupyter_hub = _prod_profile()["jupyter_hub"]

        assert jupyter_hub["enabled"] is True
        assert _host_of(jupyter_hub["base_url"]) == SERVICE_DNS_HOSTS["jupyterhub"]
        assert jupyter_hub["base_url"].endswith(":8000")

    def test_open_webui_points_to_compose_service(self) -> None:
        """``open_webui.base_url`` — service-DNS имя compose-сервиса."""
        open_webui = _prod_profile()["open_webui"]

        assert _host_of(open_webui["base_url"]) == SERVICE_DNS_HOSTS["open-webui"]
        assert open_webui["base_url"].endswith(":3000")

    @pytest.mark.parametrize("host", ("clickhouse", "jupyterhub"))
    def test_waf_allowlist_covers_service_dns(self, host: str) -> None:
        """Хосты сервисов есть в ``waf.allow_hosts`` (клиенты идут через WAF)."""
        allow_hosts = _prod_profile()["waf"]["allow_hosts"]

        assert host in allow_hosts, f"{host}: отсутствует в waf.allow_hosts"

    def test_profile_hosts_match_compose_service_names(self) -> None:
        """Хосты профиля существуют как сервисы в prod-compose."""
        services = _compose_services()

        for host in SERVICE_DNS_HOSTS.values():
            assert host in services, f"сервиса {host} нет в prod-compose"


class TestInfraEnvNames:
    """Env-имена выводятся из префиксов моделей настроек."""

    def test_clickhouse_env_prefix_and_fields(self) -> None:
        """``CLICKHOUSE_ENABLED/HOST/HTTP_PORT`` — реальные поля модели."""
        assert ClickHouseSettings.model_config.get("env_prefix") == "CLICKHOUSE_"
        for field in ("enabled", "host", "http_port", "password"):
            assert field in ClickHouseSettings.model_fields

    def test_jupyter_hub_env_prefix_and_fields(self) -> None:
        """``JUPYTER_HUB_ENABLED/BASE_URL/API_TOKEN`` — реальные поля модели."""
        assert JupyterHubSettings.model_config.get("env_prefix") == "JUPYTER_HUB_"
        for field in ("enabled", "base_url", "api_token"):
            assert field in JupyterHubSettings.model_fields

    def test_open_webui_env_prefix_and_fields(self) -> None:
        """``OPEN_WEBUI_BASE_URL/API_KEY`` — реальные поля модели."""
        assert OpenWebUISettings.model_config.get("env_prefix") == "OPEN_WEBUI_"
        for field in ("base_url", "api_key"):
            assert field in OpenWebUISettings.model_fields


class TestEnvExampleInfraSecrets:
    """Секреты инфраструктуры задокументированы в ``.env.example``."""

    @pytest.mark.parametrize("name", INFRA_SECRETS)
    def test_secret_present_and_empty(self, name: str) -> None:
        """Секрет описан в ``.env.example`` и имеет пустое значение."""
        env = _env_example()

        assert name in env, f"{name}: отсутствует в .env.example"
        assert env[name] == "", f"{name}: значение в шаблоне должно быть пустым"


class TestJupyterHubConfig:
    """Конфиг JupyterHub регистрирует API-токен приложения."""

    def _load(self, env: dict[str, str]) -> SimpleNamespace:
        """Выполняет конфиг JupyterHub с подменённым окружением.

        Args:
            env: Значения переменных окружения для подмены.

        Returns:
            Объект конфигурации (``c``) после выполнения файла.

        """
        config = SimpleNamespace(
            JupyterHub=SimpleNamespace(), Authenticator=SimpleNamespace()
        )
        namespace: dict[str, Any] = {"get_config": lambda: config}
        code = compile(
            JUPYTERHUB_CONFIG.read_text(encoding="utf-8"),
            str(JUPYTERHUB_CONFIG),
            "exec",
        )
        with patch.dict(os.environ, env, clear=False):
            exec(code, namespace)  # noqa: S102 — исполнение конфига JupyterHub
        return config

    def test_api_token_registered_for_admin(self) -> None:
        """Токен из env регистрируется как токен пользователя-админа."""
        config = self._load(
            {"JUPYTER_HUB_API_TOKEN": "tok-123", "JUPYTER_HUB_API_USER": "admin"}
        )

        assert config.JupyterHub.api_tokens == {"admin": "tok-123"}
        assert config.Authenticator.admin_users == {"admin"}

    def test_no_token_no_registration(self) -> None:
        """Без токена в env API-токены не регистрируются."""
        config = self._load({"JUPYTER_HUB_API_TOKEN": ""})

        assert not getattr(config.JupyterHub, "api_tokens", {})
