"""ProcessorHealthService — координатор processor-specific health-checks.

W9 P2-13 Phase 4 (cycle 153): извлечено из ``services/ops/health.py``
(609 LOC god-module).

Регистрирует именованные async-checks через ``register_check``, выполняет их
параллельно через ``asyncio.TaskGroup`` (Python 3.14, PEP 654 structured
concurrency) для structured concurrency. Feature-flag
``processor_health_checks_strict`` (default-OFF) управляет strict mode.

Back-compat: ``services/ops/health.py`` (file) продолжает re-export через
thin ``__init__.py`` shim (см. ADR-0329).

V15 R-V15-15: НЕ создавать ``.from_health_check()`` или ``HealthCheckProcessor`` —
используется обычный сервис + регистрация через ActionSpec (см. tech.py).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.services.ops.health._types import ProcessorHealthResult

logger = get_logger("services.ops.health")


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
                return await asyncio.wait_for(
                    check(), timeout=self._timeout_per_check_s
                )
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
        from src.backend.services.ops.health._checks import _is_strict_mode

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
        from src.backend.services.ops.health._checks import (
            _check_clickhouse,
            _check_graylog,
            _check_kafka_schema_registry,
            _check_nats,
            _check_redis_cluster,
            _check_temporal_server,
            _check_vault_sealed,
        )

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
