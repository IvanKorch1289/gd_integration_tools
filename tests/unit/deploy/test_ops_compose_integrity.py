"""Регрессия: целостность prod/compose-стека (аудит 2026-11-18).

Зона: ``ops/compose/**`` + ``ops/compose/Dockerfile``. Тесты статические
(``yaml.safe_load`` + разбор текста Dockerfile) — Docker не требуется.

Подтверждённые дефекты, закрытые этим файлом:

1. **Конфликт host-портов.** В ``docker-compose.prod.yml`` MinIO публиковал
   host-порт 9000, и ClickHouse (native) — тоже 9000; JupyterHub — 8000,
   как и ``app``. При старте второго претендента на порт Docker отдаёт
   «port is already allocated» → стек не поднимался целиком.
2. **Healthcheck на несуществующем маршруте.** ``app`` в prod-compose
   проверял ``/docs``; в prod-профиле ``app.enable_swagger=false``, то
   есть FastAPI монтируется без ``docs_url`` → 404 → сервис вечно
   unhealthy. Perf-compose проверял ``/api/v1/health`` — такого маршрута
   нет (в v1-роутере только ``/liveness``, ``/readiness``, ``/startup``,
   ``/components``).
3. **Healthcheck на бинарнике, которого нет в образе.** ``curl`` был
   установлен только в builder-слое Dockerfile; в runtime-слое его нет,
   а curl используют prod/perf/bluegreen-compose.
4. **Fail-open на миграциях.** ``migration-runner`` выполнял
   ``alembic upgrade head || true`` → падение миграции не мешало
   ``depends_on: service_completed_successfully``, и приложение стартовало
   поверх неактуальной схемы БД.
5. **Сервисы, которые не могут стартовать.** ``celery-worker``/
   ``celery-beat`` звали ``python -m celery -A src.backend.tasks.celery_app``,
   при этом ни пакет ``celery`` (в pyproject/uv.lock), ни модуль
   ``src/backend/tasks/`` в проекте не существуют → гарантированный
   CrashLoopBackOff и ненулевой код выхода ``docker compose up``.
6. **Хардкод секретов в prod-compose.** Vault работал в dev-режиме с
   root-токеном ``gd-dev-token``, зашитым в репозиторий; у MinIO был
   дефолтный пароль ``minioadmin``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
COMPOSE_DIR: Final[Path] = PROJECT_ROOT / "ops" / "compose"
BASE_COMPOSE: Final[Path] = COMPOSE_DIR / "docker-compose.yml"
PROD_COMPOSE: Final[Path] = COMPOSE_DIR / "docker-compose.prod.yml"
PERF_COMPOSE: Final[Path] = COMPOSE_DIR / "docker-compose.perf.yml"
BLUEGREEN_COMPOSE: Final[Path] = COMPOSE_DIR / "docker-compose.bluegreen.yml"
LIGHT_COMPOSE: Final[Path] = COMPOSE_DIR / "docker-compose.light.yml"
DOCKERFILE: Final[Path] = COMPOSE_DIR / "Dockerfile"

#: Compose-файлы, чьи healthcheck'и бьют по приложению.
APP_HEALTHCHECK_COMPOSES: Final[tuple[Path, ...]] = (
    PROD_COMPOSE,
    PERF_COMPOSE,
    BLUEGREEN_COMPOSE,
    LIGHT_COMPOSE,
)

#: Реально зарегистрированные liveness/health-маршруты приложения.
#: Источник — ``src/backend/plugins/composition/app_factory.py`` (root-level)
#: и ``src/backend/entrypoints/api/v1/endpoints/health.py`` (v1-роутер).
KNOWN_HEALTH_ROUTES: Final[frozenset[str]] = frozenset(
    {
        "/health",
        "/health/live",
        "/health/ready",
        "/ready",
        "/livez",
        "/healthz",
        "/readyz",
        "/api/v1/health/liveness",
        "/api/v1/health/readiness",
        "/api/v1/health/startup",
    }
)

#: Бинарники, которые могут вызываться в healthcheck'ах compose.
KNOWN_HEALTHCHECK_BINARIES: Final[frozenset[str]] = frozenset(
    {
        "curl",
        "python",
        "python3",
        "nc",
        "pg_isready",
        "redis-cli",
        "clickhouse-client",
        "mc",
        "wget",
        "kafka-broker-api-versions",
    }
)


def _load_yaml(path: Path) -> dict[str, Any]:
    """Прочитать YAML-файл.

    Args:
        path: Путь к файлу.

    Returns:
        Разобранный mapping.

    """
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    assert isinstance(data, dict)
    return data


def _merged_services() -> dict[str, dict[str, Any]]:
    """Сервисы объединённого стека base + prod (как в docker compose).

    Returns:
        Mapping ``имя сервиса → описание`` с применённым prod-оверлеем.

    """
    base = _load_yaml(BASE_COMPOSE)["services"]
    prod = _load_yaml(PROD_COMPOSE)["services"]
    merged: dict[str, dict[str, Any]] = {k: dict(v) for k, v in base.items()}
    for name, overlay in prod.items():
        target = merged.setdefault(name, {})
        for key, value in overlay.items():
            if key == "ports" and "ports" in target:
                target[key] = list(target[key]) + list(value)
            elif key == "environment" and "environment" in target:
                env = dict(target[key] or {})
                env.update(value or {})
                target[key] = env
            else:
                target[key] = value
    return merged


def _published_ports(services: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Собрать host-порты по сервисам.

    Args:
        services: Mapping сервисов.

    Returns:
        Mapping ``host-порт → список сервисов``.

    """
    ports: dict[str, list[str]] = {}
    for name, service in services.items():
        for raw in service.get("ports") or []:
            text = str(raw)
            published = text.split(":")[0] if ":" in text else text
            ports.setdefault(published, []).append(name)
    return ports


def _dockerfile_runtime_packages() -> set[str]:
    """Пакеты, установленные в RUNTIME-слое образа.

    Returns:
        Множество имён apt-пакетов из runtime-слоя.

    """
    text = DOCKERFILE.read_text(encoding="utf-8")
    runtime = text.split("AS runtime", 1)[-1]
    packages: set[str] = set()
    for block in re.findall(
        r"apt-get install -y --no-install-recommends\s+(.*?)(?:&&|\\\n\s*$)",
        runtime,
        flags=re.DOTALL,
    ):
        for token in re.split(r"[\\\s]+", block):
            token = token.strip()
            if token and not token.startswith("#") and "apt-get" not in token:
                packages.add(token)
    return packages


class TestHostPortUniqueness:
    """Host-порты объединённого prod-стека не должны конфликтовать."""

    def test_no_duplicate_published_ports(self) -> None:
        """Ни один host-порт не публикуется двумя сервисами.

        Регресс: MinIO (9000) против ClickHouse (9000) и JupyterHub (8000)
        против app (8000) — `docker compose up` падал с «port is already
        allocated».
        """
        conflicts = {
            port: names
            for port, names in _published_ports(_merged_services()).items()
            if len(names) > 1
        }

        assert not conflicts, f"конфликт host-портов в prod-стеке: {conflicts}"

    def test_clickhouse_and_minio_use_distinct_host_ports(self) -> None:
        """ClickHouse (native) и MinIO (API) публикуют разные host-порты."""
        services = _merged_services()

        def _port(service: str) -> str:
            raw = str((services[service].get("ports") or [""])[0])
            return raw.split(":")[0]

        assert _port("clickhouse") != _port("minio")
        assert _port("jupyterhub") != _port("app")

    def test_in_network_ports_unchanged(self) -> None:
        """Host-порт меняется, порт внутри compose-сети — нет.

        Приложение ходит по service-DNS (``clickhouse:9000``,
        ``jupyterhub:8000``), поэтому host-mapping менять безопасно, а
        container-порт — нельзя.
        """
        prod = _load_yaml(PROD_COMPOSE)["services"]

        clickhouse = [str(p) for p in prod["clickhouse"]["ports"]]
        assert any(p.endswith(":9000") for p in clickhouse), clickhouse
        jupyterhub = [str(p) for p in prod["jupyterhub"]["ports"]]
        assert any(p.endswith(":8000") for p in jupyterhub), jupyterhub


class TestHealthcheckCorrectness:
    """Healthcheck'и должны бить по существующим маршрутам и бинарникам."""

    @pytest.mark.parametrize("compose_file", APP_HEALTHCHECK_COMPOSES)
    def test_healthcheck_url_is_a_real_route(self, compose_file: Path) -> None:
        """URL healthcheck'а приложения — зарегистрированный маршрут.

        Регресс: ``/docs`` в prod (swagger отключён → 404) и
        ``/api/v1/health`` в perf-compose (такого маршрута нет).
        """
        services = _load_yaml(compose_file)["services"]
        checked = 0
        for name, service in services.items():
            healthcheck = service.get("healthcheck") or {}
            test = healthcheck.get("test")
            if not test:
                continue
            joined = " ".join(str(part) for part in test)
            for route in re.findall(r"https?://[^/\"' ]+(/[^\"' ]*)?", joined):
                path = route or "/"
                path = path.split("?")[0].rstrip("/") or "/"
                if not path.startswith(
                    ("/health", "/ready", "/livez", "/api/v1/health")
                ):
                    continue
                checked += 1
                assert path in KNOWN_HEALTH_ROUTES, (
                    f"{compose_file.name}:{name}: healthcheck бьёт по "
                    f"несуществующему маршруту {path!r}"
                )
        assert checked, f"{compose_file.name}: не найдено ни одного healthcheck URL"

    def test_app_healthcheck_not_docs(self) -> None:
        """Prod-compose не проверяет ``/docs`` (в prod swagger выключен)."""
        services = _load_yaml(PROD_COMPOSE)["services"]
        joined = " ".join(
            str(part)
            for part in (services["app"].get("healthcheck") or {}).get("test", [])
        )

        assert "/docs" not in joined, (
            "app.healthcheck бьёт по /docs — в prod-профиле enable_swagger=false"
        )

    def test_healthcheck_binaries_present_in_runtime_image(self) -> None:
        """Каждый бинарник из healthcheck'а установлен в runtime-слое.

        Регресс: ``curl`` был только в builder-слое → все curl-healthcheck'и
        падали с «executable file not found».

        Проверяются только сервисы, собираемые из ``ops/compose/Dockerfile``
        (у сторонних образов — свои бинарники).
        """
        packages = _dockerfile_runtime_packages()

        assert "curl" in packages, (
            f"curl не установлен в runtime-слое: {sorted(packages)}"
        )

        for compose_file in APP_HEALTHCHECK_COMPOSES:
            services = _load_yaml(compose_file)["services"]
            for name, service in services.items():
                build = service.get("build") or {}
                if "Dockerfile" not in str(build.get("dockerfile", "")):
                    continue
                test = (service.get("healthcheck") or {}).get("test")
                if not test:
                    continue
                joined = " ".join(str(part) for part in test)
                for binary in re.findall(
                    r"\b(curl|wget|nc|pg_isready|redis-cli|mc)\b", joined
                ):
                    assert binary in packages, (
                        f"{compose_file.name}:{name}: healthcheck использует "
                        f"{binary!r}, которого нет в runtime-слое образа"
                    )


class TestMigrationRunnerFailClosed:
    """Миграции не должны «проглатывать» ошибку."""

    def test_migration_runner_has_no_ignore_errors(self) -> None:
        """``migration-runner`` не подавляет код возврата alembic.

        Регресс: ``alembic upgrade head || true`` делал шаг всегда
        «успешным» → ``depends_on: service_completed_successfully``
        срабатывал → приложение стартовало поверх старой схемы.
        """
        services = _load_yaml(BASE_COMPOSE)["services"]
        command = " ".join(
            str(part) for part in services["migration-runner"]["command"]
        )

        assert "||" not in command, (
            f"migration-runner подавляет ошибку миграции: {command!r}"
        )
        assert "alembic" in command and "upgrade head" in command


class TestCeleryServicesAreOptIn:
    """Celery-сервисы не должны ломать дефолтный prod-стек."""

    def test_celery_services_are_profile_gated(self) -> None:
        """Celery-сервисы — только за явным ``--profile celery``.

        Регресс: пакет ``celery`` и модуль ``src.backend.tasks.celery_app``
        в проекте отсутствуют → контейнеры гарантированно падали в
        CrashLoopBackOff, а ``docker compose up`` завершался с ошибкой.
        """
        services = _load_yaml(PROD_COMPOSE)["services"]
        celery_services = {
            name: service
            for name, service in services.items()
            if name.startswith("celery")
        }

        for name, service in celery_services.items():
            profiles = service.get("profiles") or []
            assert "celery" in profiles, (
                f"{name}: celery-сервис без profiles — не может стартовать "
                "(нет ни пакета celery, ни модуля src.backend.tasks.celery_app)"
            )

    def test_celery_app_module_absent(self) -> None:
        """Модуля ``src/backend/tasks/celery_app.py`` действительно нет."""
        assert not (
            PROJECT_ROOT / "src" / "backend" / "tasks" / "celery_app.py"
        ).exists()


class TestProdComposeSecrets:
    """Секреты prod-compose — только из env, без дефолтов."""

    def test_vault_root_token_not_hardcoded(self) -> None:
        """Root-токен Vault не зашит в репозиторий."""
        services = _load_yaml(PROD_COMPOSE)["services"]
        vault = services["vault"]

        command = " ".join(str(part) for part in vault["command"])
        assert "gd-dev-token" not in command, "vault: root-токен зашит в compose-файл"
        token = str(vault["environment"]["VAULT_DEV_ROOT_TOKEN_ID"])
        assert token.startswith("${") and ":?" in token, (
            f"vault: root-токен не fail-closed: {token!r}"
        )

    def test_minio_password_has_no_default(self) -> None:
        """У MinIO нет дефолтного пароля ``minioadmin``."""
        services = _load_yaml(PROD_COMPOSE)["services"]
        password = str(services["minio"]["environment"]["MINIO_ROOT_PASSWORD"])

        assert ":?" in password, (
            f"minio: пароль имеет дефолт (fail-closed требует ':?'): {password!r}"
        )
        assert "minioadmin" not in password


class TestDockerfileReproducibility:
    """Образ собирается воспроизводимо."""

    def test_base_image_pinned_by_digest(self) -> None:
        """Оба базовых образа закреплены по digest."""
        text = DOCKERFILE.read_text(encoding="utf-8")
        from_lines = [line for line in text.splitlines() if line.startswith("FROM ")]

        assert from_lines, "в Dockerfile нет FROM"
        for line in from_lines:
            assert "@sha256:" in line, f"базовый образ не закреплён по digest: {line}"

    def test_uv_image_pinned(self) -> None:
        """``uv`` тянется не из ``latest``, а из закреплённого тега/digest."""
        text = DOCKERFILE.read_text(encoding="utf-8")
        uv_copy = [line for line in text.splitlines() if "astral-sh/uv" in line]

        assert uv_copy, "uv не копируется из официального образа"
        for line in uv_copy:
            assert ":latest" not in line, f"uv берётся из latest: {line}"
            assert "@sha256:" in line, f"uv не закреплён по digest: {line}"

    def test_ruamel_yaml_install_is_pinned(self) -> None:
        """``ruamel-yaml`` ставится с точной версией, а не «latest».

        Регресс: ``uv pip install ruamel-yaml`` тянул свежую версию из
        PyPI мимо ``uv.lock`` → невоспроизводимая сборка образа.
        """
        text = DOCKERFILE.read_text(encoding="utf-8")
        install_lines = [
            line
            for line in text.splitlines()
            if "ruamel-yaml" in line
            and "uv pip" in line
            and not line.strip().startswith("#")
        ]

        assert install_lines, "ruamel-yaml не устанавливается в Dockerfile"
        for line in install_lines:
            assert re.search(r"ruamel-yaml==\d", line), (
                f"ruamel-yaml установлен без точной версии: {line.strip()!r}"
            )
