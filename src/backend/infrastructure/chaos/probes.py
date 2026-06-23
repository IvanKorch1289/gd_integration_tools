"""Chaos engineering probes — controlled fault injection (S37.4).

Назначение:
    Инструменты для намеренного внесения сбоев в dev/staging средах
    с целью проверки отказоустойчивости (graceful degradation,
    circuit breaker, fallback chains, retry logic).

    В production режиме все пробы должны быть ОТКЛЮЧЕНЫ через
    feature-flag ``chaos_engineering_enabled`` (default ``False``).

Пробы:
    * ``LatencyProbe`` — случайная задержка перед операцией.
    * ``ErrorProbe`` — случайное выбрасывание исключения.
    * ``PoolExhaustionProbe`` — временное снижение max_size пула до 0.
    * ``PartitionProbe`` — временное отключение health-check для пула.

S168 W11 P2-1 DECISION (per master prompt v8):
    KEEP custom probes. Decision rationale:
    - 4 probe types integrated with project-specific concerns
      (pool exhaustion, partition simulation)
    - test coverage: tests/unit/infrastructure/test_chaos_probes.py
    - lightweight (294 LOC, no external deps)
    - feature-flag controlled (chaos_engineering_enabled default False)

    REJECTED alternatives:
    - chaostoolkit: heavier framework, focuses on full experiment
      definitions (steady-state hypothesis, rollback). Not aligned
      with our use case (lightweight in-process fault injection).
    - chaos-mesh: requires Kubernetes deployment, not relevant.

    Migration path: extract probe types to interface if chaostoolkit
    adoption needed in future. Per Ponytail minimum, no change required
    now — current implementation matches use case.

Использование::

    # В middleware / processor / handler
    from src.backend.infrastructure.chaos.probes import get_chaos_engineering
    chaos = get_chaos_engineering()
    await chaos.latency("http_request", probability=0.1, max_delay_ms=200)
    chaos.maybe_raise("db_query", probability=0.05, exc=ConnectionError("chaos"))

    # В тестах
    async with chaos.exhaust_pool("db_main", duration_seconds=3):
        await service.fetch_data()   # должен использовать fallback/cache
"""

from __future__ import annotations

import asyncio
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.feature_flags import get_feature_flag_service
from src.backend.core.logging import get_logger

__all__ = ("ChaosEngineering", "get_chaos_engineering", "is_chaos_enabled")

logger = get_logger("infrastructure.chaos")


@dataclass
class ChaosConfig:
    """Конфигурация одного chaos-эксперимента.

    Attributes:
        name: Идентификатор эксперимента.
        enabled: Активен ли прямо сейчас.
        probability: Вероятность срабатывания [0.0, 1.0].
        parameters: Произвольные параметры (задержка, тип ошибки и т.д.).
    """

    name: str
    enabled: bool = False
    probability: float = 0.0
    parameters: dict[str, Any] = field(default_factory=dict)


class ChaosEngineering:
    """Контейнер для chaos-probes.

    Все методы — no-op если ``is_chaos_enabled()`` возвращает ``False``.
    Это позволяет оставлять вызовы в production-коде без риска.
    """

    def __init__(self) -> None:
        self._experiments: dict[str, ChaosConfig] = {}

    # ------------------------------------------------------------------
    # Experiment management
    # ------------------------------------------------------------------

    def register(
        self, name: str, probability: float = 0.0, **params: Any
    ) -> ChaosConfig:
        """Регистрирует или обновляет chaos-эксперимент."""
        cfg = ChaosConfig(
            name=name, enabled=True, probability=probability, parameters=params
        )
        self._experiments[name] = cfg
        logger.info("Chaos experiment registered: %s (p=%.2f)", name, probability)
        return cfg

    def unregister(self, name: str) -> None:
        self._experiments.pop(name, None)

    def get(self, name: str) -> ChaosConfig | None:
        return self._experiments.get(name)

    # ------------------------------------------------------------------
    # Probes
    # ------------------------------------------------------------------

    async def latency(
        self,
        name: str,
        *,
        probability: float | None = None,
        max_delay_ms: float = 500.0,
    ) -> None:
        """Внедряет случайную задержку перед продолжением.

        Args:
            name: Имя эксперимента (для логирования и lookup).
            probability: Вероятность срабатывания (override).
            max_delay_ms: Максимальная задержка в миллисекундах.
        """
        if not is_chaos_enabled():
            return
        cfg = self._experiments.get(name)
        p = (
            probability
            if probability is not None
            else (cfg.probability if cfg else 0.0)
        )
        if p <= 0.0 or random.random() > p:  # noqa: S311
            return
        delay = random.uniform(0, max_delay_ms) / 1000.0  # noqa: S311
        logger.warning("Chaos latency injected: %s delay=%.3fs", name, delay)
        await asyncio.sleep(delay)

    def maybe_raise(
        self,
        name: str,
        *,
        probability: float | None = None,
        exc: Exception | None = None,
    ) -> None:
        """Случайно выбрасывает исключение.

        Args:
            name: Имя эксперимента.
            probability: Вероятность срабатывания (override).
            exc: Экземпляр исключения для raise (default ``RuntimeError``).
        """
        if not is_chaos_enabled():
            return
        cfg = self._experiments.get(name)
        p = (
            probability
            if probability is not None
            else (cfg.probability if cfg else 0.0)
        )
        if p <= 0.0 or random.random() > p:  # noqa: S311
            return
        error = exc or RuntimeError(f"Chaos error probe: {name}")
        logger.warning("Chaos error injected: %s — %s", name, error)
        raise error

    @asynccontextmanager
    async def exhaust_pool(self, name: str, duration_seconds: float = 5.0):
        """Временно «исчерпывает» пул — устанавливает max_size=0.

        Восстанавливает исходный размер при выходе из контекста.
        Подходит для проверки fallback-цепочек при недоступности DB.

        Args:
            name: Логическое имя пула из UnifiedPoolManager.
            duration_seconds: Длительность эксперимента.

        Yields:
            None
        """
        if not is_chaos_enabled():
            yield
            return

        from src.backend.infrastructure.clients.unified_pool_manager import (
            get_unified_pool_manager,
        )

        manager = get_unified_pool_manager()
        reg = manager._pools.get(name)
        if reg is None:
            logger.warning("Chaos exhaust_pool: pool '%s' not found", name)
            yield
            return

        pool = reg.pool
        original_max = None
        attr_name = None
        pool_target = None
        for candidate in ("_pool", "pool", "connection_pool"):
            target = getattr(pool, candidate, pool)
            for attr in ("max_size", "max_connections", "maxsize"):
                if hasattr(target, attr):
                    try:
                        original_max = getattr(target, attr)
                        attr_name = attr
                        pool_target = target
                        break
                    except Exception:
                        pass
            if attr_name:
                break

        if attr_name is None:
            logger.warning("Chaos exhaust_pool: pool '%s' has no size attribute", name)
            yield
            return

        try:
            setattr(pool_target, attr_name, 0)
            logger.warning(
                "Chaos pool exhausted: %s (original %s=%s, duration=%.1fs)",
                name,
                attr_name,
                original_max,
                duration_seconds,
            )
            await asyncio.sleep(duration_seconds)
            yield
        finally:
            if original_max is not None:
                setattr(pool_target, attr_name, original_max)
                logger.info(
                    "Chaos pool restored: %s (%s=%s)", name, attr_name, original_max
                )

    @asynccontextmanager
    async def partition(self, name: str, duration_seconds: float = 5.0):
        """Временно «разрывает» связь с пулом — делает ping_fn no-op.

        Полезно для проверки поведения health-check и circuit breaker.

        Args:
            name: Логическое имя пула из UnifiedPoolManager.
            duration_seconds: Длительность эксперимента.
        """
        if not is_chaos_enabled():
            yield
            return

        from src.backend.infrastructure.clients.unified_pool_manager import (
            get_unified_pool_manager,
        )

        manager = get_unified_pool_manager()
        reg = manager._pools.get(name)
        if reg is None:
            logger.warning("Chaos partition: pool '%s' not found", name)
            yield
            return

        original_ping = reg.ping_fn

        async def _broken_ping() -> None:
            raise ConnectionError(f"Chaos partition probe: {name}")

        try:
            reg.ping_fn = _broken_ping
            logger.warning(
                "Chaos partition started: %s (duration=%.1fs)", name, duration_seconds
            )
            await asyncio.sleep(duration_seconds)
            yield
        finally:
            reg.ping_fn = original_ping
            logger.info("Chaos partition ended: %s", name)


# ---------------------------------------------------------------------------
# Feature-flag
# ---------------------------------------------------------------------------


def is_chaos_enabled() -> bool:
    """Проверяет feature-flag ``chaos_engineering_enabled``.

    Returns ``False`` при любой ошибке импорта (safe default).
    """
    try:
        return get_feature_flag_service().is_enabled("chaos_engineering_enabled")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_chaos_instance: ChaosEngineering | None = None


def get_chaos_engineering() -> ChaosEngineering:
    """Возвращает singleton ChaosEngineering."""
    global _chaos_instance
    if _chaos_instance is None:
        _chaos_instance = ChaosEngineering()
    return _chaos_instance
