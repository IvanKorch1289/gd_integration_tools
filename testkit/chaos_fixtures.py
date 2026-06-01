"""Chaos-fixtures для resilience-тестов K5 Sprint 6.

Назначение:
    Набор pytest-фикстур, обёртывающих ``toxiproxy`` поверх стандартных
    backend-контейнеров (PostgreSQL/Redis/Kafka/RabbitMQ/Temporal/ClickHouse/
    Vault/S3/Graylog/Elasticsearch/NATS). Каждая фикстура создаёт
    ``ToxiproxyContainer`` рядом с реальным backend'ом и возвращает прокси,
    через который можно эмулировать latency / disconnect / data-corruption.

Использование::

    @pytest.mark.chaos
    @pytest.mark.requires_toxiproxy
    async def test_postgres_latency(toxiproxy_pg):
        client, proxy = toxiproxy_pg
        proxy.add_toxic("latency", "downstream", attributes={"latency": 500})
        ...

Если ``testcontainers[toxiproxy]`` / Docker недоступен — фикстура поднимает
``pytest.skip("toxiproxy недоступен")``, чтобы chaos-suite оставался warn-only
в CI без блокирующего сбоя (см. ``chaos_tests_blocking`` feature-flag).

Все фикстуры — модульного scope, чтобы амортизировать стоимость поднятия
контейнеров между сценариями одного chain.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

__all__ = (
    "ChaosScenario",
    "ChaosTarget",
    "apply_disconnect",
    "apply_latency",
    "apply_random_drop",
    "toxiproxy_clickhouse",
    "toxiproxy_es",
    "toxiproxy_graylog",
    "toxiproxy_kafka",
    "toxiproxy_nats",
    "toxiproxy_pg",
    "toxiproxy_rabbitmq",
    "toxiproxy_redis",
    "toxiproxy_s3",
    "toxiproxy_temporal",
    "toxiproxy_vault",
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ChaosTarget:
    """Описание прокси-цели, возвращается фикстурами.

    Attributes:
        name: Логическое имя backend'а (например ``"pg"``).
        proxy_host: Хост прокси для подключения клиента.
        proxy_port: Порт прокси.
        upstream_host: Реальный backend host (для cleanup).
        upstream_port: Реальный backend port.
        proxy: Сырой объект proxy (``toxiproxy.Proxy``) если testcontainers
            установлен; ``None`` при degraded режиме.
    """

    name: str
    proxy_host: str
    proxy_port: int
    upstream_host: str
    upstream_port: int
    proxy: Any | None = None


@dataclass(slots=True, frozen=True)
class ChaosScenario:
    """Описание сценария применения хаоса.

    Attributes:
        kind: Один из ``"latency"`` / ``"disconnect"`` / ``"corruption"``.
        latency_ms: Задержка в мс (для kind=latency).
        toxicity: Вероятность применения toxic (0..1).
    """

    kind: str
    latency_ms: int = 500
    toxicity: float = 1.0


# ---------------------------------------------------------------------------
# Helpers: применяют toxic к target. Дёшевы no-op если proxy is None.
# ---------------------------------------------------------------------------


def apply_latency(target: ChaosTarget, latency_ms: int = 500) -> None:
    """Включает latency-toxic в downstream направлении.

    Args:
        target: Объект, возвращённый одной из toxiproxy-фикстур.
        latency_ms: Задержка в миллисекундах.

    Raises:
        pytest.skip.Exception: Если proxy недоступен (degraded mode).
    """
    if target.proxy is None:
        pytest.skip(f"toxiproxy недоступен для {target.name}")
    try:
        target.proxy.add_toxic(
            name=f"{target.name}-latency",
            type="latency",
            stream="downstream",
            toxicity=1.0,
            attributes={"latency": latency_ms},
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"toxiproxy add_toxic latency failed: {exc}")


def apply_disconnect(target: ChaosTarget) -> None:
    """Полностью разрывает соединение с upstream (reset_peer-like).

    Если toxiproxy SDK не поддерживает ``reset_peer`` — используется
    ``disable()`` proxy, эквивалентный disconnect.

    Args:
        target: Объект, возвращённый toxiproxy-фикстурой.
    """
    if target.proxy is None:
        pytest.skip(f"toxiproxy недоступен для {target.name}")
    try:
        # reset_peer toxic, если поддерживается SDK
        try:
            target.proxy.add_toxic(
                name=f"{target.name}-reset",
                type="reset_peer",
                stream="downstream",
                toxicity=1.0,
                attributes={"timeout": 0},
            )
        except Exception:  # noqa: BLE001
            # Fallback: disable() — proxy refuses new connections.
            target.proxy.disable()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"toxiproxy disconnect failed: {exc}")


def apply_random_drop(target: ChaosTarget, toxicity: float = 0.3) -> None:
    """Включает limit_data + slicer-toxic для data-corruption.

    Эмулирует случайное обрезание/искажение payload путём slice-toxic
    с малым average_size. ``toxicity`` определяет долю соединений.

    Args:
        target: Объект, возвращённый toxiproxy-фикстурой.
        toxicity: Вероятность toxic (0..1).
    """
    if target.proxy is None:
        pytest.skip(f"toxiproxy недоступен для {target.name}")
    try:
        target.proxy.add_toxic(
            name=f"{target.name}-slicer",
            type="slicer",
            stream="downstream",
            toxicity=toxicity,
            attributes={"average_size": 64, "size_variation": 32, "delay": 0},
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"toxiproxy slicer failed: {exc}")


# ---------------------------------------------------------------------------
# Internal helper: поднимает Toxiproxy-контейнер один раз на module-session.
# ---------------------------------------------------------------------------


def _can_open_port(host: str, port: int, timeout: float = 0.5) -> bool:
    """Быстрая проверка доступности TCP-порта (без зависимостей).

    Используется как fallback-detector «у нас НЕТ docker / нет sidecar»,
    чтобы избежать долгого pulling testcontainers wheel.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _make_toxiproxy_target(
    name: str,
    upstream_host: str,
    upstream_port: int,
) -> ChaosTarget:
    """Поднимает Toxiproxy и создаёт proxy → upstream.

    При отсутствии testcontainers/Docker — возвращает ``ChaosTarget`` с
    ``proxy=None``, что приведёт к ``pytest.skip`` в любой helper-функции.
    Это сохраняет green-suite в окружениях без Docker (CI dev_light /
    локальный без toxiproxy образа).
    """
    try:
        from testcontainers.toxiproxy import (
            ToxiproxyContainer,  # type: ignore[import-untyped]
        )
    except ImportError:
        logger.warning(
            "testcontainers[toxiproxy] не установлен — chaos-фикстура %s "
            "вернёт degraded target (proxy=None, тесты будут skipped).",
            name,
        )
        return ChaosTarget(
            name=name,
            proxy_host=upstream_host,
            proxy_port=upstream_port,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            proxy=None,
        )

    # Docker недоступен → degraded target, skip
    if not _can_open_port(upstream_host, upstream_port):
        return ChaosTarget(
            name=name,
            proxy_host=upstream_host,
            proxy_port=upstream_port,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            proxy=None,
        )

    try:
        container = ToxiproxyContainer().with_name(f"toxiproxy-{name}")
        container.start()
        proxy = container.add_proxy(
            name=f"{name}_proxy",
            upstream=f"{upstream_host}:{upstream_port}",
        )
        return ChaosTarget(
            name=name,
            proxy_host=container.get_container_host_ip(),
            proxy_port=container.get_exposed_port(proxy.listen.split(":")[1]),
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            proxy=proxy,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Toxiproxy bootstrap failed для %s: %s", name, exc)
        return ChaosTarget(
            name=name,
            proxy_host=upstream_host,
            proxy_port=upstream_port,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
            proxy=None,
        )


# ---------------------------------------------------------------------------
# 11 toxiproxy-фикстур (1 на chain).
# Все фикстуры module-scope для амортизации стоимости контейнеров.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def toxiproxy_pg() -> Iterator[ChaosTarget]:
    """Toxiproxy перед PostgreSQL backend'ом."""
    target = _make_toxiproxy_target("pg", "127.0.0.1", 5432)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_redis() -> Iterator[ChaosTarget]:
    """Toxiproxy перед Redis backend'ом."""
    target = _make_toxiproxy_target("redis", "127.0.0.1", 6379)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_kafka() -> Iterator[ChaosTarget]:
    """Toxiproxy перед Kafka broker."""
    target = _make_toxiproxy_target("kafka", "127.0.0.1", 9092)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_rabbitmq() -> Iterator[ChaosTarget]:
    """Toxiproxy перед RabbitMQ broker."""
    target = _make_toxiproxy_target("rabbitmq", "127.0.0.1", 5672)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_temporal() -> Iterator[ChaosTarget]:
    """Toxiproxy перед Temporal frontend."""
    target = _make_toxiproxy_target("temporal", "127.0.0.1", 7233)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_clickhouse() -> Iterator[ChaosTarget]:
    """Toxiproxy перед ClickHouse native protocol."""
    target = _make_toxiproxy_target("clickhouse", "127.0.0.1", 9000)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_vault() -> Iterator[ChaosTarget]:
    """Toxiproxy перед HashiCorp Vault."""
    target = _make_toxiproxy_target("vault", "127.0.0.1", 8200)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_s3() -> Iterator[ChaosTarget]:
    """Toxiproxy перед S3-совместимым хранилищем (MinIO)."""
    target = _make_toxiproxy_target("s3", "127.0.0.1", 9001)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_graylog() -> Iterator[ChaosTarget]:
    """Toxiproxy перед Graylog GELF input."""
    target = _make_toxiproxy_target("graylog", "127.0.0.1", 12201)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_es() -> Iterator[ChaosTarget]:
    """Toxiproxy перед Elasticsearch HTTP."""
    target = _make_toxiproxy_target("es", "127.0.0.1", 9200)
    yield target


@pytest.fixture(scope="module")
def toxiproxy_nats() -> Iterator[ChaosTarget]:
    """Toxiproxy перед NATS."""
    target = _make_toxiproxy_target("nats", "127.0.0.1", 4222)
    yield target
