import asyncio
import logging
from typing import Any, Callable

import orjson

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from app.dsl.engine.processors.base import BaseProcessor

_eip_logger = logging.getLogger("dsl.eip")
_camel_logger = logging.getLogger("dsl.camel")

__all__ = (
    "DeadLetterProcessor",
    "IdempotentConsumerProcessor",
    "FallbackChainProcessor",
    "WireTapProcessor",
    "MessageTranslatorProcessor",
    "DynamicRouterProcessor",
    "ScatterGatherProcessor",
    "ThrottlerProcessor",
    "DelayProcessor",
    "SplitterProcessor",
    "AggregatorProcessor",
    "RecipientListProcessor",
    "LoadBalancerProcessor",
    "CircuitBreakerProcessor",
    "ClaimCheckProcessor",
    "NormalizerProcessor",
    "ResequencerProcessor",
    "MulticastProcessor",
)


class DeadLetterProcessor(BaseProcessor):
    """Dead Letter Channel — направляет упавшие Exchange в DLQ.

    Оборачивает sub-pipeline. При неуспехе сохраняет Exchange
    в DLQ-хранилище (Redis stream) с полным контекстом ошибки.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        dlq_stream: str = "dsl-dlq",
        max_retries: int = 0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "dead_letter")
        self._processors = processors
        self._dlq_stream = dlq_stream
        self._max_retries = max_retries

    async def _send_to_dlq(self, exchange: Exchange[Any]) -> None:
        try:
            from app.infrastructure.clients.redis import redis_client

            dlq_entry = {
                "exchange_id": exchange.meta.exchange_id,
                "route_id": exchange.meta.route_id or "",
                "correlation_id": exchange.meta.correlation_id,
                "error": exchange.error or "unknown",
                "body": orjson.dumps(
                    exchange.in_message.body, default=str
                ).decode()[:8192] if exchange.in_message.body else "",
                "properties": orjson.dumps(
                    exchange.properties, default=str
                ).decode()[:4096],
                "timestamp": exchange.meta.created_at.isoformat(),
            }
            await redis_client.add_to_stream(
                stream_name=self._dlq_stream,
                data=dlq_entry,
            )
            _eip_logger.info(
                "Exchange %s sent to DLQ stream '%s'",
                exchange.meta.exchange_id,
                self._dlq_stream,
            )
        except Exception as dlq_exc:
            _eip_logger.error("Failed to send to DLQ: %s", dlq_exc)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        for proc in self._processors:
            if exchange.status == ExchangeStatus.failed or exchange.stopped:
                break
            try:
                await proc.process(exchange, context)
            except Exception as exc:
                exchange.fail(str(exc))
                break

        if exchange.status == ExchangeStatus.failed:
            await self._send_to_dlq(exchange)


class IdempotentConsumerProcessor(BaseProcessor):
    """Idempotent Consumer — предотвращает повторную обработку.

    Использует Redis SET NX EX для дедупликации по ключу.
    Если сообщение уже обработано, Exchange останавливается.
    """

    def __init__(
        self,
        key_expression: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 86400,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "idempotent_consumer")
        self._key_expr = key_expression
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            from app.infrastructure.clients.redis import redis_client

            dedup_key = f"idempotent:{self._key_expr(exchange)}"
            is_new = await redis_client.set_if_not_exists(
                key=dedup_key, value="1", ttl=self._ttl
            )
            if not is_new:
                _eip_logger.debug(
                    "Duplicate message filtered: key=%s", dedup_key
                )
                exchange.set_property("idempotent_duplicate", True)
                exchange.stop()
                return
        except Exception as exc:
            _eip_logger.warning(
                "Idempotent check failed (proceeding): %s", exc
            )


class FallbackChainProcessor(BaseProcessor):
    """Fallback Chain — последовательно пробует процессоры.

    Выполняет первый процессор. При ошибке — следующий.
    Останавливается на первом успешном. Если все провалились —
    Exchange завершается ошибкой последнего.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"fallback_chain({len(processors)})")
        self._processors = processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        last_error: str | None = None

        for i, proc in enumerate(self._processors):
            exchange.status = ExchangeStatus.processing
            exchange.error = None
            exchange.properties.pop("_stopped", None)

            try:
                await proc.process(exchange, context)
                if exchange.status != ExchangeStatus.failed:
                    exchange.set_property("fallback_used", i)
                    return
                last_error = exchange.error
            except Exception as exc:
                last_error = str(exc)
                _eip_logger.debug(
                    "Fallback %d (%s) failed: %s", i, proc.name, exc
                )

        exchange.fail(f"All fallbacks exhausted. Last error: {last_error}")


class WireTapProcessor(BaseProcessor):
    """Wire Tap — копирует Exchange в отдельный канал.

    Не влияет на основной поток. Полезно для логирования,
    аудита, отладки.

    Args:
        tap_processors: Процессоры, обрабатывающие копию Exchange.
    """

    def __init__(
        self,
        tap_processors: list[BaseProcessor],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "wire_tap")
        self._tap_processors = tap_processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        tap_exchange = Exchange(
            in_message=Message(
                body=exchange.in_message.body,
                headers=dict(exchange.in_message.headers),
            )
        )
        tap_exchange.meta.route_id = exchange.meta.route_id
        tap_exchange.meta.correlation_id = exchange.meta.correlation_id
        tap_exchange.properties = dict(exchange.properties)
        tap_exchange.status = ExchangeStatus.processing

        async def _run_tap() -> None:
            for proc in self._tap_processors:
                if tap_exchange.status == ExchangeStatus.failed:
                    break
                try:
                    await proc.process(tap_exchange, context)
                except Exception as exc:
                    _eip_logger.debug("Wire tap processor error: %s", exc)

        task = asyncio.create_task(_run_tap())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


# ---------------------------------------------------------------------------
#  Apache Camel-inspired процессоры
# ---------------------------------------------------------------------------


class MessageTranslatorProcessor(BaseProcessor):
    """Конвертация форматов: JSON↔XML, JSON↔CSV.

    Работает через подключаемые конвертеры. По умолчанию
    поддерживает json→xml, xml→json, dict→csv, csv→dict.
    """

    def __init__(
        self,
        from_format: str,
        to_format: str,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"translate:{from_format}→{to_format}")
        self._from = from_format
        self._to = to_format

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        converted = self._convert(body)
        exchange.set_out(body=converted, headers=dict(exchange.in_message.headers))

    def _convert(self, body: Any) -> Any:
        key = f"{self._from}→{self._to}"

        if key in ("json→xml", "dict→xml"):
            return self._dict_to_xml(body if isinstance(body, dict) else {})

        if key in ("xml→json", "xml→dict"):
            return self._xml_to_dict(body if isinstance(body, str) else str(body))

        if key in ("dict→csv", "json→csv"):
            return self._dict_list_to_csv(body if isinstance(body, list) else [body])

        if key in ("csv→dict", "csv→json"):
            return self._csv_to_dict_list(body if isinstance(body, str) else str(body))

        return body

    @staticmethod
    def _dict_to_xml(data: dict, root_tag: str = "root") -> str:
        try:
            import xmltodict
            return xmltodict.unparse({root_tag: data}, pretty=True)
        except ImportError:
            parts = [f"<{root_tag}>"]
            for k, v in data.items():
                parts.append(f"  <{k}>{v}</{k}>")
            parts.append(f"</{root_tag}>")
            return "\n".join(parts)

    @staticmethod
    def _xml_to_dict(xml_str: str) -> dict[str, Any]:
        try:
            import xmltodict
            parsed = xmltodict.parse(xml_str)
            if len(parsed) == 1:
                return dict(next(iter(parsed.values())))
            return dict(parsed)
        except ImportError:
            import re as _re
            return {m.group(1): m.group(2) for m in _re.finditer(r"<(\w+)>([^<]*)</\1>", xml_str)}

    @staticmethod
    def _dict_list_to_csv(data: list[dict]) -> str:
        if not data:
            return ""
        try:
            import pandas as pd
            import io
            df = pd.DataFrame(data)
            return df.to_csv(index=False)
        except ImportError:
            headers = list(data[0].keys())
            lines = [",".join(headers)]
            for row in data:
                lines.append(",".join(str(row.get(h, "")) for h in headers))
            return "\n".join(lines)

    @staticmethod
    def _csv_to_dict_list(csv_str: str) -> list[dict[str, str]]:
        try:
            import pandas as pd
            import io
            df = pd.read_csv(io.StringIO(csv_str))
            return df.to_dict(orient="records")
        except ImportError:
            lines = csv_str.strip().split("\n")
            if len(lines) < 2:
                return []
            headers = [h.strip() for h in lines[0].split(",")]
            return [
                dict(zip(headers, [v.strip() for v in line.split(",")]))
                for line in lines[1:]
            ]


class DynamicRouterProcessor(BaseProcessor):
    """Маршрутизация на основе runtime-выражения.

    Вычисляет route_id из Exchange, затем делегирует
    выполнение соответствующему DSL-маршруту.
    """

    def __init__(
        self,
        route_expression: Callable[[Exchange[Any]], str],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "dynamic_router")
        self._expr = route_expression

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.dsl.commands.registry import route_registry
        from app.dsl.engine.processors.base import SubPipelineExecutor

        target_route_id = self._expr(exchange)
        if not route_registry.is_registered(target_route_id):
            exchange.fail(f"Dynamic route '{target_route_id}' not found")
            return

        result, error = await SubPipelineExecutor.execute_route(
            target_route_id, exchange.in_message.body,
            dict(exchange.in_message.headers), context,
        )
        if error:
            exchange.fail(f"Dynamic route '{target_route_id}' failed: {error}")
            return

        exchange.set_property("dynamic_route_used", target_route_id)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class ScatterGatherProcessor(BaseProcessor):
    """Fan-out на N маршрутов → сборка результатов.

    Отправляет копию Exchange на несколько DSL-маршрутов
    параллельно, собирает результаты в ``scatter_results``.
    """

    def __init__(
        self,
        route_ids: list[str],
        *,
        aggregation: str = "merge",
        timeout_seconds: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"scatter_gather({len(route_ids)})")
        self._route_ids = route_ids
        self._aggregation = aggregation
        self._timeout = timeout_seconds

    async def _call_route(
        self, route_id: str, body: Any, headers: dict, context: ExecutionContext
    ) -> tuple[str, Any, str | None]:
        from app.dsl.engine.processors.base import SubPipelineExecutor

        return await SubPipelineExecutor.execute_route_safe(
            route_id, body, headers, context,
        )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        tasks = [
            self._call_route(rid, exchange.in_message.body, exchange.in_message.headers, context)
            for rid in self._route_ids
        ]

        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            exchange.fail(f"Scatter-gather timeout ({self._timeout}s)")
            return

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for item in raw_results:
            if isinstance(item, Exception):
                errors["_exception"] = str(item)
            else:
                rid, result, error = item
                if error:
                    errors[rid] = error
                else:
                    results[rid] = result

        exchange.set_property("scatter_results", results)
        if errors:
            exchange.set_property("scatter_errors", errors)

        if self._aggregation == "merge" and results:
            merged: dict[str, Any] = {}
            for v in results.values():
                if isinstance(v, dict):
                    merged.update(v)
            exchange.set_out(body=merged, headers=dict(exchange.in_message.headers))


class ThrottlerProcessor(BaseProcessor):
    """Rate-limit per route: N сообщений в секунду.

    Использует token bucket для контроля пропускной
    способности. При превышении — задержка.
    """

    def __init__(
        self,
        rate: float,
        *,
        burst: int = 1,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"throttle({rate}/s)")
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = 0.0
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time

        async with self._lock:
            now = time.monotonic()
            if self._last_refill == 0.0:
                self._last_refill = now

            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


class DelayProcessor(BaseProcessor):
    """Задержка обработки на N миллисекунд или до timestamp."""

    def __init__(
        self,
        delay_ms: int | None = None,
        *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"delay({delay_ms}ms)")
        self._delay_ms = delay_ms
        self._scheduled_fn = scheduled_time_fn

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time

        if self._scheduled_fn is not None:
            target = self._scheduled_fn(exchange)
            now = time.time()
            if target > now:
                await asyncio.sleep(target - now)
        elif self._delay_ms is not None and self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000.0)


class SplitterProcessor(BaseProcessor):
    """Разбивает массив из body на отдельные Exchange.

    Каждый элемент обрабатывается sub-процессорами.
    Результаты собираются в ``split_results``.
    """

    def __init__(
        self,
        expression: str,
        processors: list[BaseProcessor],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"splitter:{expression[:20]}")
        self._expression = expression
        self._processors = processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import jmespath

        body = exchange.in_message.body
        items = jmespath.search(self._expression, body)
        if not isinstance(items, list):
            exchange.set_property("split_results", [])
            return

        results: list[Any] = []
        for item in items:
            sub_exchange = Exchange(
                in_message=Message(body=item, headers=dict(exchange.in_message.headers))
            )
            sub_exchange.status = ExchangeStatus.processing

            for proc in self._processors:
                if sub_exchange.status == ExchangeStatus.failed or sub_exchange.stopped:
                    break
                await proc.process(sub_exchange, context)

            result = (
                sub_exchange.out_message.body
                if sub_exchange.out_message
                else sub_exchange.in_message.body
            )
            results.append(result)

        exchange.set_property("split_results", results)
        exchange.set_out(body=results, headers=dict(exchange.in_message.headers))


class AggregatorProcessor(BaseProcessor):
    """Собирает N Exchange по correlation_id.

    Накапливает результаты в shared state (context.state),
    выдаёт агрегированный результат по достижении ``batch_size``
    или ``timeout``.
    """

    _MAX_CORRELATION_KEYS = 10000

    def __init__(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
        max_buffer_size: int = 100000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"aggregator(batch={batch_size})")
        self._corr_key = correlation_key
        self._batch_size = batch_size
        self._timeout = timeout_seconds
        self._max_buffer = max_buffer_size
        self._buffers: dict[str, list[Any]] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = self._corr_key(exchange)

        async with self._lock:
            if len(self._buffers) >= self._MAX_CORRELATION_KEYS:
                oldest = next(iter(self._buffers))
                del self._buffers[oldest]

            buf = self._buffers.setdefault(key, [])
            if len(buf) >= self._max_buffer:
                buf.pop(0)
            buf.append(exchange.in_message.body)

            if len(buf) >= self._batch_size:
                aggregated = list(buf)
                buf.clear()
                exchange.set_property("aggregated", True)
                exchange.set_out(body=aggregated, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property("aggregated", False)
                exchange.set_property("buffer_size", len(buf))
                exchange.stop()


class RecipientListProcessor(BaseProcessor):
    """Отправляет сообщение на динамический список маршрутов.

    Список маршрутов вычисляется из Exchange. Каждый получатель
    получает копию сообщения. Результаты собираются в property.
    """

    def __init__(
        self,
        recipients_expression: Callable[[Exchange[Any]], list[str]],
        *,
        parallel: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "recipient_list")
        self._expr = recipients_expression
        self._parallel = parallel

    async def _send_to(
        self, route_id: str, body: Any, headers: dict, context: ExecutionContext
    ) -> tuple[str, Any, str | None]:
        from app.dsl.engine.processors.base import SubPipelineExecutor

        return await SubPipelineExecutor.execute_route_safe(
            route_id, body, headers, context,
        )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        recipients = self._expr(exchange)
        if not recipients:
            return

        body = exchange.in_message.body
        headers = exchange.in_message.headers

        if self._parallel:
            tasks = [self._send_to(rid, body, headers, context) for rid in recipients]
            raw = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            raw = []
            for rid in recipients:
                raw.append(await self._send_to(rid, body, headers, context))

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for item in raw:
            if isinstance(item, Exception):
                errors["_exception"] = str(item)
            else:
                rid, result, error = item
                if error:
                    errors[rid] = error
                else:
                    results[rid] = result

        exchange.set_property("recipient_results", results)
        if errors:
            exchange.set_property("recipient_errors", errors)


# ---------------------------------------------------------------------------
#  Apache Camel EIP v2 — LoadBalancer, CircuitBreaker, ClaimCheck,
#  Normalizer, Resequencer, Multicast
# ---------------------------------------------------------------------------


class LoadBalancerProcessor(BaseProcessor):
    """Camel Load Balancer EIP — distributes exchanges across multiple routes.

    Strategies: round_robin, random, weighted, sticky (header-based).
    """

    def __init__(
        self,
        targets: list[str],
        *,
        strategy: str = "round_robin",
        weights: list[float] | None = None,
        sticky_header: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"load_balancer({strategy})")
        self._targets = targets
        self._strategy = strategy
        self._weights = weights
        self._sticky_header = sticky_header
        self._rr_index = 0

    def _select_target(self, exchange: Exchange[Any]) -> str:
        if self._strategy == "round_robin":
            target = self._targets[self._rr_index % len(self._targets)]
            self._rr_index += 1
            return target

        if self._strategy == "random":
            import random as _random
            return _random.choice(self._targets)

        if self._strategy == "weighted" and self._weights:
            import random as _random
            return _random.choices(self._targets, weights=self._weights, k=1)[0]

        if self._strategy == "sticky" and self._sticky_header:
            key = exchange.in_message.headers.get(self._sticky_header, "")
            idx = hash(key) % len(self._targets)
            return self._targets[idx]

        return self._targets[0]

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.dsl.engine.processors.base import SubPipelineExecutor

        target = self._select_target(exchange)
        exchange.set_property("lb_target", target)

        result, error = await SubPipelineExecutor.execute_route(
            target, exchange.in_message.body,
            dict(exchange.in_message.headers), context,
        )
        if error:
            exchange.fail(f"Load balancer target '{target}' failed: {error}")
            return
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class CircuitBreakerProcessor(BaseProcessor):
    """Camel Circuit Breaker EIP — fail-fast pattern inside DSL pipeline.

    Wraps sub-processors with CLOSED → OPEN → HALF_OPEN state machine.
    When open, immediately routes to fallback or fails.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 1,
        fallback_processors: list[BaseProcessor] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"circuit_breaker(threshold={failure_threshold})")
        self._processors = processors
        self._fallback = fallback_processors or []
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max = half_open_max
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time = 0.0
        self._half_open_calls = 0

    def _check_state(self) -> str:
        import time
        if self._state == "open":
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = "half_open"
                self._half_open_calls = 0
        return self._state

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time
        from app.dsl.engine.processors.base import run_sub_processors

        state = self._check_state()

        if state == "open":
            if self._fallback:
                exchange.set_property("cb_state", "open_fallback")
                await run_sub_processors(self._fallback, exchange, context)
                return
            exchange.fail("Circuit breaker is OPEN")
            return

        if state == "half_open":
            self._half_open_calls += 1
            if self._half_open_calls > self._half_open_max:
                exchange.fail("Circuit breaker HALF_OPEN: max calls exceeded")
                return

        saved_status = exchange.status
        await run_sub_processors(self._processors, exchange, context)

        if exchange.status == ExchangeStatus.failed:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._threshold:
                self._state = "open"
            exchange.set_property("cb_state", self._state)
        else:
            if self._state == "half_open":
                self._state = "closed"
            self._failure_count = 0
            exchange.set_property("cb_state", self._state)


class ClaimCheckProcessor(BaseProcessor):
    """Camel Claim Check EIP — store payload, pass token through pipeline.

    mode="store": saves body to Redis, replaces with claim token.
    mode="retrieve": loads body from Redis using the token.
    """

    def __init__(
        self,
        *,
        mode: str = "store",
        store: str = "redis",
        ttl_seconds: int = 3600,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"claim_check:{mode}")
        self._mode = mode
        self._store = store
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import uuid

        if self._mode == "store":
            token = f"claim:{uuid.uuid4()}"
            body_bytes = orjson.dumps(exchange.in_message.body, default=str)
            try:
                from app.infrastructure.clients.redis import redis_client
                await redis_client.set_if_not_exists(
                    key=token, value=body_bytes.decode(), ttl=self._ttl,
                )
            except (ConnectionError, TimeoutError, OSError) as exc:
                _camel_logger.warning("Claim check store failed: %s", exc)
                return

            exchange.set_property("_claim_token", token)
            exchange.set_out(
                body={"_claim_token": token},
                headers=dict(exchange.in_message.headers),
            )

        elif self._mode == "retrieve":
            token = exchange.properties.get("_claim_token")
            if not token:
                body = exchange.in_message.body
                if isinstance(body, dict):
                    token = body.get("_claim_token")

            if not token:
                exchange.fail("No claim token found")
                return

            try:
                from app.infrastructure.clients.redis import redis_client
                raw = await redis_client.get(token)
                if raw is None:
                    exchange.fail(f"Claim token expired or not found: {token}")
                    return
                restored = orjson.loads(raw)
                exchange.set_out(
                    body=restored,
                    headers=dict(exchange.in_message.headers),
                )
            except (ConnectionError, TimeoutError, OSError) as exc:
                exchange.fail(f"Claim check retrieve failed: {exc}")


class NormalizerProcessor(BaseProcessor):
    """Camel Normalizer EIP — auto-detect input format and normalize to canonical dict.

    Detects XML, CSV, YAML, JSON string and converts to dict,
    then optionally validates against a Pydantic schema.
    """

    def __init__(
        self,
        target_schema: type | None = None,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "normalizer")
        self._schema = target_schema

    @staticmethod
    def _detect_and_parse(body: Any) -> Any:
        if isinstance(body, dict):
            return body
        if isinstance(body, list):
            return body
        if not isinstance(body, str):
            return body

        text = body.strip()

        if text.startswith("<"):
            try:
                import xmltodict
                parsed = xmltodict.parse(text)
                if len(parsed) == 1:
                    return dict(next(iter(parsed.values())))
                return dict(parsed)
            except Exception:
                pass

        if text.startswith("{") or text.startswith("["):
            try:
                return orjson.loads(text)
            except Exception:
                pass

        try:
            import yaml
            result = yaml.safe_load(text)
            if isinstance(result, (dict, list)):
                return result
        except Exception:
            pass

        lines = text.split("\n")
        if len(lines) >= 2 and "," in lines[0]:
            headers = [h.strip() for h in lines[0].split(",")]
            return [
                dict(zip(headers, [v.strip() for v in line.split(",")]))
                for line in lines[1:] if line.strip()
            ]

        return body

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        normalized = self._detect_and_parse(body)

        if self._schema is not None:
            try:
                validated = self._schema.model_validate(normalized)
                exchange.set_property("normalized_model", validated)
                normalized = validated.model_dump()
            except Exception as exc:
                exchange.fail(f"Normalization validation failed: {exc}")
                return

        exchange.set_out(body=normalized, headers=dict(exchange.in_message.headers))


class ResequencerProcessor(BaseProcessor):
    """Camel Resequencer EIP — reorder messages by sequence field.

    Buffers messages by correlation key, emits them in sequence order
    when batch is complete or timeout expires.
    """

    _MAX_KEYS = 10000

    def __init__(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        sequence_field: str = "seq",
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"resequencer(batch={batch_size})")
        self._corr_key = correlation_key
        self._seq_field = sequence_field
        self._batch_size = batch_size
        self._timeout = timeout_seconds
        self._buffers: dict[str, list[tuple[int, Any]]] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = self._corr_key(exchange)
        body = exchange.in_message.body

        seq = 0
        if isinstance(body, dict):
            seq = body.get(self._seq_field, 0)
        elif hasattr(body, self._seq_field):
            seq = getattr(body, self._seq_field, 0)

        async with self._lock:
            if len(self._buffers) >= self._MAX_KEYS:
                oldest = next(iter(self._buffers))
                del self._buffers[oldest]

            buf = self._buffers.setdefault(key, [])
            buf.append((seq, body))

            if len(buf) >= self._batch_size:
                buf.sort(key=lambda x: x[0])
                ordered = [item for _, item in buf]
                buf.clear()
                exchange.set_property("resequenced", True)
                exchange.set_out(body=ordered, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property("resequenced", False)
                exchange.set_property("resequence_buffer_size", len(buf))
                exchange.stop()


class MulticastProcessor(BaseProcessor):
    """Camel Multicast EIP — send one message to N processor lists in parallel.

    Unlike ParallelProcessor (named branches), Multicast works with
    a flat list of processor groups and aggregates results.
    """

    def __init__(
        self,
        branches: list[list[BaseProcessor]],
        *,
        strategy: str = "all",
        stop_on_error: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"multicast({len(branches)})")
        self._branches = branches
        self._strategy = strategy
        self._stop_on_error = stop_on_error

    async def _run_branch(
        self,
        index: int,
        processors: list[BaseProcessor],
        body: Any,
        headers: dict[str, Any],
        context: ExecutionContext,
    ) -> tuple[int, Any, str | None]:
        branch_exchange = Exchange(
            in_message=Message(body=body, headers=dict(headers))
        )
        branch_exchange.status = ExchangeStatus.processing

        for proc in processors:
            if branch_exchange.status == ExchangeStatus.failed or branch_exchange.stopped:
                break
            try:
                await proc.process(branch_exchange, context)
            except Exception as exc:
                branch_exchange.fail(str(exc))
                break

        result = (
            branch_exchange.out_message.body
            if branch_exchange.out_message
            else branch_exchange.in_message.body
        )
        return index, result, branch_exchange.error

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        headers = exchange.in_message.headers

        tasks = [
            self._run_branch(i, procs, body, headers, context)
            for i, procs in enumerate(self._branches)
        ]

        results: list[Any] = [None] * len(self._branches)
        errors: dict[int, str] = {}

        if self._strategy == "first":
            done, pending = await asyncio.wait(
                [asyncio.create_task(t) for t in tasks],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                idx, result, error = task.result()
                if error:
                    errors[idx] = error
                else:
                    results[idx] = result
        else:
            for coro_result in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(coro_result, Exception):
                    errors[-1] = str(coro_result)
                else:
                    idx, result, error = coro_result
                    results[idx] = result
                    if error:
                        errors[idx] = error
                        if self._stop_on_error:
                            break

        exchange.set_property("multicast_results", results)
        if errors:
            exchange.set_property("multicast_errors", errors)
