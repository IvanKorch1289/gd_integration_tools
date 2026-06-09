"""Transport / Storage / Sink mixin для RouteBuilder.

Decomposed в S84 W2 (B1, ADR-0107 pending):
- ``sinks.py`` — 10 sink_* методов (S84 W2 B1 extraction)
- persistence / scheduling / sources / proxy / external — S85+ backlog

Backward-compat: ``from src.backend.dsl.builders.transport import TransportMixin``
работает как раньше (MRO композитный).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

from src.backend.dsl.builders.transport.persistence import PersistenceMixin
from src.backend.dsl.builders.transport.sinks import SinksMixin


class TransportMixin(PersistenceMixin, SinksMixin):
    """Поведенческий миксин transport / storage / sink.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. 10 ``sink_*`` методов вынесены в
    :class:`SinksMixin` (S84 W2 B1 extraction, ADR-0107). Контракт см. в ``base.py``.
    """

    __slots__ = ()

    def directory_scan(
        self,
        path: str,
        pattern: str = "*",
        *,
        recursive: bool = False,
        max_files: int = 1000,
        sort_by: str = "name",
        result_property: str = "directory_scan_result",
    ) -> RouteBuilder:
        """Сканирует директорию и возвращает список файлов, подходящих под glob.

        S35 GAP-INT-3: batch file processing.

        Args:
            path: Директория для сканирования.
            pattern: glob-паттерн, например ``*.csv`` или ``**/*.json``.
            recursive: Рекурсивный обход поддиректорий.
            max_files: Максимальное число возвращаемых файлов.
            sort_by: Сортировка результатов: ``name`` (default),
                ``mtime`` (по времени изменения) или ``size``.
            result_property: Имя property, куда будет записан результат
                (список dict с ключами ``path``, ``name``, ``size``, ``mtime``).
        """
        from src.backend.dsl.engine.processors.fs_directory_scan import (
            DirectoryScanProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            DirectoryScanProcessor(
                path=path,
                pattern=pattern,
                recursive=recursive,
                max_files=max_files,
                sort_by=sort_by,
                result_property=result_property,
            )
        )

    def expose_proxy(
        self,
        src: str,
        *,
        methods: list[str] | None = None,
        header_map: dict[str, Any] | None = None,
    ) -> RouteBuilder:
        """Объявить роут как прокси-вход.

        Args:
            src: ``<protocol>:<address>`` (``http:/api/payments``,
                ``kafka:orders.in`` и т.п.).
            methods: HTTP-методы (для ``http``). ``None`` = все.
            header_map: Опциональный словарь ``{add|drop|override}`` для
                политики inbound-headers.
        """
        from src.backend.dsl.engine.processors.proxy import (
            ExposeProxyProcessor,
            HeaderMapPolicy,
        )

        return self._add(  # type: ignore[attr-defined]
            ExposeProxyProcessor(
                src=src,
                methods=methods,
                header_policy=HeaderMapPolicy.from_dict(header_map),
            )
        )

    def forward_to(
        self,
        dst: str,
        *,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> RouteBuilder:
        """Переслать текущее сообщение в backend без трансформаций."""
        from src.backend.dsl.engine.processors.proxy import (
            ForwardToProcessor,
            HeaderMapPolicy,
        )

        return self._add(  # type: ignore[attr-defined]
            ForwardToProcessor(
                dst=dst,
                pass_headers=pass_headers,
                header_policy=HeaderMapPolicy.from_dict(header_map),
                rewrite_path=rewrite_path,
                timeout=timeout,
            )
        )

    def from_nats_js(
        cls,
        route_id: str,
        subject: str,
        stream: str,
        durable: str,
        *,
        nats_url: str = "nats://localhost:4222",
        description: str | None = None,
    ) -> RouteBuilder:
        """Точка входа: маршрут из NATS JetStream durable consumer.

        Создаёт :class:`RouteBuilder` с источником NATS JetStream
        (durable pull consumer). Используется совместно с
        :class:`~src.backend.infrastructure.sources.nats_jetstream.NATSJetStreamSource`.

        Под feature-flag ``nats_jetstream_dsl`` (default-OFF, K3 W2).
        nats-py добавляется в pyproject.toml в S3 Wave 3 cutover.

        Args:
            route_id: Уникальный ID маршрута.
            subject: Subject (тема) NATS JetStream.
            stream: Имя JetStream stream.
            durable: Имя durable consumer (обеспечивает возобновляемость).
            nats_url: URL NATS-сервера.
            description: Человекочитаемое описание маршрута.

        Returns:
            :class:`RouteBuilder` для fluent-chain вызовов.

        Example::

            route = (
                RouteBuilder.from_nats_js(
                    "orders.jetstream.consumer",
                    subject="orders.created",
                    stream="ORDERS",
                    durable="orders-consumer",
                )
                .call_function("extensions.orders.handler:process")
                .dispatch_action("orders.ack")
                .build()
            )
        """
        source = f"nats_js:{stream}/{subject}?durable={durable}&url={nats_url}"
        return cls(route_id=route_id, source=source, description=description)  # type: ignore[operator,return-value]

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
        description: str | None = None,
    ) -> RouteBuilder:
        """Точка входа: WebDAV polling-источник (S13 K3 W2, INF-2.8).

        Сканирует папку на WebDAV-сервере (Nextcloud / OwnCloud / любой
        RFC 4918) каждые ``poll_interval_seconds`` секунд и эмитит
        ``FileEvent`` для новых файлов. Persistent marker (``_processed.txt``)
        предотвращает повторную обработку после restart.

        Args:
            route_id: Уникальный ID маршрута.
            url: Базовый URL WebDAV-сервера.
            watch_path: Папка для опроса.
            poll_interval_seconds: Интервал между PROPFIND.
            file_pattern: Glob-фильтр имени файла.
            username/password: HTTP basic auth.
            processed_marker_path: Путь к persistent marker (опц.).
            marker_dedup: Использовать persistent marker.
            description: Описание маршрута.

        Returns:
            :class:`RouteBuilder` с source ``webdav:<route_id>``.
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
        # Создаём source instance для smoke-валидации конструктора;
        # реальный wire-up идёт через source_registry на основе ``source`` URI.
        mod.WebDAVSource(cfg)
        return cls(  # type: ignore[operator,return-value]
            route_id=route_id, source=f"webdav:{route_id}", description=description
        )

    def graphql_query(
        self,
        endpoint: str,
        query: str,
        *,
        variables: dict[str, Any] | None = None,
        operation_name: str | None = None,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        auth_header: str = "Authorization",
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> RouteBuilder:
        """GraphQL query/mutation executor.

        Выполняет GraphQL-запрос к указанному endpoint с поддержкой:
        - query string и variables;
        - operation name для batched queries;
        - Bearer token authentication;
        - custom headers;
        - result writing в property или body.

        Args:
            endpoint: GraphQL endpoint URL.
            query: GraphQL query или mutation string.
            variables: Опциональные variables для query.
            operation_name: Имя операции (для batched/named operations).
            headers: Дополнительные HTTP headers.
            auth_token: Bearer token для authentication.
            auth_header: Имя auth header (default ``Authorization``).
            timeout: Request timeout в секундах (default 30.0).
            result_property: Имя property для записи результата.
                Если ``None`` — результат пишется в ``out_message.body``.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.graphql_query",
            "GraphQLQueryProcessor",
            endpoint=endpoint,
            query=query,
            variables=variables,
            operation_name=operation_name,
            headers=headers,
            auth_token=auth_token,
            auth_header=auth_header,
            timeout=timeout,
            result_property=result_property,
        )

    def http_call(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> RouteBuilder:
        """HTTP client: GET/POST/PUT/DELETE с таймаутом и headers."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "HttpCallProcessor",
            url=url,
            method=method,
            headers=headers,
            auth_token=auth_token,
            timeout=timeout,
            result_property=result_property,
        )

    def poll(
        self,
        source_action: str,
        *,
        payload: dict[str, Any] | None = None,
        result_property: str = "polled_data",
    ) -> RouteBuilder:
        """Periodically вызывает action, результат → body."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "PollingConsumerProcessor",
            source_action=source_action,
            payload=payload,
            result_property=result_property,
        )

    def proxy(
        self,
        src: str,
        dst: str,
        *,
        methods: list[str] | None = None,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> RouteBuilder:
        """Сокращение: ``expose_proxy(src) → forward_to(dst)``."""
        return self.expose_proxy(
            src=src, methods=methods, header_map=header_map
        ).forward_to(
            dst=dst,
            pass_headers=pass_headers,
            header_map=header_map,
            rewrite_path=rewrite_path,
            timeout=timeout,
        )

    def redirect(
        self,
        target_url: str | None = None,
        *,
        status_code: int = 302,
        url_source: str | None = None,
        source_key: str | None = None,
        allowed_hosts: list[str] | None = None,
    ) -> RouteBuilder:
        """Добавляет HTTP-redirect в маршрут.

        Args:
            target_url: Фиксированный URL назначения (``mode=static``).
                Если задан — используется static-режим.
            status_code: HTTP-статус редиректа (301/302/307/308). По умолчанию 302.
            url_source: Источник URL для proxy-режима:
                ``header`` | ``body_field`` | ``exchange_var`` | ``query_param``.
            source_key: Ключ для извлечения URL из источника.
            allowed_hosts: Белый список хостов (для ``url_source=query_param``).
        """
        from src.backend.dsl.engine.processors.proxy import RedirectProcessor

        if target_url is not None:
            return self._add(  # type: ignore[attr-defined]
                RedirectProcessor(
                    mode="static", status_code=status_code, target_url=target_url
                )
            )
        return self._add(  # type: ignore[attr-defined]
            RedirectProcessor(
                mode="proxy",
                status_code=status_code,
                url_source=url_source,
                source_key=source_key,
                allowed_hosts=allowed_hosts,
            )
        )

    def timer(
        self,
        *,
        interval_seconds: float | None = None,
        cron: str | None = None,
        max_fires: int | None = None,
    ) -> RouteBuilder:
        """Scheduled event source: интервал или cron-выражение."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "TimerProcessor",
            interval_seconds=interval_seconds,
            cron=cron,
            max_fires=max_fires,
        )

    def to_nats_js(
        self,
        subject: str,
        *,
        nats_url: str = "nats://localhost:4222",
        headers: dict[str, str] | None = None,
        payload_property: str | None = None,
        result_property: str = "nats_js_publish_result",
    ) -> RouteBuilder:
        """Публикует payload в NATS JetStream (Sink step).

        Добавляет шаг публикации в NATS JetStream subject.
        Использует :class:`~src.backend.infrastructure.sinks.nats_jetstream.NATSJetStreamSink`
        через :class:`GenericSinkPublishProcessor`.

        Под feature-flag ``nats_jetstream_dsl`` (default-OFF, K3 W2).
        nats-py добавляется в pyproject.toml в S3 Wave 3 cutover.

        Args:
            subject: Целевой subject (тема) JetStream.
            nats_url: URL NATS-сервера.
            headers: Заголовки NATS-сообщения (опционально).
            payload_property: Имя property с payload (None → ``in_message.body``).
            result_property: Имя property для результата публикации.

        Returns:
            Тот же :class:`RouteBuilder` для продолжения fluent-chain.

        Example::

            route = (
                RouteBuilder.from_("orders.transformer", source="http:POST /orders")
                .call_function("extensions.orders.normalizer:apply")
                .to_nats_js("orders.created", headers={"X-Source": "api"})
                .build()
            )
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {"nats_url": nats_url, "subject": subject}
        if headers:
            config["headers"] = dict(headers)

        return self._add(  # type: ignore[attr-defined]
            GenericSinkPublishProcessor(
                kind="nats_js",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def web_search(
        self,
        engine: str = "auto",
        *,
        query: str | None = None,
        query_source: str | None = None,
        max_results: int = 10,
        to: str = "body.search_results",
        deep_research: bool = False,
    ) -> RouteBuilder:
        """K3 S5 W9 — web-поиск через WebSearchService (Tavily/Perplexity/SearXNG).

        Args:
            engine: ``tavily`` / ``perplexity`` / ``searxng`` / ``auto`` (fallback).
            query: Прямой query (если задан).
            query_source: ``body.<field>`` / ``properties.<name>`` для query.
            max_results: Максимум результатов.
            to: Куда положить результат.
            deep_research: Использовать deep_research().

        Returns:
            ``RouteBuilder`` для chain-продолжения.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.web_search",
            "WebSearchProcessor",
            engine=engine,
            query=query,
            query_source=query_source,
            max_results=max_results,
            to=to,
            deep_research=deep_research,
        )
