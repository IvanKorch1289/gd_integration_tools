"""Сервис метрик AI-агентов.

Собирает и экспортирует в Prometheus метрики вызовов AI:
  * время выполнения агента / чата (Histogram с p50/p95/p99);
  * количество tool-calls за сессию (Counter);
  * токены input/output по провайдерам (Counter);
  * процент успешных / неудачных вызовов (Counter);
  * стоимость вызова (Counter, если провайдер вернул usage cost);
  * статус feedback-разметки (Gauge).

Метрики регистрируются лениво: при отсутствии ``prometheus_client``
сервис превращается в no-op (не ломает импорт). Экспорт происходит
через существующий ``/metrics`` endpoint приложения.

История > 30 дней (ClickHouse) — реализуется в Wave 5.2 отдельным
``MetricsCollector``; тут только real-time Prometheus.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from src.backend.core.di import app_state_singleton

__all__ = ("AgentMetricsService", "get_agent_metrics_service")

logger = logging.getLogger("services.ai.metrics")


_NO_PROMETHEUS = "prometheus_client недоступен — AgentMetricsService работает в no-op"


class AgentMetricsService:
    """Сервис метрик AI-агентов с экспортом в Prometheus.

    Инкапсулирует семейство метрик с префиксом ``agent_``:
      * ``agent_execution_seconds`` (Histogram) — latency вызова агента;
      * ``agent_tokens_total`` (Counter) — токены по направлениям;
      * ``agent_calls_total`` (Counter) — успех/ошибка по провайдерам;
      * ``agent_tool_calls_total`` (Counter) — инструменты по агенту;
      * ``agent_cost_usd_total`` (Counter) — накопленная стоимость;
      * ``agent_feedback_total`` (Counter) — разметка ответов оператором.

    Все методы безопасны к отсутствию ``prometheus_client``: если
    библиотека не установлена, вызовы выполняются как no-op.

    Атрибуты:
        _initialized: Выполнена ли инициализация Prometheus-метрик.
        _histogram / _tokens / _calls / _tool / _cost / _feedback:
            Ссылки на метрики (``None`` в no-op режиме).
    """

    _BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0)

    def __init__(self) -> None:
        """Инициализирует сервис с ленивой загрузкой метрик."""
        self._initialized = False
        self._histogram: Any = None
        self._tokens: Any = None
        self._calls: Any = None
        self._tool: Any = None
        self._cost: Any = None
        self._feedback: Any = None
        self._ensure()

    def _ensure(self) -> None:
        """Лениво регистрирует Prometheus-метрики при первом вызове.

        При отсутствии ``prometheus_client`` помечает сервис
        как инициализированный (все методы становятся no-op).
        """
        if self._initialized:
            return
        try:
            from prometheus_client import Counter, Histogram

            self._histogram = Histogram(
                "agent_execution_seconds",
                "Длительность выполнения AI-агента, сек",
                labelnames=("agent_id", "provider", "status"),
                buckets=self._BUCKETS,
            )
            self._tokens = Counter(
                "agent_tokens_total",
                "Токены LLM по направлениям",
                labelnames=("provider", "model", "direction"),
            )
            self._calls = Counter(
                "agent_calls_total",
                "Вызовы AI-агентов по статусу",
                labelnames=("agent_id", "provider", "status"),
            )
            self._tool = Counter(
                "agent_tool_calls_total",
                "Вызовы инструментов AI-агентами",
                labelnames=("agent_id", "tool"),
            )
            self._cost = Counter(
                "agent_cost_usd_total",
                "Накопленная стоимость вызовов AI, USD",
                labelnames=("provider", "model"),
            )
            self._feedback = Counter(
                "agent_feedback_total",
                "Разметка feedback оператором",
                labelnames=("agent_id", "label"),
            )
        except ImportError:
            logger.info(_NO_PROMETHEUS)
        finally:
            self._initialized = True

    def record_execution(
        self,
        *,
        agent_id: str,
        provider: str,
        duration_seconds: float,
        status: str = "success",
    ) -> None:
        """Фиксирует длительность одного вызова агента.

        Args:
            agent_id: Логический идентификатор агента.
            provider: Фактически использованный LLM-провайдер.
            duration_seconds: Длительность вызова в секундах.
            status: ``success`` / ``error`` / ``timeout``.
        """
        if self._histogram is None or self._calls is None:
            return
        self._histogram.labels(
            agent_id=agent_id, provider=provider, status=status
        ).observe(max(duration_seconds, 0.0))
        self._calls.labels(agent_id=agent_id, provider=provider, status=status).inc()

    def record_tokens(
        self,
        *,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """Фиксирует расход токенов по направлениям.

        Args:
            provider: LLM-провайдер.
            model: Имя модели.
            input_tokens: Количество входных токенов.
            output_tokens: Количество выходных токенов.
        """
        if self._tokens is None:
            return
        if input_tokens:
            self._tokens.labels(provider=provider, model=model, direction="input").inc(
                input_tokens
            )
        if output_tokens:
            self._tokens.labels(provider=provider, model=model, direction="output").inc(
                output_tokens
            )

    def record_tool_call(self, *, agent_id: str, tool: str) -> None:
        """Фиксирует один вызов инструмента агентом.

        Args:
            agent_id: Идентификатор агента.
            tool: Имя вызванного инструмента.
        """
        if self._tool is None:
            return
        self._tool.labels(agent_id=agent_id, tool=tool).inc()

    def record_cost(self, *, provider: str, model: str, cost_usd: float) -> None:
        """Фиксирует стоимость одного вызова LLM в USD.

        Args:
            provider: LLM-провайдер.
            model: Имя модели.
            cost_usd: Стоимость вызова (из usage-поля ответа).
        """
        if self._cost is None or cost_usd <= 0:
            return
        self._cost.labels(provider=provider, model=model).inc(cost_usd)

    def record_feedback(self, *, agent_id: str, label: str) -> None:
        """Фиксирует разметку feedback оператором.

        Args:
            agent_id: Идентификатор агента, чей ответ оценили.
            label: ``positive`` / ``negative`` / ``skip``.
        """
        if self._feedback is None:
            return
        self._feedback.labels(agent_id=agent_id, label=label).inc()

    @contextmanager
    def track_execution(
        self, *, agent_id: str, provider: str
    ) -> Iterator[dict[str, Any]]:
        """Контекст-менеджер для измерения latency агента.

        Args:
            agent_id: Идентификатор агента.
            provider: LLM-провайдер (обновляется через ``ctx["provider"]``).

        Yields:
            Изменяемый словарь: можно переопределить ``provider``
            и ``status`` по фактическому результату.

        Пример::

            with metrics.track_execution(agent_id="risk", provider="openai") as ctx:
                result = await agent.run(...)
                ctx["provider"] = result["provider"]
                ctx["status"] = "success" if result["success"] else "error"
        """
        start = time.perf_counter()
        ctx = {"provider": provider, "status": "success"}
        try:
            yield ctx
        except Exception:
            ctx["status"] = "error"
            raise
        finally:
            duration = time.perf_counter() - start
            self.record_execution(
                agent_id=agent_id,
                provider=str(ctx.get("provider") or provider),
                duration_seconds=duration,
                status=str(ctx.get("status") or "success"),
            )


@app_state_singleton("agent_metrics_service", factory=AgentMetricsService)
def get_agent_metrics_service() -> AgentMetricsService:
    """Возвращает singleton ``AgentMetricsService`` из ``app.state``."""
