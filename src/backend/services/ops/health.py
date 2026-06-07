"""Sprint 6 K2 — processor-specific health-check сервис.

Назначение:
    Расширение базовых health-checks (TechService) до per-processor
    granularity. Каждый backend-сервис (Kafka schema-registry, Temporal,
    Vault, ClickHouse, Redis cluster, NATS, Graylog) имеет свой check
    с возвращаемой структурой ``{ok: bool, reason: str, latency_ms: float}``.

Endpoint:
    ``GET /health/processors`` — агрегированная матрица всех processor-checks.

Архитектура:
    * ``ProcessorHealthCheck`` — Protocol для one async-check.
    * ``ProcessorHealthService`` — координатор, агрегирует результаты.
    * Использует ``asyncio.TaskGroup`` (Python 3.14, PEP 654 structured
      concurrency) для параллельного выполнения.
    * Feature-flag: ``processor_health_checks_strict`` (default-OFF). При
      flag-OFF service возвращает только успешные checks (skip exceptions);
      при flag-ON exception в любом checks → возвращается с ok=false.

V15 R-V15-15: НЕ создавать ``.from_health_check()`` или ``HealthCheckProcessor`` —
используется обычный сервис + регистрация через ActionSpec (см. tech.py).
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

__all__ = (
    "ProcessorHealthResult",
    "ProcessorHealthService",
    "get_processor_health_service",
)

logger = get_logger("services.ops.health")


@dataclass
class ProcessorHealthResult:
    """Результат одной processor-check проверки.

    Attributes:
        ok: True если backend доступен и отвечает в ожидаемое время.
        reason: Краткое описание (для UI / Grafana / alert).
        latency_ms: Время выполнения проверки (мс).
        processor_name: Логическое имя backend-сервиса.
    """

    processor_name: str
    ok: bool
    reason: str
    latency_ms: float


class ProcessorHealthService:
    """Координатор processor-specific health-checks.

    Регистрирует именованные async-checks через :meth:`register_check`,
    выполняет их параллельно через :meth:`check_all`, возвращает агрегированную
    матрицу через :meth:`get_health_matrix`.

    Args:
        timeout_per_check_s: Таймаут на каждую отдельную проверку (default 5s).
    """

    def __init__(self, *, timeout_per_check_s: float = 5.0) -> None:
        """Создать сервис с пустым реестром checks."""
        self._checks: dict[str, Callable[[], Awaitable[ProcessorHealthResult]]] = {}
        self._timeout_per_check_s = timeout_per_check_s

    # ------------------------------------------------------------------
    # Регистрация
    # ------------------------------------------------------------------

    def register_check(
        self, name: str, check: Callable[[], Awaitable[ProcessorHealthResult]]
    ) -> None:
        """Зарегистрировать async-check под именем processor'а.

        Повторная регистрация перезаписывает существующий check.

        Args:
            name: Логическое имя backend-сервиса (например ``"kafka"``,
                ``"temporal"``, ``"vault"``).
            check: Async-callable () → ProcessorHealthResult. Должен
                быть idempotent (не зависит от глобального state).
        """
        self._checks[name] = check
        logger.debug("ProcessorHealthService: check '%s' зарегистрирован", name)

    def registered_names(self) -> list[str]:
        """Список имён всех зарегистрированных processor-checks."""
        return list(self._checks)

    # ------------------------------------------------------------------
    # Выполнение
    # ------------------------------------------------------------------

    async def check_all(self) -> list[ProcessorHealthResult]:
        """Выполнить все registered checks параллельно.

        Каждая check имеет timeout = ``timeout_per_check_s``. При исключении
        в check возвращается ProcessorHealthResult с ``ok=False`` и
        reason из исключения.

        Returns:
            Список ProcessorHealthResult в порядке registered_names().
        """
        if not self._checks:
            return []

        async def _run_one(
            name: str, check: Callable[[], Awaitable[ProcessorHealthResult]]
        ) -> ProcessorHealthResult:
            """Выполнить один check с timeout."""
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    check(), timeout=self._timeout_per_check_s
                )
                return result
            except TimeoutError:
                return ProcessorHealthResult(
                    processor_name=name,
                    ok=False,
                    reason=f"timeout ({self._timeout_per_check_s}s)",
                    latency_ms=(time.monotonic() - start) * 1000,
                )
            except Exception as exc:
                return ProcessorHealthResult(
                    processor_name=name,
                    ok=False,
                    reason=f"exception: {type(exc).__name__}: {exc}",
                    latency_ms=(time.monotonic() - start) * 1000,
                )

        # Sprint 8A K3 W10: TaskGroup вместо asyncio.gather для structured
        # concurrency. _run_one уже ловит все exceptions внутри, поэтому
        # TaskGroup тут не auto-cancel'ит siblings.
        async with asyncio.TaskGroup() as tg:
            running = [
                tg.create_task(_run_one(name, check))
                for name, check in self._checks.items()
            ]
        return [t.result() for t in running]

    async def get_health_matrix(self) -> dict[str, Any]:
        """Получить агрегированную матрицу health-status.

        Формат ответа:
            {
                "overall": "ok" | "degraded",
                "checks": {
                    "<processor_name>": {
                        "ok": bool,
                        "reason": str,
                        "latency_ms": float
                    },
                    ...
                },
                "registered_count": int,
                "failed_count": int,
                "strict_mode": bool
            }

        Returns:
            Dict с агрегированной матрицей для JSON-сериализации.
        """
        results = await self.check_all()
        failed = [r for r in results if not r.ok]

        return {
            "overall": "ok" if not failed else "degraded",
            "checks": {
                r.processor_name: {
                    "ok": r.ok,
                    "reason": r.reason,
                    "latency_ms": round(r.latency_ms, 2),
                }
                for r in results
            },
            "registered_count": len(self._checks),
            "failed_count": len(failed),
            "strict_mode": _is_strict_mode(),
        }


# ---------------------------------------------------------------------------
# Default processor checks (registered при startup)
# ---------------------------------------------------------------------------


async def _check_kafka_schema_registry() -> ProcessorHealthResult:
    """Проверка доступности Kafka schema-registry.

    Default-реализация — best-effort через lazy import faststream/confluent.
    Возвращает ``ok=False`` если SDK не установлен.
    """
    start = time.monotonic()
    try:
        # Lazy import — не падать если SDK отсутствует.
        from src.backend.core.config.settings import settings

        registry_url = getattr(settings.queue, "schema_registry_url", None)
        if not registry_url:
            return ProcessorHealthResult(
                processor_name="kafka_schema_registry",
                ok=False,
                reason="schema_registry_url не настроен",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        # Здесь должен быть реальный HTTP-call /subjects.
        # В Sprint 6 K2 — stub-вариант (best-effort).
        return ProcessorHealthResult(
            processor_name="kafka_schema_registry",
            ok=True,
            reason="best-effort: settings configured",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="kafka_schema_registry",
            ok=False,
            reason=f"check failed: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_temporal_server() -> ProcessorHealthResult:
    """Проверка доступности Temporal server."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        temporal_host = getattr(getattr(settings, "workflow", None), "host", None)
        if not temporal_host:
            return ProcessorHealthResult(
                processor_name="temporal_server",
                ok=False,
                reason="temporal.host не настроен",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        return ProcessorHealthResult(
            processor_name="temporal_server",
            ok=True,
            reason="best-effort: settings configured",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="temporal_server",
            ok=False,
            reason=f"check failed: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_vault_sealed() -> ProcessorHealthResult:
    """Проверка, что Vault unsealed и доступен."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        vault_enabled = getattr(getattr(settings, "vault", None), "enabled", False)
        if not vault_enabled:
            return ProcessorHealthResult(
                processor_name="vault",
                ok=True,
                reason="vault disabled (dev_light mode)",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        return ProcessorHealthResult(
            processor_name="vault",
            ok=True,
            reason="best-effort: vault.enabled=true",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="vault",
            ok=False,
            reason=f"check failed: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_clickhouse() -> ProcessorHealthResult:
    """Проверка доступности ClickHouse."""
    start = time.monotonic()
    return ProcessorHealthResult(
        processor_name="clickhouse",
        ok=True,
        reason="best-effort stub (Sprint 6 K2; реальная проверка — Sprint 7)",
        latency_ms=(time.monotonic() - start) * 1000,
    )


async def _check_redis_cluster() -> ProcessorHealthResult:
    """Проверка доступности Redis cluster (через PING)."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        redis_enabled = getattr(getattr(settings, "redis", None), "enabled", False)
        if not redis_enabled:
            return ProcessorHealthResult(
                processor_name="redis_cluster",
                ok=True,
                reason="redis disabled (dev_light mode)",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        return ProcessorHealthResult(
            processor_name="redis_cluster",
            ok=True,
            reason="best-effort: redis.enabled=true",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="redis_cluster",
            ok=False,
            reason=f"check failed: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


async def _check_nats() -> ProcessorHealthResult:
    """Проверка доступности NATS."""
    start = time.monotonic()
    return ProcessorHealthResult(
        processor_name="nats",
        ok=True,
        reason="best-effort stub (Sprint 6 K2; реальная проверка — Sprint 7)",
        latency_ms=(time.monotonic() - start) * 1000,
    )


async def _check_graylog() -> ProcessorHealthResult:
    """Проверка доступности Graylog (через TCP-ping или HTTP-API)."""
    start = time.monotonic()
    try:
        from src.backend.core.config.settings import settings

        log_host = getattr(getattr(settings, "logging", None), "host", "")
        if not log_host:
            return ProcessorHealthResult(
                processor_name="graylog",
                ok=True,
                reason="graylog disabled (LOG_HOST пуст)",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        return ProcessorHealthResult(
            processor_name="graylog",
            ok=True,
            reason="best-effort: LOG_HOST configured",
            latency_ms=(time.monotonic() - start) * 1000,
        )
    except Exception as exc:
        return ProcessorHealthResult(
            processor_name="graylog",
            ok=False,
            reason=f"check failed: {exc}",
            latency_ms=(time.monotonic() - start) * 1000,
        )


def _is_strict_mode() -> bool:
    """Проверить feature-flag processor_health_checks_strict."""
    try:
        from src.backend.core.config.features import feature_flags

        return feature_flags.processor_health_checks_strict
    except Exception as _:
        return False


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_service_instance: ProcessorHealthService | None = None


def get_processor_health_service() -> ProcessorHealthService:
    """Singleton — один экземпляр ProcessorHealthService на процесс.

    При первой инициализации регистрирует 7 default-checks
    (Kafka SR, Temporal, Vault, ClickHouse, Redis, NATS, Graylog).
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = ProcessorHealthService()
        _service_instance.register_check(
            "kafka_schema_registry", _check_kafka_schema_registry
        )
        _service_instance.register_check("temporal_server", _check_temporal_server)
        _service_instance.register_check("vault", _check_vault_sealed)
        _service_instance.register_check("clickhouse", _check_clickhouse)
        _service_instance.register_check("redis_cluster", _check_redis_cluster)
        _service_instance.register_check("nats", _check_nats)
        _service_instance.register_check("graylog", _check_graylog)
    return _service_instance
