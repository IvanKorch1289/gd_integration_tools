from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class CdcSourcesMixin:
    """CDC (Change Data Capture) source registration для RouteBuilder. S57 W2 extraction."""

    __slots__ = ()

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
    ) -> RouteBuilder:
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
        CDCSource = mod.CDCSource
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
    def from_cdc_registry(
        cls, route_id: str, backend: str, **kwargs: Any
    ) -> RouteBuilder:
        """S101 W1 — создать маршрут с CDC-source через :func:`get_cdc_source`.

        Preferred path: возвращает ``CDCSource`` Protocol (canonical
        в ``core/cdc/source.py``) вместо concrete
        ``infrastructure.sources.cdc.CDCSource``. Поддерживает все 5
        backends: ``poll`` / ``listen_notify`` / ``debezium`` / ``adapter`` /
        ``fake``.

        Args:
            route_id: Уникальный ID маршрута.
            backend: Имя CDC backend'а — одно из
                ``src.backend.core.cdc.registry.SUPPORTED_BACKENDS``.
            **kwargs: Параметры для backend'а (см. ``get_cdc_source``).

        Returns:
            ``RouteBuilder`` с ``source = cdc-registry:<backend>``.

        Example::

            route = (
                RouteBuilder.from_cdc_registry(
                    "orders.changes",
                    "poll",
                    profile="dev",
                )
                .dispatch_action("analytics.insert_batch")
                .build()
            )
        """
        from src.backend.core.cdc.registry import get_cdc_source

        source_instance = get_cdc_source(backend, **kwargs)
        builder: RouteBuilder = cls(route_id=route_id, source=f"cdc-registry:{backend}")
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
    ) -> RouteBuilder:
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
        SourceCls = mod.CdcPostgresLogicalSource
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
    ) -> RouteBuilder:
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

    def cdc_transform(
        self,
        *,
        operations: list[str] | None = None,
        project: list[str] | None = None,
        include_old: bool = True,
        include_new: bool = True,
        timestamp_field: str = "timestamp",
        drop_unknown: bool = True,
    ) -> RouteBuilder:
        """CDC event normalization + filtering + projection.

        Args:
            operations: Allowed operations (e.g. ``["INSERT", "UPDATE"]``).
            project: Fields to include in output.
            include_old: Include ``old`` payload.
            include_new: Include ``new`` payload.
            timestamp_field: Name of timestamp field in output.
            drop_unknown: Drop events without operation or table.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.cdc_transform",
            "TransformCdcEventProcessor",
            operations=operations,
            project=project,
            include_old=include_old,
            include_new=include_new,
            timestamp_field=timestamp_field,
            drop_unknown=drop_unknown,
        )
