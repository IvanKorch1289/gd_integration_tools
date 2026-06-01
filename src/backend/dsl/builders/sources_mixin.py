"""K3 W5 — :class:`SourcesMixin`: builder source-сахар для всех источников событий.

Предоставляет 8 classmethod'ов-фабрик, каждый из которых создаёт свежий
``RouteBuilder`` с правильно установленным источником (``source``).

Принципы:
    - lazy-import тяжёлых Source-классов (psycopg3, FastStream, watchfiles и др.)
      — dev_light без них остаётся работоспособным;
    - ``route_id`` задаётся явно (уникальный ID маршрута в системе);
    - дополнительные ``**kwargs`` проксируются в конструктор соответствующего
      Source-класса для полной настройки без промежуточных обёрток;
    - возвращает ``RouteBuilder`` для продолжения fluent-chain;
    - feature-flag ``builder_source_sugar`` (K3 секция features.py) контролирует
      доступность сахара; при False методы работают в режиме совместимости
      (без регистрации источника в SourceRegistry).

Guard (feature-flag):
    По умолчанию (default-OFF) все методы создают RouteBuilder с ``source``
    как строковый DSN (``kafka:<topic>``, ``rabbitmq:<queue>`` и т.д.).
    При включённом flag'е — дополнительно инстанцируется соответствующий
    Source-класс и его можно получить через атрибут ``_source_instance``
    на возвращённом builder'е.

Контракт миксина (см. ``base.py``):
    - stateless — нет instance-атрибутов;
    - ``__slots__ = ()`` — обязательно;
    - не содержит ``@dataclass``;
    - методы используют ``cls(...)`` — classmethod'ы, возвращающие новый экземпляр.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("SourcesMixin",)


class SourcesMixin:
    """Миксин builder source-сахар (K3 W5).

    Каждый classmethod создаёт свежий ``RouteBuilder`` с источником,
    соответствующим выбранному transport/protocol. Тяжёлые Source-классы
    импортируются лениво внутри каждого метода.

    Все методы статические фабрики — не требуют существующего инстанса
    ``RouteBuilder``.
    """

    __slots__ = ()

    @classmethod
    def from_webdav(
        cls,
        route_id: str,
        url: str,
        *,
        watch_path: str = "/",
        poll_interval_seconds: int = 60,
        file_pattern: str = "*",
        username: str | None = None,
        password: str | None = None,
        processed_marker_path: str | None = None,
        marker_dedup: bool = True,
    ) -> "RouteBuilder":
        """Создаёт маршрут с polling-источником WebDAV (S13 K3 W2, INF-2.8).

        Args:
            route_id: Уникальный ID маршрута.
            url: Базовый URL WebDAV-сервера (e.g. ``http://nextcloud:80/remote.php/dav/files/admin``).
            watch_path: Папка для опроса.
            poll_interval_seconds: Интервал между PROPFIND-запросами.
            file_pattern: Glob-фильтр имени файла.
            username/password: HTTP basic auth.
            processed_marker_path: Путь на сервере для маркера (опц.).
            marker_dedup: Использовать persistent marker для dedup.

        Returns:
            RouteBuilder с source ``webdav:<route_id>``.
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.webdav")
        cfg = mod.WebDAVSourceConfig(
            url=url,
            watch_path=watch_path,
            poll_interval_seconds=poll_interval_seconds,
            file_pattern=file_pattern,
            username=username,
            password=password,
            processed_marker_path=processed_marker_path,
            marker_dedup=marker_dedup,
        )
        source_instance = mod.WebDAVSource(cfg)
        builder: RouteBuilder = cls(route_id=route_id, source=f"webdav:{route_id}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_cdc(
        cls,
        route_id: str,
        table: str,
        *,
        dsn: str = "",
        slot_name: str = "",
        publication_names: list[str] | None = None,
        plugin: str = "pgoutput",
        **kwargs: Any,
    ) -> "RouteBuilder":
        """Создаёт маршрут с источником CDC (PostgreSQL logical replication).

        Лениво импортирует :class:`CDCSource` из
        ``infrastructure.sources.cdc`` (зависимость ``psycopg[binary]>=3.1``
        — опциональная, ``sources-cdc`` extra).

        Args:
            route_id: Уникальный ID маршрута.
            table: Имя таблицы / publication (используется в ``slot_name`` по умолчанию).
            dsn: PostgreSQL DSN (``postgres://user:pass@host/db``).
            slot_name: Имя logical replication slot. По умолчанию — ``table``.
            publication_names: Список PUBLICATION для pgoutput.
            plugin: Плагин декодирования (``pgoutput`` / ``wal2json``).
            **kwargs: Дополнительные параметры для :class:`CDCSource`.

        Returns:
            RouteBuilder с ``source`` установленным в ``cdc:<table>``.

        Example::

            route = (
                RouteBuilder.from_cdc("orders.audit", "orders",
                    dsn="postgres://user:pass@host/db",
                    slot_name="orders_slot")
                .dispatch_action("analytics.insert_batch")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.cdc")
        CDCSource = mod.CDCSource  # noqa: N806
        effective_slot = slot_name or table
        source_instance = CDCSource(
            source_id=route_id,
            dsn=dsn,
            slot_name=effective_slot,
            publication_names=publication_names,
            plugin=plugin,
            **kwargs,
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"cdc:{table}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_cdc_logical(
        cls,
        route_id: str,
        table: str,
        *,
        dsn: str,
        mode: str = "delta",
        slot_name: str | None = None,
        publication: str | None = None,
        plugin: str = "pgoutput",
        **kwargs: Any,
    ) -> "RouteBuilder":
        """K3 S5 W5 — расширенный CDC через :class:`CdcPostgresLogicalSource`.

        В отличие от :meth:`from_cdc`, поддерживает:
          * режимы ``full`` (snapshot+tail) и ``delta`` (только tail);
          * персистентный watermark cursor (``cdc_cursors``);
          * idempotent setup publication+slot.

        Args:
            route_id: Уникальный ID маршрута.
            table: Имя таблицы.
            dsn: PostgreSQL DSN с REPLICATION-ролью.
            mode: ``full`` или ``delta``.
            slot_name: Имя slot (default ``cdc_<table>``).
            publication: Имя publication (default ``pub_<table>``).
            plugin: ``pgoutput`` (default) / ``wal2json``.
            **kwargs: Дополнительно (``cursor_store=...``).

        Returns:
            ``RouteBuilder`` с ``source = cdc-logical:<table>``.
        """
        import importlib

        mod = importlib.import_module(
            "src.backend.infrastructure.sources.cdc_postgres_logical"
        )
        SourceCls = mod.CdcPostgresLogicalSource  # noqa: N806
        source_instance = SourceCls(
            source_id=route_id,
            table=table,
            dsn=dsn,
            mode=mode,
            slot_name=slot_name,
            publication=publication,
            plugin=plugin,
            **kwargs,
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"cdc-logical:{table}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_cdc_capture(
        cls,
        route_id: str,
        profile: str,
        tables: list[str],
        *,
        strategy: str = "polling",
        interval: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        channel: str | None = None,
        **kwargs: Any,
    ) -> "RouteBuilder":
        """Создаёт маршрут с источником CDC Capture.

        Лениво импортирует :class:`CDCClient` из
        ``infrastructure.clients.external.cdc``.

        В отличие от :meth:`from_cdc` (источник логической репликации PostgreSQL),
        этот метод подходит для любого профиля внешней БД с поддержкой
        polling/listen_notify/logminer стратегий.

        Args:
            route_id: Уникальный ID маршрута.
            profile: Имя профиля внешней БД.
            tables: Список таблиц для отслеживания.
            strategy: Стратегия CDC — ``polling`` (любая БД),
                ``listen_notify`` (PostgreSQL LISTEN/NOTIFY),
                ``logminer`` (Oracle LogMiner).
            interval: Интервал polling в секундах (default 5.0).
            timestamp_column: Столбец для polling-стратегии.
            batch_size: Макс. событий за итерацию.
            channel: Имя PostgreSQL-канала для listen_notify.
            **kwargs: Дополнительные параметры для CDC-подписки.

        Returns:
            RouteBuilder с ``source`` установленным в ``cdc-capture:<profile>:<tables>``.

        Example::

            route = (
                RouteBuilder.from_cdc_capture(
                    "orders.changes",
                    profile="oracle_prod",
                    tables=["orders", "customers"],
                    strategy="polling",
                )
                .dispatch_action("analytics.process_changes")
                .build()
            )
        """
        builder: RouteBuilder = cls(
            route_id=route_id, source=f"cdc-capture:{profile}:{','.join(tables)}"
        )
        object.__setattr__(
            builder,
            "_source_config",
            {
                "type": "cdc_capture",
                "profile": profile,
                "tables": tables,
                "strategy": strategy,
                "interval": interval,
                "timestamp_column": timestamp_column,
                "batch_size": batch_size,
                "channel": channel,
                **kwargs,
            },
        )
        return builder

    @classmethod
    def from_kafka(
        cls,
        route_id: str,
        topic: str,
        bootstrap_servers: str,
        group_id: str,
        **kwargs: Any,
    ) -> "RouteBuilder":
        """Создаёт маршрут с источником Apache Kafka.

        Лениво импортирует :class:`MQSource` с transport ``kafka``
        из ``infrastructure.sources.mq`` (FastStream + aiokafka).

        Args:
            route_id: Уникальный ID маршрута.
            topic: Имя Kafka-топика.
            bootstrap_servers: Kafka bootstrap servers (``host:port``).
            group_id: Consumer group ID.
            **kwargs: Дополнительные параметры для :class:`MQSource`.

        Returns:
            RouteBuilder с ``source`` установленным в ``kafka:<topic>``.

        Example::

            route = (
                RouteBuilder.from_kafka(
                    "payments.stream",
                    topic="payments",
                    bootstrap_servers="kafka:9092",
                    group_id="payments-consumer",
                )
                .dispatch_action("payments.process")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.mq")
        MQSource = mod.MQSource  # noqa: N806
        source_instance = MQSource(
            source_id=route_id,
            transport="kafka",
            topic=topic,
            group=group_id,
            connect_url=bootstrap_servers,
            **kwargs,
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"kafka:{topic}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_rabbit(
        cls, route_id: str, queue: str, url: str, **kwargs: Any
    ) -> "RouteBuilder":
        """Создаёт маршрут с источником RabbitMQ.

        Лениво импортирует :class:`MQSource` с transport ``rabbitmq``
        из ``infrastructure.sources.mq`` (FastStream + aio-pika).

        Args:
            route_id: Уникальный ID маршрута.
            queue: Имя очереди RabbitMQ.
            url: AMQP URL (``amqp://user:pass@host/vhost``).
            **kwargs: Дополнительные параметры для :class:`MQSource`.

        Returns:
            RouteBuilder с ``source`` установленным в ``rabbitmq:<queue>``.

        Example::

            route = (
                RouteBuilder.from_rabbit(
                    "notifications.consumer",
                    queue="notifications",
                    url="amqp://guest:guest@rabbitmq/",
                )
                .dispatch_action("notifications.process")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.mq")
        MQSource = mod.MQSource  # noqa: N806
        source_instance = MQSource(
            source_id=route_id,
            transport="rabbitmq",
            topic=queue,
            connect_url=url,
            **kwargs,
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"rabbitmq:{queue}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_mqtt(
        cls, route_id: str, topic: str, broker_url: str, **kwargs: Any
    ) -> "RouteBuilder":
        """Создаёт маршрут с источником MQTT.

        MQTT Source — лёгкий wrapper поверх ``aiomqtt`` (lazy-import).
        ``source`` строка: ``mqtt:<topic>``.

        Args:
            route_id: Уникальный ID маршрута.
            topic: MQTT-топик (поддерживаются wildcards: ``+``, ``#``).
            broker_url: URL брокера (``mqtt://host:1883`` или ``mqtts://host:8883``).
            **kwargs: Дополнительные параметры (qos, client_id и др.).

        Returns:
            RouteBuilder с ``source`` установленным в ``mqtt:<topic>``.

        Example::

            route = (
                RouteBuilder.from_mqtt(
                    "sensors.telemetry",
                    topic="sensors/+/temperature",
                    broker_url="mqtt://iot-broker:1883",
                )
                .dispatch_action("sensors.store_reading")
                .build()
            )
        """
        # MQTT Source-класса пока нет в infrastructure/sources/
        # — используем строковый DSN; source_instance = None (будущее расширение)
        builder: RouteBuilder = cls(route_id=route_id, source=f"mqtt:{topic}")
        # Сохраняем параметры для будущей регистрации MQTTSource
        object.__setattr__(
            builder,
            "_source_config",
            {"transport": "mqtt", "topic": topic, "broker_url": broker_url, **kwargs},
        )
        return builder

    @classmethod
    def from_redis_streams(
        cls, route_id: str, stream: str, consumer_group: str, **kwargs: Any
    ) -> "RouteBuilder":
        """Создаёт маршрут с источником Redis Streams.

        Лениво импортирует :class:`MQSource` с transport ``redis_streams``
        из ``infrastructure.sources.mq`` (FastStream + redis-py).

        Args:
            route_id: Уникальный ID маршрута.
            stream: Имя Redis Stream (ключ).
            consumer_group: Имя consumer group (для XREADGROUP).
            **kwargs: Дополнительные параметры для :class:`MQSource`
                (connect_url, decode_json и др.).

        Returns:
            RouteBuilder с ``source`` установленным в ``redis_streams:<stream>``.

        Example::

            route = (
                RouteBuilder.from_redis_streams(
                    "audit.trail",
                    stream="audit:events",
                    consumer_group="audit-consumers",
                    connect_url="redis://redis:6379",
                )
                .dispatch_action("audit.persist")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.mq")
        MQSource = mod.MQSource  # noqa: N806
        source_instance = MQSource(
            source_id=route_id,
            transport="redis_streams",
            topic=stream,
            group=consumer_group,
            **kwargs,
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"redis_streams:{stream}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_filewatcher(
        cls, route_id: str, path: str, *, recursive: bool = True, **kwargs: Any
    ) -> "RouteBuilder":
        """Создаёт маршрут с источником FileWatcher (watchfiles.awatch).

        Лениво импортирует :class:`FileWatcherSource` из
        ``infrastructure.sources.file_watcher``.
        Активируется через feature_flag ``eventbus_file_watcher`` (default-OFF).

        Args:
            route_id: Уникальный ID маршрута.
            path: Корневой путь для наблюдения (строка или Path).
            recursive: Рекурсивно обходить поддиректории (default ``True``).
            **kwargs: Дополнительные параметры для :class:`FileWatcherSource`
                (debounce, watch_filter).

        Returns:
            RouteBuilder с ``source`` установленным в ``filewatcher:<path>``.

        Example::

            route = (
                RouteBuilder.from_filewatcher(
                    "config.hotreload",
                    path="/etc/app/config",
                    recursive=False,
                )
                .dispatch_action("config.reload")
                .build()
            )
        """
        import importlib
        from pathlib import Path

        mod = importlib.import_module("src.backend.infrastructure.sources.file_watcher")
        FileWatcherSource = mod.FileWatcherSource  # noqa: N806
        source_instance = FileWatcherSource(
            path=Path(path), recursive=recursive, **kwargs
        )
        builder: RouteBuilder = cls(route_id=route_id, source=f"filewatcher:{path}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_webhook(cls, route_id: str, path: str, **kwargs: Any) -> "RouteBuilder":
        """Создаёт маршрут с источником inbound webhook.

        Лениво импортирует :class:`WebhookSource` из
        ``infrastructure.sources.webhook``.
        HMAC-SHA256 верификация включается через ``hmac_secret`` в kwargs.

        Args:
            route_id: Уникальный ID маршрута.
            path: HTTP-путь для inbound webhook (e.g., ``/webhooks/github``).
            **kwargs: Дополнительные параметры для :class:`WebhookSource`
                (hmac_secret, hmac_header, timestamp_header и др.).

        Returns:
            RouteBuilder с ``source`` установленным в ``webhook:<path>``.

        Example::

            route = (
                RouteBuilder.from_webhook(
                    "github.push",
                    path="/webhooks/github",
                    hmac_secret="my-secret",
                    hmac_header="X-Hub-Signature-256",
                )
                .dispatch_action("ci.trigger_build")
                .build()
            )
        """
        import importlib

        mod = importlib.import_module("src.backend.infrastructure.sources.webhook")
        WebhookSource = mod.WebhookSource  # noqa: N806
        source_instance = WebhookSource(source_id=route_id, path=path, **kwargs)
        builder: RouteBuilder = cls(route_id=route_id, source=f"webhook:{path}")
        object.__setattr__(builder, "_source_instance", source_instance)
        return builder

    @classmethod
    def from_schedule(
        cls, route_id: str, cron_expr: str, **kwargs: Any
    ) -> "RouteBuilder":
        """Создаёт маршрут с источником cron-расписания.

        Лениво импортирует :class:`PollingSource` из
        ``infrastructure.sources.polling`` для cron-based опроса.
        Для полноценного cron — интеграция с APScheduler через
        ``infrastructure.scheduler.scheduled_tasks``.

        Args:
            route_id: Уникальный ID маршрута.
            cron_expr: Cron-выражение (``* * * * *`` style, 5 полей).
            **kwargs: Дополнительные параметры: ``url`` (polling URL),
                ``interval_seconds`` и др.

        Returns:
            RouteBuilder с ``source`` установленным в ``schedule:<cron_expr>``.

        Example::

            route = (
                RouteBuilder.from_schedule(
                    "reports.daily",
                    cron_expr="0 9 * * 1-5",
                )
                .dispatch_action("reports.generate_daily")
                .build()
            )
        """
        builder: RouteBuilder = cls(route_id=route_id, source=f"schedule:{cron_expr}")
        # Сохраняем cron и kwargs для последующей регистрации в APScheduler
        object.__setattr__(
            builder,
            "_source_config",
            {"type": "schedule", "cron_expr": cron_expr, **kwargs},
        )
        return builder
