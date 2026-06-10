"""Mixin for transport data source methods (S50 W2 extraction, ADR-0107 B3-B5).

Extracted from ``transport.py`` god-file (S84 B1).
MRO composition: TransportMixin → SourcesMixin → ExternalMixin → ProxyMixin → PersistenceMixin → SinksMixin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class SourcesMixin:
    """Stateless mixin. Uses self._add / self._add_lazy via MRO."""

    __slots__ = ()

    # --- data source methods ---
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

