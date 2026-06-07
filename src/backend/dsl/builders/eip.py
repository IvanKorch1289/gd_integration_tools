"""EIP / streaming / transport / messaging миксин для RouteBuilder.

Группа: wire_tap / split / aggregate / recipient_list / load_balance /
claim_check_in / claim_check_out / normalize / resequence / multicast /
sort / on_completion / scatter_gather / dynamic_route / translate /
enrich / filter / transform; Express BotX (7 методов); Telegram Bot API
(7 методов); composed_message / multicast_routes / windowed_dedup /
windowed_collect; streaming окна (tumbling_window / sliding_window /
session_window / group_by_key); exactly_once / durable_fanout /
purge_channel / sample / reply_to / schema_validate / validate_schema;
cdc / sse_source / protocol / transport.

Stateless — см. контракт в ``base.py``.

Apache Camel EIP patterns reference: https://camel.apache.org/components/latest/eips/patterns.html
Apache Camel Routing Slip: https://camel.apache.org/components/latest/eips/routingSlip.html
Apache Camel Content-Based Router: https://camel.apache.org/components/latest/eips/contentBasedRouter.html
Apache Airflow Sensor: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.core.di.dependencies import get_watermark_store_optional
from src.backend.core.interfaces.watermark_store import WatermarkStore
from src.backend.dsl.adapters.types import ProtocolType, TransportConfig
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    AggregatorProcessor,
    BaseProcessor,
    CDCProcessor,
    ClaimCheckProcessor,
    DynamicRouterProcessor,
    FilterProcessor,
    LoadBalancerProcessor,
    NormalizerProcessor,
    ResequencerProcessor,
    ScatterGatherProcessor,
    SplitterProcessor,
    TransformProcessor,
)
from src.backend.dsl.engine.processors.streaming import (
    ChannelPurgerProcessor,
    DurableSubscriberProcessor,
    ExactlyOnceProcessor,
    GroupByKeyProcessor,
    ReplyToProcessor,
    SamplingProcessor,
    SchemaRegistryValidator,
    SessionWindowProcessor,
    SlidingWindowProcessor,
    TumblingWindowProcessor,
)

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class EIPMixin:
    """Поведенческий миксин EIP / streaming / transport для ``RouteBuilder``.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` /
    ``self._processors`` / ``self.route_id`` / ``self._protocol`` /
    ``self._transport_config`` через MRO; собственных полей не содержит.
    Контракт см. в ``base.py``.
    """

    __slots__ = ("_protocol", "_transport_config")

    # ── Core EIPs ──

    def transform(self, expression: str) -> RouteBuilder:
        """Трансформирует body через JMESPath-выражение."""
        return self._add(TransformProcessor(expression=expression))  # type: ignore[attr-defined]

    def filter(self, predicate: Callable[[Exchange[Any]], bool]) -> RouteBuilder:
        """Фильтрует Exchange — останавливает, если predicate=False."""
        return self._add(FilterProcessor(predicate=predicate))  # type: ignore[attr-defined]

    # ── CDC ──

    def cdc(
        self,
        profile: str,
        tables: list[str],
        target_action: str,
        *,
        strategy: str = "polling",
        interval: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        channel: str | None = None,
    ) -> RouteBuilder:
        """Change Data Capture — подписка на изменения в БД.

        strategy: polling (любая БД), listen_notify (PostgreSQL), logminer (Oracle).
        """
        return self._add(  # type: ignore[attr-defined]
            CDCProcessor(
                profile=profile,
                tables=tables,
                target_action=target_action,
                strategy=strategy,
                interval=interval,
                timestamp_column=timestamp_column,
                batch_size=batch_size,
                channel=channel,
            )
        )

    # ── Control routing / EIPs ──

    def translate(self, from_format: str, to_format: str) -> RouteBuilder:
        """DEPRECATED: используйте .convert(). translate() — alias для обратной совместимости."""
        return self.convert(from_format=from_format, to_format=to_format)  # type: ignore[attr-defined]

    def dynamic_route(
        self, route_expression: Callable[[Exchange[Any]], str]
    ) -> RouteBuilder:
        """Dynamic Router: runtime-вычисление route_id."""
        return self._add(DynamicRouterProcessor(route_expression=route_expression))  # type: ignore[attr-defined]

    def scatter_gather(
        self,
        route_ids: list[str],
        *,
        aggregation: str = "merge",
        timeout_seconds: float = 30.0,
    ) -> RouteBuilder:
        """Scatter-Gather: fan-out на N маршрутов + сборка результатов."""
        return self._add(  # type: ignore[attr-defined]
            ScatterGatherProcessor(
                route_ids=route_ids,
                aggregation=aggregation,
                timeout_seconds=timeout_seconds,
            )
        )

    def routing_slip(
        self,
        steps: Callable[[Exchange[Any]], Any] | list[str],
        *,
        header: str | None = None,
        strict: bool = True,
        max_steps: int = 50,
    ) -> RouteBuilder:
        """Routing Slip EIP: динамическая цепочка processors per-message.

        Apache Camel Routing Slip: https://camel.apache.org/components/latest/eips/routingSlip.html

        Каждое сообщение определяет свой ordered список steps, через которые
        message проходит последовательно. Отличие от Pipeline: steps
        определяются runtime'ом (per-message) — не статически.

        Args:
            steps: list имен processors ИЛИ callable, возвращающий list
                (для динамического выбора на основе exchange).
            header: имя header в exchange, который содержит list имен
                steps. Удобно когда список приходит извне.
            strict: если True (default) — отсутствующий step → KeyError.
                Если False — warning + skip.
            max_steps: защита от бесконечной цепочки (default 50).

        Пример::

            # Static steps
            .routing_slip(["audit", "transform", "send"])

            # Dynamic (per-message)
            .routing_slip(
                steps=lambda ex: ex.in_message.headers.get("flow"),
                strict=True,
            )

            # From header
            .routing_slip(steps=[], header="processing_pipeline")
        """
        from src.backend.dsl.engine.processors.eip.routing_slip import (
            ProcessorRegistry,
            RoutingSlipProcessor,
        )
        from src.backend.dsl.registry.processor import get_processor_registry

        # Resolve steps: list → constant, callable → wrap
        if isinstance(steps, list):
            _steps_list: list[str] = list(steps)  # capture by value

            def _const_resolver(e: Exchange[Any]) -> Any:
                return _steps_list  # type: ignore[misc]

            steps_resolver: Callable[[Exchange[Any]], Any] = _const_resolver
        else:
            steps_resolver = steps

        # If header specified, override resolver
        if header is not None:
            _h: str = header

            def _from_header(e: Exchange[Any]) -> Any:
                val = e.in_message.headers.get(_h)
                if val is None:
                    return []
                if isinstance(val, str):
                    return [s.strip() for s in val.split(",")]
                return list(val)

            steps_resolver = _from_header

        registry: ProcessorRegistry = get_processor_registry()

        return self._add(  # type: ignore[attr-defined]
            RoutingSlipProcessor(
                steps_resolver=steps_resolver,
                registry=registry,
                strict=strict,
                max_steps=max_steps,
            )
        )

    def from_interval(
        self,
        interval_s: float,
        *,
        start_immediately: bool = False,
        payload: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    ) -> RouteBuilder:
        """Camel-style ``from("timer:foo?period=...")`` — periodic trigger.

        Регистрирует IntervalTrigger в TriggerRegistry, который каждые
        ``interval_s`` секунд запускает route. При register() / startup
        приложения trigger.start() вызывается автоматически.

        Args:
            interval_s: interval в секундах.
            start_immediately: запустить сразу (default — после первого interval).
            payload: static dict или factory для payload (callable).
        """
        from src.backend.dsl.orchestration.triggers import (
            IntervalTrigger,
            get_trigger_registry,
        )

        # route_id: must be derived from builder. Use builder name or generated.
        # The actual binding happens at register time; here we just enqueue.
        trigger = IntervalTrigger(
            name=f"interval_{id(self)}",
            route_id=getattr(self, "_route_id", "_pending_"),
            interval_s=interval_s,
            start_immediately=start_immediately,
            payload=payload,
        )
        get_trigger_registry().register(trigger)
        return self  # type: ignore

    def from_webhook(self, path: str, *, method: str = "POST") -> RouteBuilder:
        """Camel-style ``from("http:host/path")`` — HTTP webhook trigger.

        Регистрирует FastAPI route на ``path``. При вызове (любой JSON body)
        → dsl_service.dispatch(route_id, body, headers).

        Args:
            path: URL path, e.g. ``"/webhooks/orders"``.
            method: HTTP method (default POST).
        """
        from src.backend.dsl.orchestration.triggers import (
            WebhookTrigger,
            get_trigger_registry,
        )

        trigger = WebhookTrigger(
            name=f"webhook_{path.replace('/', '_').strip('_') or 'root'}",
            route_id=getattr(self, "_route_id", "_pending_"),
            path=path,
            method=method,
        )
        get_trigger_registry().register(trigger)
        return self  # type: ignore

    def from_file(
        self,
        path: str,
        *,
        pattern: str | None = None,
        recursive: bool = False,
        poll_interval_s: float = 1.0,
    ) -> RouteBuilder:
        """Camel-style ``from("file:directory?pattern=*")`` — file sensor trigger.

        Apache Airflow FileSensor analogue. При появлении/изменении файла
        (matching pattern) → dsl_service.dispatch(route_id, {}, headers).

        Args:
            path: директория для watching.
            pattern: optional glob pattern (e.g., ``"*.csv"``).
            recursive: watch recursively (default False).
            poll_interval_s: debounce interval (default 1.0s).
        """
        from src.backend.core.orchestration.airflow_sensors import FileSensor
        from src.backend.core.orchestration.sensor import SensorTrigger
        from src.backend.dsl.orchestration.triggers import (
            FileSensorTaskWrapper as _FileSensorWrapper,
        )
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        sensor = FileSensor(
            path=path,
            pattern=pattern,
            recursive=recursive,
            poll_interval_s=poll_interval_s,
        )
        trigger_cfg = SensorTrigger(
            sensor_id=f"file_{path.replace('/', '_').strip('_')}",
            check=lambda d: asyncio.sleep(0, result=True),  # placeholder
            poll_interval_s=poll_interval_s,
        )

        async def _runner() -> None:
            from src.backend.dsl.service import get_dsl_service

            route_id = getattr(self, "_route_id", "_pending_")
            while True:
                matched = await sensor.watch(
                    trigger=trigger_cfg, input={}, namespace="default"
                )
                if matched:
                    await get_dsl_service().dispatch(
                        route_id=route_id,
                        body={},
                        headers={"x-sensor": "file", "x-sensor-path": path},
                    )
                await asyncio.sleep(poll_interval_s)

        task = asyncio.create_task(_runner(), name=f"sensor:file:{path}")
        get_trigger_registry().register(_FileSensorWrapper(task))  # type: ignore[arg-type]
        return self  # type: ignore

    def from_sql(
        self,
        dsn: str,
        query: str,
        *,
        predicate: str | None = None,
        poll_interval_s: float = 5.0,
    ) -> RouteBuilder:
        """Camel-style ``from("sql:...")`` — SQL sensor trigger.

        Apache Airflow SqlSensor analogue. Polls query до match (any row
        или JMESPath predicate). При match → dsl_service.dispatch.

        Args:
            dsn: PostgreSQL connection string (asyncpg DSN).
            query: SQL query.
            predicate: optional JMESPath (e.g., "length(@) > `0`").
            poll_interval_s: interval between polls (default 5.0s).
        """
        from src.backend.core.orchestration.airflow_sensors import SqlSensor
        from src.backend.core.orchestration.sensor import SensorTrigger
        from src.backend.dsl.orchestration.triggers import (
            FileSensorTaskWrapper as _FileSensorWrapper,
        )
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        sensor = SqlSensor(
            dsn=dsn, query=query, predicate=predicate, poll_interval_s=poll_interval_s
        )
        trigger_cfg = SensorTrigger(
            sensor_id=f"sql_{id(self)}",
            check=lambda d: asyncio.sleep(0, result=True),
            poll_interval_s=poll_interval_s,
        )

        async def _runner() -> None:
            from src.backend.dsl.service import get_dsl_service

            route_id = getattr(self, "_route_id", "_pending_")
            while True:
                matched = await sensor.watch(
                    trigger=trigger_cfg, input={}, namespace="default"
                )
                if matched:
                    await get_dsl_service().dispatch(
                        route_id=route_id,
                        body={},
                        headers={"x-sensor": "sql", "x-sensor-dsn": dsn.split("@")[-1]},
                    )
                await asyncio.sleep(poll_interval_s)

        task = asyncio.create_task(_runner(), name=f"sensor:sql:{id(self)}")
        get_trigger_registry().register(_FileSensorWrapper(task))  # type: ignore[arg-type]
        return self  # type: ignore

    def from_http(
        self,
        url: str,
        *,
        expected_status: int = 200,
        method: str = "GET",
        body_match: str | None = None,
        poll_interval_s: float = 10.0,
    ) -> RouteBuilder:
        """Camel-style ``from("http:url")`` — HTTP sensor trigger.

        Apache Airflow HttpSensor analogue. Polls endpoint до match.
        При match → dsl_service.dispatch.

        Args:
            url: HTTP endpoint.
            expected_status: status code для match (default 200).
            method: HTTP method.
            body_match: optional JMESPath для response body.
            poll_interval_s: interval between polls (default 10.0s).
        """
        from src.backend.core.orchestration.airflow_sensors import HttpSensor
        from src.backend.core.orchestration.sensor import SensorTrigger
        from src.backend.dsl.orchestration.triggers import (
            FileSensorTaskWrapper as _FileSensorWrapper,
        )
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        sensor = HttpSensor(
            url=url,
            expected_status=expected_status,
            method=method,
            body_match=body_match,
            poll_interval_s=poll_interval_s,
        )
        trigger_cfg = SensorTrigger(
            sensor_id=f"http_{id(self)}",
            check=lambda d: asyncio.sleep(0, result=True),
            poll_interval_s=poll_interval_s,
        )

        async def _runner() -> None:
            from src.backend.dsl.service import get_dsl_service

            route_id = getattr(self, "_route_id", "_pending_")
            while True:
                matched = await sensor.watch(
                    trigger=trigger_cfg, input={}, namespace="default"
                )
                if matched:
                    await get_dsl_service().dispatch(
                        route_id=route_id,
                        body={},
                        headers={"x-sensor": "http", "x-sensor-url": url},
                    )
                await asyncio.sleep(poll_interval_s)

        task = asyncio.create_task(_runner(), name=f"sensor:http:{id(self)}")
        get_trigger_registry().register(_FileSensorWrapper(task))  # type: ignore[arg-type]
        return self  # type: ignore

    def from_s3(
        self,
        bucket: str,
        key: str,
        *,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        poll_interval_s: float = 30.0,
    ) -> RouteBuilder:
        """Camel-style ``from("aws-s3:bucket/key")`` — S3 sensor trigger.

        Apache Airflow S3KeySensor analogue. Polls S3 head_object до match.
        При match → dsl_service.dispatch.

        Требует ``aioboto3`` (user-approved dep): ``uv pip install aioboto3``.
        Raises ImportError при construction если не установлен.

        Args:
            bucket: S3 bucket name.
            key: S3 object key.
            region: AWS region (default ``"us-east-1"``).
            endpoint_url: optional custom endpoint (MinIO, Ceph, Garage).
            poll_interval_s: interval between polls (default 30.0s).
        """
        from src.backend.core.orchestration.airflow_sensors import S3Sensor
        from src.backend.core.orchestration.sensor import SensorTrigger
        from src.backend.dsl.orchestration.triggers import (
            FileSensorTaskWrapper as _FileSensorWrapper,
        )
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        sensor = S3Sensor(
            bucket=bucket,
            key=key,
            region=region,
            endpoint_url=endpoint_url,
            poll_interval_s=poll_interval_s,
        )
        trigger_cfg = SensorTrigger(
            sensor_id=f"s3_{bucket}",
            check=lambda d: asyncio.sleep(0, result=True),
            poll_interval_s=poll_interval_s,
        )

        async def _runner() -> None:
            from src.backend.dsl.service import get_dsl_service

            route_id = getattr(self, "_route_id", "_pending_")
            while True:
                matched = await sensor.watch(
                    trigger=trigger_cfg, input={}, namespace="default"
                )
                if matched:
                    await get_dsl_service().dispatch(
                        route_id=route_id,
                        body={},
                        headers={
                            "x-sensor": "s3",
                            "x-sensor-bucket": bucket,
                            "x-sensor-key": key,
                        },
                    )
                await asyncio.sleep(poll_interval_s)

        task = asyncio.create_task(_runner(), name=f"sensor:s3:{bucket}")
        get_trigger_registry().register(_FileSensorWrapper(task))  # type: ignore[arg-type]
        return self  # type: ignore

    def content_based_router(
        self,
        routes: list[tuple[Callable[[Exchange[Any]], bool], str]],
        *,
        default_endpoint: str | None = None,
    ) -> RouteBuilder:
        """Content-Based Router EIP: route по predicate.

        Apache Camel: https://camel.apache.org/components/latest/eips/contentBasedRouter.html

        First matching predicate wins. Если ни один не match и default_endpoint
        задан → туда; иначе message dropped.

        Пример::

            .content_based_router([
                (lambda ex: ex.in_message.body.get("priority") == "high", "high_pri"),
                (lambda ex: ex.in_message.body.get("country") == "ru", "ru_route"),
            ], default_endpoint="default")
        """
        from src.backend.dsl.engine.processors.eip.filter_router_sampling import (
            ContentBasedRouter as _CBR,
        )

        return self._add(  # type: ignore[attr-defined]
            _CBR(routes=routes, default_endpoint=default_endpoint)
        )

    def sampling(
        self,
        *,
        rate: int | None = None,
        fraction: float | None = None,
        time_window_ms: int | None = None,
        max_in_window: int | None = None,
        seed: int | None = None,
    ) -> RouteBuilder:
        """Sampling EIP: probabilistic subset of messages.

        Apache Camel: https://camel.apache.org/components/latest/eips/sampling.html

        Пример::

            # 10% sampling
            .sampling(fraction=0.1)

            # Каждый 100-й
            .sampling(rate=100)

            # 5 per second
            .sampling(time_window_ms=1000, max_in_window=5)
        """
        from src.backend.dsl.engine.processors.eip.filter_router_sampling import (
            SamplingProcessor as _SP,
        )

        return self._add(  # type: ignore[attr-defined]
            _SP(
                rate=rate,
                fraction=fraction,
                time_window_ms=time_window_ms,
                max_in_window=max_in_window,
                seed=seed,
            )
        )

    def split(self, expression: str, processors: list[BaseProcessor]) -> RouteBuilder:
        """Splitter: разбиение массива на отдельные Exchange по JMESPath."""
        return self._add(  # type: ignore[attr-defined]
            SplitterProcessor(expression=expression, processors=processors)
        )

    def aggregate(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> RouteBuilder:
        """Aggregator: собирает N Exchange по correlation_key в batch."""
        return self._add(  # type: ignore[attr-defined]
            AggregatorProcessor(
                correlation_key=correlation_key,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
            )
        )

    def load_balance(
        self,
        targets: list[str],
        *,
        strategy: str = "round_robin",
        weights: list[float] | None = None,
        sticky_header: str | None = None,
    ) -> RouteBuilder:
        """Load Balancer: round_robin/random/weighted/sticky распределение."""
        return self._add(  # type: ignore[attr-defined]
            LoadBalancerProcessor(
                targets=targets,
                strategy=strategy,
                weights=weights,
                sticky_header=sticky_header,
            )
        )

    def claim_check_in(
        self,
        *,
        store: str = "redis",
        ttl_seconds: int = 3600,
        threshold_bytes: int = 256 * 1024,
    ) -> RouteBuilder:
        """Claim Check (store): сохраняет body в Redis/S3, body → {_claim_token: ...}.

        Args:
            store: "redis" | "s3" | "auto" (auto = S3 если payload >= threshold).
            ttl_seconds: Время жизни токена.
            threshold_bytes: Порог в байтах для переключения на S3 (по умолчанию 256 KB).
        """
        return self._add(  # type: ignore[attr-defined]
            ClaimCheckProcessor(
                mode="store",
                store=store,
                ttl_seconds=ttl_seconds,
                threshold_bytes=threshold_bytes,
            )
        )

    def claim_check_out(self) -> RouteBuilder:
        """Claim Check (retrieve): восстанавливает body по _claim_token."""
        return self._add(ClaimCheckProcessor(mode="retrieve"))  # type: ignore[attr-defined]

    def normalize(self, target_schema: type | None = None) -> RouteBuilder:
        """Normalizer: автоопределение формата (XML/CSV/YAML/JSON) → canonical dict."""
        return self._add(NormalizerProcessor(target_schema=target_schema))  # type: ignore[attr-defined]

    def resequence(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        sequence_field: str = "seq",
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> RouteBuilder:
        """Resequencer: восстановление порядка сообщений по sequence_field."""
        return self._add(  # type: ignore[attr-defined]
            ResequencerProcessor(
                correlation_key=correlation_key,
                sequence_field=sequence_field,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
            )
        )

    def on_completion(
        self,
        processors: list[BaseProcessor],
        *,
        on_success_only: bool = False,
        on_failure_only: bool = False,
    ) -> RouteBuilder:
        """OnCompletion — запуск callback после окончания pipeline (как finally)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip",
            "OnCompletionProcessor",
            processors=processors,
            on_success_only=on_success_only,
            on_failure_only=on_failure_only,
        )

    def sort(
        self,
        *,
        key_fn: Callable[[Any], Any] | None = None,
        key_field: str | None = None,
        reverse: bool = False,
    ) -> RouteBuilder:
        """Sort — сортировка list body по функции ключа или имени поля."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip",
            "SortProcessor",
            key_fn=key_fn,
            key_field=key_field,
            reverse=reverse,
        )

    # ── Transport config ──

    def protocol(self, proto: ProtocolType) -> RouteBuilder:
        """Привязывает маршрут к конкретному протоколу (REST/SOAP/gRPC/...)."""
        self._protocol = proto
        return self  # type: ignore[return-value]

    def transport(self, config: TransportConfig) -> RouteBuilder:
        """Настройки транспорта (endpoint, timeout, retry_count, options)."""
        self._transport_config = config
        return self  # type: ignore[return-value]

    # ── Windowed (EIP-extended) ──

    def windowed_dedup(
        self,
        key_from: str,
        *,
        key_prefix: str = "dedup",
        window_seconds: int = 60,
        mode: str = "first",
    ) -> RouteBuilder:
        """Дедупликация в скользящем окне с Redis-персистентностью.

        Args:
            key_from: Точечный путь к ключу (напр. ``body.entity_id``).
            key_prefix: Пространство имён Redis-ключей.
            window_seconds: Длительность окна в секундах.
            mode: Режим — ``first`` | ``last`` | ``unique``.
        """
        from src.backend.dsl.engine.processors.eip.windowed_dedup import (
            WindowedDedupProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            WindowedDedupProcessor(
                key_from=key_from,
                key_prefix=key_prefix,
                window_seconds=window_seconds,
                mode=mode,
            )
        )

    def batch(
        self, *, size: int = 100, timeout_ms: int = 500, group_by: str | None = None
    ) -> RouteBuilder:
        """Накопление сообщений в окно с flush по N ИЛИ по таймауту (S13 K3 W1).

        Args:
            size: Максимальный размер батча перед flush'ем.
            timeout_ms: Таймаут окна в миллисекундах.
            group_by: Опциональный путь группировки (``header.tenant_id`` |
                ``body.x`` | ``property.k``). Без значения — общий буфер.

        Usage::

            .batch(size=100, timeout_ms=500)
            .batch(size=50, timeout_ms=1000, group_by="header.tenant_id")
        """
        from src.backend.dsl.engine.processors.patterns import BatchWindowProcessor

        return self._add(  # type: ignore[attr-defined]
            BatchWindowProcessor(
                window_seconds=timeout_ms / 1000.0, max_size=size, group_by=group_by
            )
        )

    def windowed_collect(
        self,
        key_from: str,
        dedup_by: str,
        *,
        window_seconds: int = 60,
        dedup_mode: str = "last",
        inject_as: str = "collected_batch",
    ) -> RouteBuilder:
        """Накопление и батч-дедупликация сообщений в окне.

        Args:
            key_from: Путь к ключу группировки (напр. ``body.table_name``).
            dedup_by: Путь к полю дедупликации внутри батча.
            window_seconds: Длительность окна в секундах.
            dedup_mode: ``first`` | ``last`` — какое значение сохранять.
            inject_as: Имя exchange-свойства для инжекции батча.
        """
        from src.backend.dsl.engine.processors.eip.windowed_dedup import (
            WindowedCollectProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            WindowedCollectProcessor(
                key_from=key_from,
                window_seconds=window_seconds,
                dedup_by=dedup_by,
                dedup_mode=dedup_mode,
                inject_as=inject_as,
            )
        )

    def multicast_routes(
        self,
        route_ids: list[str],
        *,
        strategy: str = "all",
        on_error: str = "continue",
        timeout: float = 30.0,
    ) -> RouteBuilder:
        """Fan-out на зарегистрированные DSL-маршруты по route_id.

        Args:
            route_ids: Список route_id из RouteRegistry.
            strategy: ``all`` — выполнить все; ``first_success`` — остановить после первого.
            on_error: ``fail`` | ``continue`` — поведение при ошибке.
            timeout: Таймаут каждого маршрута в секундах.
        """
        from src.backend.dsl.engine.processors.eip.routing import (
            MulticastRoutesProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            MulticastRoutesProcessor(
                route_ids=route_ids,
                strategy=strategy,
                on_error=on_error,
                timeout=timeout,
            )
        )

    # ── Express BotX (Wave 4.2) ──

    def express_send(
        self,
        body: str | None = None,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        body_from: str | None = None,
        bubble: list[list[dict[str, Any]]] | None = None,
        keyboard: list[list[dict[str, Any]]] | None = None,
        status: str = "ok",
        silent_response: bool = False,
        sync: bool = False,
        result_property: str = "express_sync_id",
    ) -> RouteBuilder:
        """Отправить сообщение в Express чат через BotX API."""
        from src.backend.dsl.engine.processors.express import ExpressSendProcessor

        return self._add(  # type: ignore[attr-defined]
            ExpressSendProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                body=body,
                body_from=body_from,
                bubble=bubble,
                keyboard=keyboard,
                status=status,
                silent_response=silent_response,
                sync=sync,
                result_property=result_property,
            )
        )

    def express_reply(
        self,
        body_from: str | None = None,
        *,
        bot: str = "main_bot",
        source_sync_id_from: str = "header.X-Express-Sync-Id",
        chat_id_from: str = "body.group_chat_id",
        body: str | None = None,
        result_property: str = "express_reply_sync_id",
    ) -> RouteBuilder:
        """Ответить на исходное сообщение Express (reply-thread)."""
        from src.backend.dsl.engine.processors.express import ExpressReplyProcessor

        return self._add(  # type: ignore[attr-defined]
            ExpressReplyProcessor(
                bot=bot,
                source_sync_id_from=source_sync_id_from,
                chat_id_from=chat_id_from,
                body=body,
                body_from=body_from,
                result_property=result_property,
            )
        )

    def express_edit(
        self,
        sync_id_from: str = "properties.express_sync_id",
        *,
        bot: str = "main_bot",
        body: str | None = None,
        body_from: str | None = None,
        bubble: list[list[dict[str, Any]]] | None = None,
        keyboard: list[list[dict[str, Any]]] | None = None,
        status: str | None = None,
    ) -> RouteBuilder:
        """Редактировать ранее отправленное Express сообщение."""
        from src.backend.dsl.engine.processors.express import ExpressEditProcessor

        return self._add(  # type: ignore[attr-defined]
            ExpressEditProcessor(
                bot=bot,
                sync_id_from=sync_id_from,
                body=body,
                body_from=body_from,
                bubble=bubble,
                keyboard=keyboard,
                status=status,
            )
        )

    def express_typing(
        self,
        action: str = "start",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
    ) -> RouteBuilder:
        """Отправить/остановить индикатор набора в Express чате."""
        from src.backend.dsl.engine.processors.express import ExpressTypingProcessor

        return self._add(  # type: ignore[attr-defined]
            ExpressTypingProcessor(bot=bot, chat_id_from=chat_id_from, action=action)
        )

    def express_send_file(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        s3_key_from: str | None = None,
        file_data_property: str | None = None,
        file_name: str | None = None,
        file_name_from: str | None = None,
        body: str | None = None,
        body_from: str | None = None,
        result_property: str = "express_file_sync_id",
    ) -> RouteBuilder:
        """Отправить файл (S3/LocalFS или exchange-property) в Express чат."""
        from src.backend.dsl.engine.processors.express import ExpressSendFileProcessor

        return self._add(  # type: ignore[attr-defined]
            ExpressSendFileProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                s3_key_from=s3_key_from,
                file_data_property=file_data_property,
                file_name=file_name,
                file_name_from=file_name_from,
                body=body,
                body_from=body_from,
                result_property=result_property,
            )
        )

    def express_mention(
        self,
        *,
        mention_type: str = "user",
        target_from: str | None = None,
        mention_id: str | None = None,
        name_from: str | None = None,
        property_name: str = "express_mentions",
    ) -> RouteBuilder:
        """Добавить упоминание (user/chat/channel/contact/all) в exchange-property."""
        from src.backend.dsl.engine.processors.express import ExpressMentionProcessor

        return self._add(  # type: ignore[attr-defined]
            ExpressMentionProcessor(
                mention_type=mention_type,
                target_from=target_from,
                mention_id=mention_id,
                name_from=name_from,
                property_name=property_name,
            )
        )

    def express_status(
        self,
        *,
        bot: str = "main_bot",
        sync_id_from: str = "properties.express_sync_id",
        result_property: str = "express_event_status",
    ) -> RouteBuilder:
        """Запросить статус доставки сообщения по sync_id."""
        from src.backend.dsl.engine.processors.express import ExpressStatusProcessor

        return self._add(  # type: ignore[attr-defined]
            ExpressStatusProcessor(
                bot=bot, sync_id_from=sync_id_from, result_property=result_property
            )
        )

    # ── Telegram Bot API (W15.3) ──

    def telegram_send(
        self,
        body: str | None = None,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        body_from: str | None = None,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
        reply_keyboard: list[list[str]] | None = None,
        disable_notification: bool = False,
        disable_web_page_preview: bool = False,
        result_property: str = "telegram_message_id",
    ) -> RouteBuilder:
        """Отправить сообщение в Telegram чат через Bot API."""
        from src.backend.dsl.engine.processors.telegram import TelegramSendProcessor

        return self._add(  # type: ignore[attr-defined]
            TelegramSendProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                body=body,
                body_from=body_from,
                parse_mode=parse_mode,
                inline_keyboard=inline_keyboard,
                reply_keyboard=reply_keyboard,
                disable_notification=disable_notification,
                disable_web_page_preview=disable_web_page_preview,
                result_property=result_property,
            )
        )

    def telegram_reply(
        self,
        body_from: str | None = None,
        *,
        bot: str = "main_bot",
        source_message_id_from: str = "body.message.message_id",
        chat_id_from: str = "body.chat_id",
        body: str | None = None,
        parse_mode: str = "HTML",
        result_property: str = "telegram_reply_message_id",
    ) -> RouteBuilder:
        """Ответить на сообщение Telegram (reply_to_message_id)."""
        from src.backend.dsl.engine.processors.telegram import TelegramReplyProcessor

        return self._add(  # type: ignore[attr-defined]
            TelegramReplyProcessor(
                bot=bot,
                source_message_id_from=source_message_id_from,
                chat_id_from=chat_id_from,
                body=body,
                body_from=body_from,
                parse_mode=parse_mode,
                result_property=result_property,
            )
        )

    def telegram_edit(
        self,
        message_id_from: str = "properties.telegram_message_id",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
    ) -> RouteBuilder:
        """Редактировать ранее отправленное Telegram-сообщение."""
        from src.backend.dsl.engine.processors.telegram import TelegramEditProcessor

        return self._add(  # type: ignore[attr-defined]
            TelegramEditProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                message_id_from=message_id_from,
                body=body,
                body_from=body_from,
                parse_mode=parse_mode,
                inline_keyboard=inline_keyboard,
            )
        )

    def telegram_typing(
        self,
        action: str = "typing",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
    ) -> RouteBuilder:
        """Отправить chat-action (typing / upload_photo / …) в Telegram."""
        from src.backend.dsl.engine.processors.telegram import TelegramTypingProcessor

        return self._add(  # type: ignore[attr-defined]
            TelegramTypingProcessor(bot=bot, chat_id_from=chat_id_from, action=action)
        )

    def telegram_send_file(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        s3_key_from: str | None = None,
        file_data_property: str | None = None,
        file_name: str | None = None,
        file_name_from: str | None = None,
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
        result_property: str = "telegram_file_message_id",
    ) -> RouteBuilder:
        """Отправить файл (документ) в Telegram чат."""
        from src.backend.dsl.engine.processors.telegram import TelegramSendFileProcessor

        return self._add(  # type: ignore[attr-defined]
            TelegramSendFileProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                s3_key_from=s3_key_from,
                file_data_property=file_data_property,
                file_name=file_name,
                file_name_from=file_name_from,
                body=body,
                body_from=body_from,
                parse_mode=parse_mode,
                disable_notification=disable_notification,
                result_property=result_property,
            )
        )

    def telegram_mention(
        self,
        *,
        user_id_from: str,
        display_name_from: str | None = None,
        parse_mode: str = "MarkdownV2",
        property_name: str = "telegram_mention",
        append: bool = False,
    ) -> RouteBuilder:
        """Создать фрагмент-упоминание пользователя для вставки в текст."""
        from src.backend.dsl.engine.processors.telegram import TelegramMentionProcessor

        return self._add(  # type: ignore[attr-defined]
            TelegramMentionProcessor(
                user_id_from=user_id_from,
                display_name_from=display_name_from,
                parse_mode=parse_mode,
                property_name=property_name,
                append=append,
            )
        )

    def telegram_status(
        self, *, bot: str = "main_bot", result_property: str = "telegram_bot_profile"
    ) -> RouteBuilder:
        """Запросить профиль бота (getMe) — health-check Telegram."""
        from src.backend.dsl.engine.processors.telegram import TelegramStatusProcessor

        return self._add(  # type: ignore[attr-defined]
            TelegramStatusProcessor(bot=bot, result_property=result_property)
        )

    # ── Composed Message Processor ──

    def composed_message(
        self,
        splitter: Callable[[Exchange[Any]], Any],
        processors: list[BaseProcessor],
        aggregator: Callable[[list[Exchange[Any]]], Any],
    ) -> RouteBuilder:
        """Composed Message Processor: split → per-part → aggregate."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.composed_message",
            "ComposedMessageProcessor",
            splitter=splitter,
            processors=processors,
            aggregator=aggregator,
        )

    # ── Streaming windows ──

    def tumbling_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        size: int = 100,
        interval_seconds: float = 10.0,
        watermark_store: WatermarkStore | None = None,
    ) -> RouteBuilder:
        """Streaming tumbling-окно фиксированного размера.

        Если ``watermark_store`` не задан и в ``app.state`` уже
        зарегистрирован durable store (W14.5), он подхватывается
        автоматически вместе с ``route_id`` маршрута. В тестах без
        composition root окно ведёт себя как in-memory.
        """
        store = watermark_store or get_watermark_store_optional()
        return self._add(  # type: ignore[attr-defined]
            TumblingWindowProcessor(
                sink=sink,
                size=size,
                interval_seconds=interval_seconds,
                watermark_store=store,
                route_id=self.route_id if store is not None else None,  # type: ignore[attr-defined]
            )
        )

    def sliding_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        window_seconds: float = 10.0,
        step_seconds: float = 2.0,
        watermark_store: WatermarkStore | None = None,
    ) -> RouteBuilder:
        """Streaming sliding-окно с перекрытием.

        ``watermark_store`` подхватывается из ``app.state`` (W14.5),
        если не передан явно. См. :meth:`tumbling_window`.
        """
        store = watermark_store or get_watermark_store_optional()
        return self._add(  # type: ignore[attr-defined]
            SlidingWindowProcessor(
                sink=sink,
                window_seconds=window_seconds,
                step_seconds=step_seconds,
                watermark_store=store,
                route_id=self.route_id if store is not None else None,  # type: ignore[attr-defined]
            )
        )

    def session_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        gap_seconds: float = 30.0,
        watermark_store: WatermarkStore | None = None,
    ) -> RouteBuilder:
        """Streaming session-окно (закрывается по паузе).

        ``watermark_store`` подхватывается из ``app.state`` (W14.5),
        если не передан явно. См. :meth:`tumbling_window`.
        """
        store = watermark_store or get_watermark_store_optional()
        return self._add(  # type: ignore[attr-defined]
            SessionWindowProcessor(
                sink=sink,
                gap_seconds=gap_seconds,
                watermark_store=store,
                route_id=self.route_id if store is not None else None,  # type: ignore[attr-defined]
            )
        )

    def group_by_key(
        self,
        key_path: str,
        sink: Callable[[dict[Any, list[Any]]], Any],
        *,
        window_seconds: float = 60.0,
    ) -> RouteBuilder:
        """Группировка по ключу (jmespath) в пределах окна."""
        return self._add(  # type: ignore[attr-defined]
            GroupByKeyProcessor(
                sink=sink, key_path=key_path, window_seconds=window_seconds
            )
        )

    # ── Schema-registry / streaming messaging EIPs ──

    def validate_schema(
        self, subject: str, *, schema_loader: Any = None
    ) -> RouteBuilder:
        """Валидация по схеме из реестра (JSON Schema / Avro / Protobuf)."""
        return self._add(  # type: ignore[attr-defined]
            SchemaRegistryValidator(subject=subject, schema_loader=schema_loader)
        )

    def reply_to(
        self,
        broker: Any,
        *,
        reply_to_header: str = "reply-to",
        correlation_header: str = "x-correlation-id",
    ) -> RouteBuilder:
        """Return Address: публикует ответ в очередь из reply-to заголовка."""
        return self._add(  # type: ignore[attr-defined]
            ReplyToProcessor(
                broker=broker,
                reply_to_header=reply_to_header,
                correlation_header=correlation_header,
            )
        )

    def exactly_once(
        self,
        storage: Any,
        *,
        id_header: str = "x-message-id",
        ttl_seconds: int = 86_400,
        namespace: str = "exactly-once",
    ) -> RouteBuilder:
        """Exactly-once: dedup через storage по message-id."""
        return self._add(  # type: ignore[attr-defined]
            ExactlyOnceProcessor(
                storage=storage,
                id_header=id_header,
                ttl_seconds=ttl_seconds,
                namespace=namespace,
            )
        )

    def durable_fanout(self, broker: Any, subscribers: list[str]) -> RouteBuilder:
        """Durable Subscriber: fan-out к persistent-подписчикам."""
        return self._add(  # type: ignore[attr-defined]
            DurableSubscriberProcessor(broker=broker, subscribers=subscribers)
        )

    def purge_channel(
        self, broker: Any, channel: str, *, dry_run: bool = True
    ) -> RouteBuilder:
        """Очистка очереди/стрима (admin-операция)."""
        return self._add(  # type: ignore[attr-defined]
            ChannelPurgerProcessor(broker=broker, channel=channel, dry_run=dry_run)
        )

    def sample(self, probability: float = 0.1) -> RouteBuilder:
        """Вероятностный сэмплинг (A/B, canary, debug-sampling)."""
        return self._add(SamplingProcessor(probability=probability))  # type: ignore[attr-defined]

    # ── SSE source + JSON-Schema validation (generic) ──

    def sse_source(
        self, url: str, event_types: list[str] | None = None
    ) -> RouteBuilder:
        """Source-процессор для Server-Sent Events."""
        from src.backend.dsl.engine.processors.generic import SseSourceProcessor

        return self._add(  # type: ignore[attr-defined]
            SseSourceProcessor(url=url, event_types=event_types)
        )

    def schema_validate(self, schema: dict[str, Any]) -> RouteBuilder:
        """Валидация body по JSON Schema (Draft 2020-12)."""
        from src.backend.dsl.engine.processors.generic import SchemaValidateProcessor

        return self._add(SchemaValidateProcessor(schema=schema))  # type: ignore[attr-defined]
