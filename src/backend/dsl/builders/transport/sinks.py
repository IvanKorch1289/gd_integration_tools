"""Sinks mixin: 10 sink_* fluent методов для outbound публикации.

Извлечено из TransportMixin в S84 W2 (B1, ADR-0107 pending).
10 методов: sink_grpc, sink_soap, sink_mq, sink_ws, sink_mqtt, sink_email,
sink_webhook, sink_file, sink_http, sink_s3.

Все методы — тонкие wrappers над :class:`GenericSinkPublishProcessor`
(или специализированные :class:`GrpcCallProcessor` / :class:`SoapCallProcessor`
для legacy совместимости). Config-словари инкапсулируют параметры sink-impl.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class SinksMixin:
    """Mixin: 10 sink_* методов для outbound публикации (S84 W2 B1 extraction)."""

    __slots__ = ()

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
        from src.backend.core.config.services.mqtt import mqtt_settings as _mqtt_settings

        if port is None:
            port = _mqtt_settings.broker_port
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

    def ssh_command(
        self,
        host: str,
        command: str,
        *,
        username: str | None = None,
        password_from: str = "none",  # noqa: S107 — source selector, not password
        key_file: str | None = None,
        timeout: float = 30.0,
        result_property: str = "ssh_result",
        continue_on_error: bool = False,
    ) -> RouteBuilder:
        """SSH remote command execution (Sprint 35).

        Args:
            host: SSH server address.
            command: Command to execute.
            username: SSH username (None = system username).
            password_from: Password source: ``"body"``, ``"properties"`` or ``"none"``.
            key_file: Path to private key file.
            timeout: Command timeout in seconds.
            result_property: Property name for result ``{stdout, stderr, exit_code}``.
            continue_on_error: If True, non-zero exit_code won't fail the route.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.ssh_command",
            "SshCommandProcessor",
            host=host,
            command=command,
            username=username,
            password_from=password_from,
            key_file=key_file,
            timeout=timeout,
            result_property=result_property,
            continue_on_error=continue_on_error,
        )

    def webdav(
        self,
        url: str,
        *,
        username: str | None = None,
        password: str | None = None,
        mode: str = "upload",
        remote_path: str = "/",
        source: str = "body",
        to: str = "body.webdav_result",
    ) -> RouteBuilder:
        """WebDAV upload/download/list/delete via webdav4.

        Args:
            url: WebDAV server base URL.
            username: Authentication username.
            password: Authentication password.
            mode: ``"upload"``, ``"download"``, ``"list"`` or ``"delete"``.
            remote_path: Remote path on server.
            source: Source for upload data.
            to: Destination for download/list results.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.webdav_io",
            "WebDavProcessor",
            url=url,
            username=username,
            password=password,
            mode=mode,
            remote_path=remote_path,
            source=source,
            to=to,
        )
