"""Transport / Storage / Sink миксин для RouteBuilder."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class TransportMixin:
    """Поведенческий миксин transport / storage / sink.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` через
    MRO; собственных полей не содержит. Контракт см. в ``base.py``.
    """

    __slots__ = ()

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

    def db_query(self, sql: str, *, result_property: str = "db_result") -> RouteBuilder:
        """SQL-запрос через SQLAlchemy (с валидацией: DDL/multi-statement запрещены)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "DatabaseQueryProcessor",
            sql=sql,
            result_property=result_property,
        )

    def read_file(
        self, path: str | None = None, *, binary: bool = False
    ) -> RouteBuilder:
        """Чтение локального файла в body (text или bytes)."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "FileReadProcessor",
            path=path,
            binary=binary,
        )

    def write_file(
        self, path: str | None = None, *, format: str = "auto"
    ) -> RouteBuilder:
        """Запись body в файл. format: auto|json|csv|text."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "FileWriteProcessor",
            path=path,
            format=format,
        )

    def read_s3(
        self, bucket: str | None = None, key: str | None = None
    ) -> RouteBuilder:
        """Загрузка объекта из S3."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "S3ReadProcessor",
            bucket=bucket,
            key=key,
        )

    def write_s3(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        content_type: str = "application/octet-stream",
    ) -> RouteBuilder:
        """Выгрузка body в S3."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.components",
            "S3WriteProcessor",
            bucket=bucket,
            key=key,
            content_type=content_type,
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

    def db_query_external(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = "body",
        result_property: str = "db_result",
        fetch: str = "all",
        commit: bool = False,
    ) -> RouteBuilder:
        """Выполняет произвольный SQL во внешней БД по profile-имени.

        Использует ``ExternalDatabaseRegistry`` (через DI) для получения
        async-сессии. Параметры берутся из body / properties / headers.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.db_query_external",
            "ExternalDbQueryProcessor",
            profile=profile,
            sql=sql,
            params_from=params_from,
            result_property=result_property,
            fetch=fetch,
            commit=commit,
        )

    def jdbc_query(
        self,
        sql: str,
        profile: str,
        *,
        params_from: str = "body",
        result_property: str = "jdbc_result",
    ) -> RouteBuilder:
        """Execute arbitrary SQL against an external JDBC-compatible database profile.

        Uses ``ExternalDatabaseRegistry`` to obtain an async session for the
        given profile. SELECT queries return list[dict] via ``result_property``.
        INSERT/UPDATE/DELETE return affected row count (int) via ``result_property``.

        SQL is validated: DDL, DROP, GRANT, REVOKE, and multi-statement are blocked.
        Bind-parameters are sourced from body / properties / headers.

        Args:
            sql: SQL query with ``:name`` bind-parameters.
            profile: External database profile name.
            params_from: Source of bind-parameters — ``"body"`` (default) /
                ``"properties"`` / ``"headers"`` / ``"none"``.
            result_property: Exchange property key for the result.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.jdbc_query",
            "JdbcQueryProcessor",
            sql=sql,
            profile=profile,
            params_from=params_from,
            result_property=result_property,
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

    def db_call_procedure(
        self,
        profile: str,
        name: str,
        *,
        schema: str = "public",
        params_from: str = "body",
        result_property: str = "sp_result",
        dialect: str = "postgres",
    ) -> RouteBuilder:
        """K3 S5 W8 — вызвать stored procedure через ExternalDatabaseRegistry.

        Args:
            profile: Профиль внешней БД из ``settings.external_databases``.
            name: Имя процедуры.
            schema: Schema-префикс (default ``public``).
            params_from: ``body`` / ``properties`` / ``headers`` / ``none``.
            result_property: Куда положить result-set.
            dialect: ``postgres`` / ``mssql`` / ``oracle``.

        Returns:
            ``RouteBuilder`` для chain-продолжения.

        Example::

            (
                RouteBuilder.from_("orders.recalc", source="timer:60s")
                .db_call_procedure("oracle_prod", "recalc_credit_score")
                .build()
            )
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.db_call_procedure",
            "DbCallProcedureProcessor",
            profile=profile,
            name=name,
            schema=schema,
            params_from=params_from,
            result_property=result_property,
            dialect=dialect,
        )

    def file_move(
        self, src: str | None = None, dst: str | None = None, *, mode: str = "copy"
    ) -> RouteBuilder:
        """Copy/move/rename файлов."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.rpa",
            "FileMoveProcessor",
            src=src,
            dst=dst,
            mode=mode,
        )

    def sink_grpc(
        self,
        *,
        target: str,
        full_method: str,
        secure: bool = True,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "grpc_result",
    ) -> RouteBuilder:
        """Camel-style fluent для gRPC unary-вызова (Sprint 3 W1 K3).

        Тонкий wrapper над :class:`GrpcCallProcessor` — публикует
        payload через :class:`~src.backend.infrastructure.sinks.grpc_sink.GrpcSink`.

        Args:
            target: ``host:port`` целевого сервера.
            full_method: Fully-qualified ``"/package.Service/Method"``.
            secure: Использовать TLS (default True).
            timeout: Дедлайн вызова в секундах.
            payload_property: Имя property с payload (None → ``in_message.body``).
            result_property: Имя property для результата публикации.
        """
        from src.backend.dsl.engine.processors.sink_publish import GrpcCallProcessor

        return self._add(  # type: ignore[attr-defined]
            GrpcCallProcessor(
                target=target,
                full_method=full_method,
                secure=secure,
                timeout=timeout,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_soap(
        self,
        *,
        wsdl_url: str,
        operation: str,
        service_name: str | None = None,
        port_name: str | None = None,
        timeout: float = 30.0,
        payload_property: str | None = None,
        result_property: str = "soap_result",
    ) -> RouteBuilder:
        """Camel-style fluent для SOAP/WSDL-вызова (Sprint 3 W1 K3).

        См. :class:`SoapCallProcessor` и
        :class:`~src.backend.infrastructure.sinks.soap_sink.SoapSink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import SoapCallProcessor

        return self._add(  # type: ignore[attr-defined]
            SoapCallProcessor(
                wsdl_url=wsdl_url,
                operation=operation,
                service_name=service_name,
                port_name=port_name,
                timeout=timeout,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_mq(
        self,
        *,
        broker: str,
        url: str,
        topic: str,
        extra: dict[str, Any] | None = None,
        payload_property: str | None = None,
        result_property: str = "mq_publish_result",
    ) -> RouteBuilder:
        """Camel-style fluent для публикации в Kafka/RabbitMQ/Redis-Streams/NATS.

        См. :class:`MqPublishProcessor` и
        :class:`~src.backend.infrastructure.sinks.mq_sink.MqSink`.

        Args:
            broker: ``"kafka"`` | ``"rabbit"`` | ``"redis"`` | ``"nats"``.
            url: Broker URL.
            topic: Топик / exchange / stream / subject.
            extra: Доп. параметры publish (routing_key, partition, headers).
        """
        from src.backend.dsl.engine.processors.sink_publish import MqPublishProcessor

        return self._add(  # type: ignore[attr-defined]
            MqPublishProcessor(
                broker=broker,
                url=url,
                topic=topic,
                extra=extra,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_ws(
        self,
        *,
        url: str,
        extra_headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "ws_publish_result",
    ) -> RouteBuilder:
        """Camel-style fluent для outbound WebSocket publish.

        См. :class:`WsPublishProcessor` и
        :class:`~src.backend.infrastructure.sinks.ws_sink.WsSink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import WsPublishProcessor

        return self._add(  # type: ignore[attr-defined]
            WsPublishProcessor(
                url=url,
                extra_headers=extra_headers,
                timeout=timeout,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_mqtt(
        self,
        *,
        host: str,
        topic: str,
        port: int | None = None,
        qos: int = 0,
        retain: bool = False,
        username: str | None = None,
        password: str | None = None,
        payload_property: str | None = None,
        result_property: str = "mqtt_publish_result",
    ) -> RouteBuilder:
        """Camel-style fluent для публикации в MQTT-брокер.

        См. :class:`MqttPublishProcessor` и
        :class:`~src.backend.infrastructure.sinks.mqtt_sink.MqttSink`.
        """
        from src.backend.entrypoints.mqtt.mqtt_handler import MqttSettings

        if port is None:
            port = MqttSettings().broker_port
        from src.backend.dsl.engine.processors.sink_publish import MqttPublishProcessor

        return self._add(  # type: ignore[attr-defined]
            MqttPublishProcessor(
                host=host,
                topic=topic,
                port=port,
                qos=qos,
                retain=retain,
                username=username,
                password=password,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_email(
        self,
        *,
        host: str,
        from_addr: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
        start_tls: bool = True,
        default_to: str | None = None,
        default_subject: str = "",
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> RouteBuilder:
        """Camel-style fluent для SMTP-публикации (Sprint 3 W1 K3).

        Использует обобщённый :class:`GenericSinkPublishProcessor` —
        строит :class:`~src.backend.infrastructure.sinks.email_sink.EmailSink`
        через :func:`build_sink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {
            "host": host,
            "port": port,
            "from_addr": from_addr,
            "use_tls": use_tls,
            "start_tls": start_tls,
            "default_subject": default_subject,
        }
        if username is not None:
            config["username"] = username
        if password is not None:
            config["password"] = password
        if default_to is not None:
            config["default_to"] = default_to

        return self._add(  # type: ignore[attr-defined]
            GenericSinkPublishProcessor(
                kind="email",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_webhook(
        self,
        *,
        url: str,
        event: str,
        secret: str | None = None,
        timeout: float = 10.0,
        extra_headers: dict[str, str] | None = None,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> RouteBuilder:
        """Camel-style fluent для outbound webhook с HMAC-подписью.

        См. :class:`~src.backend.infrastructure.sinks.webhook_sink.WebhookSink`.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {"url": url, "event": event, "timeout": timeout}
        if secret is not None:
            config["secret"] = secret
        if extra_headers:
            config["extra_headers"] = dict(extra_headers)

        return self._add(  # type: ignore[attr-defined]
            GenericSinkPublishProcessor(
                kind="webhook",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_file(
        self,
        *,
        path: str,
        mode: str = "append",
        encoding: str = "utf-8",
        ensure_dir: bool = True,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> RouteBuilder:
        """Camel-style fluent для записи в local FS (append / write).

        См. :class:`~src.backend.infrastructure.sinks.file_sink.FileSink`.

        Args:
            path: Целевой путь к файлу.
            mode: ``"append"`` (NDJSON) или ``"write"`` (атомарный rewrite).
            encoding: Кодировка для текстовых payload (UTF-8 default).
            ensure_dir: Создавать parent dir если отсутствует.
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {
            "path": path,
            "mode": mode,
            "encoding": encoding,
            "ensure_dir": ensure_dir,
        }

        return self._add(  # type: ignore[attr-defined]
            GenericSinkPublishProcessor(
                kind="file",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_http(
        self,
        *,
        url: str,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> RouteBuilder:
        """Camel-style fluent для REST POST/PUT/PATCH/DELETE через Sink.

        В отличие от :meth:`http_call` (general-purpose HTTP client),
        :meth:`sink_http` использует
        :class:`~src.backend.infrastructure.sinks.http_sink.HttpSink` для
        полной Sink-симметрии (один обобщённый ``sink_publish`` step).
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {"url": url, "method": method, "timeout": timeout}
        if headers:
            config["headers"] = dict(headers)

        return self._add(  # type: ignore[attr-defined]
            GenericSinkPublishProcessor(
                kind="http",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

    def sink_s3(
        self,
        *,
        bucket: str,
        key: str,
        content_type: str = "application/octet-stream",
        payload_property: str | None = None,
        result_property: str = "sink_publish_result",
    ) -> RouteBuilder:
        """Camel-style fluent для выгрузки payload в S3/MinIO.

        См. :class:`~src.backend.infrastructure.sinks.s3_sink.S3Sink`
        (Sprint 3 W1 K3, GAP-03 symmetry).
        """
        from src.backend.dsl.engine.processors.sink_publish import (
            GenericSinkPublishProcessor,
        )

        config: dict[str, Any] = {
            "bucket": bucket,
            "key": key,
            "content_type": content_type,
        }

        return self._add(  # type: ignore[attr-defined]
            GenericSinkPublishProcessor(
                kind="s3",
                config=config,
                payload_property=payload_property,
                result_property=result_property,
            )
        )

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
        return cls(  # type: ignore[return-value]
            route_id=route_id, source=f"webdav:{route_id}", description=description
        )

    @classmethod
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
        return cls(route_id=route_id, source=source, description=description)  # type: ignore[return-value]

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
