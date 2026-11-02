"""ADR-0412 — deploy-манифесты: Service для sidecar'ов и endpoint'ов (волна 23, C2).

Контракт ADR-0412: конфигурация адресует sidecar'ы и внутренние сервисы по
service-DNS, поэтому в кластере обязаны быть соответствующие ``Service``:

* ``clamd`` — ClamAV (TCP INSTREAM, 3310);
* ``otel-collector`` — OTLP-экспорт телеметрии (4317/4318);
* ``open-webui`` — внутренний LLM-сервер (3000).

И ``ConfigMap`` должен содержать те же хосты, что и профили конфигурации
(иначе приложение в кластере пойдёт не туда, а валидатор профиля проверит
другой файл).

Проверки офлайн (без kubectl/Helm): YAML разбирается напрямую.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
K8S_DIR: Final[Path] = REPO_ROOT / "deploy" / "k8s"
SERVICE_FILE: Final[Path] = K8S_DIR / "service.yaml"
CONFIGMAP_FILE: Final[Path] = K8S_DIR / "configmap.yaml"

CLAMAV_SERVICE: Final[str] = "clamd"
OTEL_SERVICE: Final[str] = "otel-collector"
OPEN_WEBUI_SERVICE: Final[str] = "open-webui"

SIDECAR_SERVICES: Final[tuple[tuple[str, int], ...]] = (
    (CLAMAV_SERVICE, 3310),
    (OTEL_SERVICE, 4317),
    (OPEN_WEBUI_SERVICE, 3000),
)
"""Ожидаемые sidecar-Service: (имя, порт)."""


def _documents(path: Path) -> list[dict[str, Any]]:
    """Читает все YAML-документы файла.

    Args:
        path: Путь к YAML-файлу.

    Returns:
        Список разобранных mapping'ов.
    """
    with path.open("r", encoding="utf-8") as fh:
        return [doc for doc in yaml.safe_load_all(fh) if isinstance(doc, dict)]


def _services() -> dict[str, dict[str, Any]]:
    """Service-объекты из ``deploy/k8s/service.yaml``.

    Returns:
        Мапа ``имя Service`` → его спецификация.
    """
    services: dict[str, dict[str, Any]] = {}
    for doc in _documents(SERVICE_FILE):
        if doc.get("kind") != "Service":
            continue
        name = str((doc.get("metadata") or {}).get("name") or "")
        if name:
            services[name] = doc
    return services


def _configmap_data() -> dict[str, str]:
    """Данные ``gd-app-config`` из ``deploy/k8s/configmap.yaml``.

    Returns:
        Мапа ``env-имя`` → значение.
    """
    for doc in _documents(CONFIGMAP_FILE):
        if doc.get("kind") != "ConfigMap":
            continue
        data = doc.get("data") or {}
        if data:
            return {str(key): str(value) for key, value in data.items()}
    return {}


class TestSidecarServices:
    """Service-объекты для sidecar'ов присутствуют в манифестах."""

    @pytest.mark.parametrize(("name", "port"), SIDECAR_SERVICES)
    def test_service_exists_with_port(self, name: str, port: int) -> None:
        """Service объявлен и отдаёт ожидаемый порт."""
        services = _services()

        assert name in services, f"нет Service '{name}' в {SERVICE_FILE}"

        ports = {
            int(entry.get("port", 0))
            for entry in (services[name].get("spec") or {}).get("ports") or []
        }

        assert port in ports, (
            f"Service '{name}': нет порта {port} (есть {sorted(ports)})"
        )

    @pytest.mark.parametrize(("name", "port"), SIDECAR_SERVICES)
    def test_service_has_selector(self, name: str, port: int) -> None:
        """У Service есть selector — иначе он не сэтчит ни один pod."""
        services = _services()

        selector = (services[name].get("spec") or {}).get("selector") or {}

        assert selector, f"Service '{name}' без selector"


class TestConfigMapSidecarHosts:
    """ConfigMap содержит те же service-DNS хосты, что и профили."""

    def test_clamav_host_is_service_dns(self) -> None:
        """``WAF_CLAMAV_HOST`` — service-DNS имя sidecar'а clamd."""
        data = _configmap_data()

        assert data.get("WAF_CLAMAV_HOST") == CLAMAV_SERVICE

    def test_otel_endpoint_is_service_dns(self) -> None:
        """OTel-экспорт указывает на service-DNS имя otel-collector."""
        data = _configmap_data()
        endpoints = [
            value for key, value in data.items() if "OTEL" in key and "ENDPOINT" in key
        ]

        assert endpoints, "в ConfigMap нет OTel-эндпоинта"
        assert all(OTEL_SERVICE in value for value in endpoints), endpoints

    def test_open_webui_endpoint_is_service_dns(self) -> None:
        """Endpoint OpenWebUI — service-DNS имя open-webui."""
        data = _configmap_data()

        assert OPEN_WEBUI_SERVICE in data.get("OPEN_WEBUI_BASE_URL", "")

    def test_configmap_hosts_match_services(self) -> None:
        """Хосты ConfigMap соответствуют объявленным Service."""
        services = _services()
        data = _configmap_data()

        assert data.get("WAF_CLAMAV_HOST") in services
        assert OTEL_SERVICE in services
        assert OPEN_WEBUI_SERVICE in services


class TestReplicaDsnExample:
    """Пример DSN read-реплики — закомментированный (значение = секрет)."""

    def test_replica_dsn_example_is_commented(self) -> None:
        """В ConfigMap есть закомментированный пример DSN реплики."""
        text = CONFIGMAP_FILE.read_text(encoding="utf-8")
        example_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("#") and "DB_REPLICA_DSN" in line
        ]

        assert example_lines, "в configmap.yaml нет закомментированного DB_REPLICA_DSN"

        assert any(
            "postgresql+asyncpg://" in line and "<replica-host>" in line
            for line in example_lines
        ), example_lines

    def test_replica_dsn_is_not_in_configmap_data(self) -> None:
        """DSN реплики — секрет: в ``data`` ConfigMap его нет."""
        data = _configmap_data()

        assert "DB_REPLICA_DSN" not in data
