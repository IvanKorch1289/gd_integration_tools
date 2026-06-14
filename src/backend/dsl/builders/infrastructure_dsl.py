"""InfrastructureDSL (S38 W4): 14 helper methods для Redis/ClickHouse/ES/Mongo/S3/SQL.

Stateless mixin для :class:`RouteBuilder`. Каждый wrapper — тонкая обёртка
над placeholder-процессором, фиксирующим intent операции в pipeline.
Реальное подключение к backend'ам (Redis/ClickHouse/ES/Mongo/S3) — через
downstream фасады в lifespan (DI-wiring).

Паттерн: копия :class:`EventBusMixin` (chainable, ``_add`` через MRO,
``__slots__ = ()``, ``to_spec()`` для сериализации).

14 методов:
    * Redis (3): ``redis_set``, ``redis_get``, ``redis_delete``
    * ClickHouse (2): ``clickhouse_insert``, ``clickhouse_query``
    * Elasticsearch (2): ``es_index``, ``es_search``
    * MongoDB (2): ``mongo_insert``, ``mongo_find``
    * S3 (4): ``s3_put``, ``s3_get``, ``s3_delete`` (S111 W1), ``s3_list`` (S111 W1)
    * SQL (1): ``sql_exec``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "ClickHouseInsertProcessor",
    "ClickHouseQueryProcessor",
    "ElasticsearchIndexProcessor",
    "ElasticsearchSearchProcessor",
    "InfrastructureDSL",
    "MongoFindProcessor",
    "MongoInsertProcessor",
    "RedisDeleteProcessor",
    "RedisGetProcessor",
    "RedisSetProcessor",
    "S3DeleteProcessor",
    "S3GetProcessor",
    "S3ListProcessor",
    "S3PutProcessor",
    "SqlExecProcessor",
)


class _InfraOp(BaseProcessor):
    """Общий базовый placeholder для инфраструктурных операций (S38 W4).

    Хранит ``op_name`` (имя операции в ``to_spec``) + ``params`` (dict).
    Наследники задают ``comp_`` флаг (compensatable) и опц. сторону эффекта.
    Реальный backend-wiring — в lifespan через DI-фасады.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = True
    op_name: ClassVar[str] = ""

    def __init__(self, *, name: str | None = None, **params: Any) -> None:
        super().__init__(name=name or f"{self.op_name}")
        self.params = params

    def to_spec(self) -> dict[str, Any] | None:
        return {self.op_name: dict(self.params)}

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Stub: real wiring в lifespan через DI-фасады. Records intent only."""
        exchange.set_property(f"{self.op_name}_pending", dict(self.params))


# ── Redis (3) ──────────────────────────────────────────────────────────


class RedisSetProcessor(_InfraOp):
    op_name: ClassVar[str] = "redis_set"
    compensatable: ClassVar[bool] = True


class RedisGetProcessor(_InfraOp):
    op_name: ClassVar[str] = "redis_get"
    compensatable: ClassVar[bool] = True


class RedisDeleteProcessor(_InfraOp):
    op_name: ClassVar[str] = "redis_delete"
    compensatable: ClassVar[bool] = True


# ── ClickHouse (2) ─────────────────────────────────────────────────────


class ClickHouseInsertProcessor(_InfraOp):
    op_name: ClassVar[str] = "clickhouse_insert"
    compensatable: ClassVar[bool] = False  # INSERT без компенсации


class ClickHouseQueryProcessor(_InfraOp):
    op_name: ClassVar[str] = "clickhouse_query"
    compensatable: ClassVar[bool] = True


# ── Elasticsearch (2) ──────────────────────────────────────────────────


class ElasticsearchIndexProcessor(_InfraOp):
    op_name: ClassVar[str] = "es_index"
    compensatable: ClassVar[bool] = False  # индекс необратим


class ElasticsearchSearchProcessor(_InfraOp):
    op_name: ClassVar[str] = "es_search"
    compensatable: ClassVar[bool] = True


# ── MongoDB (2) ────────────────────────────────────────────────────────


class MongoInsertProcessor(_InfraOp):
    op_name: ClassVar[str] = "mongo_insert"
    compensatable: ClassVar[bool] = False


class MongoFindProcessor(_InfraOp):
    op_name: ClassVar[str] = "mongo_find"
    compensatable: ClassVar[bool] = True


# ── S3 (1) ─────────────────────────────────────────────────────────────


class S3PutProcessor(_InfraOp):
    op_name: ClassVar[str] = "s3_put"
    compensatable: ClassVar[bool] = True


class S3GetProcessor(_InfraOp):
    """S104 W1 — S3 GET processor (требует aioboto3)."""
    op_name: ClassVar[str] = "s3_get"
    compensatable: ClassVar[bool] = False


class S3DeleteProcessor(_InfraOp):
    """S111 W1 — S3 DELETE processor (idempotent: missing → no-op)."""
    op_name: ClassVar[str] = "s3_delete"
    compensatable: ClassVar[bool] = False  # delete необратим


class S3ListProcessor(_InfraOp):
    """S111 W1 — S3 LIST processor (пагинация по префиксу)."""
    op_name: ClassVar[str] = "s3_list"
    compensatable: ClassVar[bool] = True  # read — обратимо


class SftpGetProcessor(_InfraOp):
    """S104 W1 — SFTP GET processor (требует asyncssh)."""
    op_name: ClassVar[str] = "sftp_get"
    compensatable: ClassVar[bool] = False


class SftpPutProcessor(_InfraOp):
    """S104 W1 — SFTP PUT processor (требует asyncssh)."""
    op_name: ClassVar[str] = "sftp_put"
    compensatable: ClassVar[bool] = True


# ── SQL (1) ────────────────────────────────────────────────────────────


class SqlExecProcessor(_InfraOp):
    """SQL exec placeholder для ``op_name="sql_exec"`` (DML/DDL).

    Используется :meth:`RouteBuilder.sql_exec` для выполнения
    произвольного SQL через переданный ``async_engine``. Компенсация
    отключена (``compensatable=False``) — DML нельзя автоматически
    откатить без явной inverse-операции в compensable spec'е.
    """
    op_name: ClassVar[str] = "sql_exec"
    compensatable: ClassVar[bool] = False  # DML не компенсируется


# ── Mixin ──────────────────────────────────────────────────────────────


class InfrastructureDSL:
    """RouteBuilder mixin: 11 helper methods для инфраструктурных клиентов (S38 W4).

    Все методы chainable (``return self``). Каждый wrapper создаёт
    placeholder-процессор и добавляет его в pipeline через
    :func:`RouteBuilder._add`. Реальный backend-wiring — в lifespan
    через DI-фасады (``RedisFacade``, ``ClickHouseFacade`` и т.п.).

    Example::

        route = (
            RouteBuilder.from_("etl.import", source="timer:300s")
            .redis_set("cache:user:42", "${body}", ttl_seconds=60)
            .clickhouse_insert("events", batch_size=500)
            .es_index("events-2026", doc_id_from="body.id")
            .mongo_find("audit_log", {"level": "error"})
            .s3_put("backups/daily.json")
            .sql_exec("UPDATE jobs SET status = :status", params={"status": "done"})
            .build()
        )
    """

    __slots__ = ()

    # ── Redis (3) ──

    def redis_set(
        self, key: str, value: str, *, ttl_seconds: int | None = None
    ) -> RouteBuilder:
        """``SET key value [EX ttl]`` в Redis. ``ttl_seconds=None`` = бессрочно."""
        return self._add(  # type: ignore[attr-defined]
            RedisSetProcessor(key=key, value=value, ttl_seconds=ttl_seconds)
        )

    def redis_get(self, key: str, *, default: Any = None) -> RouteBuilder:
        """``GET key`` в Redis; ``default`` при отсутствии ключа."""
        return self._add(  # type: ignore[attr-defined]
            RedisGetProcessor(key=key, default=default)
        )

    def redis_delete(self, key: str) -> RouteBuilder:
        """``DEL key`` в Redis."""
        return self._add(  # type: ignore[attr-defined]
            RedisDeleteProcessor(key=key)
        )

    # ── ClickHouse (2) ──

    def clickhouse_insert(self, table: str, *, batch_size: int = 1000) -> RouteBuilder:
        """Batch INSERT в ClickHouse ``table`` из exchange body."""
        return self._add(  # type: ignore[attr-defined]
            ClickHouseInsertProcessor(table=table, batch_size=batch_size)
        )

    def clickhouse_query(
        self, query: str, *, to_property: str = "query_result"
    ) -> RouteBuilder:
        """SELECT в ClickHouse; результат в ``exchange.properties[to_property]``."""
        return self._add(  # type: ignore[attr-defined]
            ClickHouseQueryProcessor(query=query, to_property=to_property)
        )

    # ── Elasticsearch (2) ──

    def es_index(self, index: str, *, doc_id_from: str | None = None) -> RouteBuilder:
        """Индексирует документ из body в ES ``index``.

        ``doc_id_from=None`` → ES auto-generates ``_id``.
        """
        return self._add(  # type: ignore[attr-defined]
            ElasticsearchIndexProcessor(index=index, doc_id_from=doc_id_from)
        )

    def es_search(self, index: str, query: dict, *, size: int = 10) -> RouteBuilder:
        """Поиск в ES; hits в ``exchange.properties["_es_hits"]``."""
        return self._add(  # type: ignore[attr-defined]
            ElasticsearchSearchProcessor(index=index, query=query, size=size)
        )

    # ── MongoDB (2) ──

    def mongo_insert(
        self, collection: str, *, document_from: str = "body"
    ) -> RouteBuilder:
        """INSERT документа в Mongo ``collection``."""
        return self._add(  # type: ignore[attr-defined]
            MongoInsertProcessor(collection=collection, document_from=document_from)
        )

    def mongo_find(
        self, collection: str, query: dict, *, to_property: str = "docs"
    ) -> RouteBuilder:
        """FIND документов в Mongo; результат в ``exchange.properties[to_property]``."""
        return self._add(  # type: ignore[attr-defined]
            MongoFindProcessor(
                collection=collection, query=query, to_property=to_property
            )
        )

    # ── S3 (2) ──

    def s3_put(self, key: str, *, body_from: str = "body") -> RouteBuilder:
        """PUT объекта в S3 по ``key`` (body из ``body_from``)."""
        return self._add(  # type: ignore[attr-defined]
            S3PutProcessor(key=key, body_from=body_from)
        )

    def s3_get(self, key: str, *, result_property: str = "s3_object") -> RouteBuilder:
        """GET объекта из S3 по ``key``.

        S104 W1: NEW DSL method для D21 RPA coverage.
        Использует :class:`S3GetProcessor` (требует aioboto3 — optional dep).

        Args:
            key: S3 object key (e.g. ``"backups/daily.json"``).
            result_property: Куда писать результат
                (``{"body": ..., "metadata": ..., "etag": ...}``).

        Returns:
            RouteBuilder с добавленным ``S3GetProcessor`` в pipeline.
        """
        return self._add(  # type: ignore[attr-defined]
            S3GetProcessor(key=key, result_property=result_property)
        )

    def s3_delete(self, key_from: str = "s3_key") -> RouteBuilder:
        """DELETE объекта из S3 по ``key_from`` (idempotent: missing → no-op).

        S111 W1: NEW DSL method (TD-017 / D17 closure).
        Использует :class:`S3DeleteProcessor` (требует aioboto3 — optional dep).

        Args:
            key_from: выражение для S3-ключа (default ``"s3_key"``).

        Returns:
            RouteBuilder с добавленным ``S3DeleteProcessor`` в pipeline.
        """
        return self._add(  # type: ignore[attr-defined]
            S3DeleteProcessor(key_from=key_from)
        )

    def s3_list(
        self,
        *,
        prefix_from: str | None = None,
        result_property: str = "s3_keys",
    ) -> RouteBuilder:
        """LIST ключей в S3 bucket с пагинацией по ``prefix_from``.

        S111 W1: NEW DSL method (TD-017 / D17 closure).
        Использует :class:`S3ListProcessor` (требует aioboto3 — optional dep).

        Args:
            prefix_from: выражение для префикса (опционально).
            result_property: имя property для записи ``list[str]``
                (default ``"s3_keys"``).

        Returns:
            RouteBuilder с добавленным ``S3ListProcessor`` в pipeline.
        """
        return self._add(  # type: ignore[attr-defined]
            S3ListProcessor(prefix_from=prefix_from, result_property=result_property)
        )

    # ── SFTP (2) — S104 W1 ──

    def sftp_get(
        self,
        host: str,
        remote_path: str,
        *,
        username: str | None = None,
        password_from: str = "none",
        key_file: str | None = None,
        timeout: float = 30.0,
        result_property: str = "sftp_object",
    ) -> RouteBuilder:
        """S104 W1 — GET файла с SFTP-сервера.

        Args:
            host: Адрес SFTP-сервера.
            remote_path: Путь к файлу на сервере.
            username: SFTP-пользователь (``None`` = системный).
            password_from: Источник пароля (``"body"`` / ``"properties"`` / ``"none"``).
            key_file: Путь к private key (для key-based auth).
            timeout: Таймаут в секундах.
            result_property: Куда писать результат (``{"body": ..., "metadata": ...}``).

        Returns:
            RouteBuilder с добавленным ``SftpGetProcessor`` в pipeline.
        """
        return self._add(  # type: ignore[attr-defined]
            SftpGetProcessor(
                host=host,
                remote_path=remote_path,
                username=username,
                password_from=password_from,
                key_file=key_file,
                timeout=timeout,
                result_property=result_property,
            )
        )

    def sftp_put(
        self,
        host: str,
        remote_path: str,
        *,
        body_from: str = "body",
        username: str | None = None,
        password_from: str = "none",
        key_file: str | None = None,
        timeout: float = 30.0,
        result_property: str = "sftp_result",
    ) -> RouteBuilder:
        """S104 W1 — PUT файла на SFTP-сервер.

        Args:
            host: Адрес SFTP-сервера.
            remote_path: Путь к файлу на сервере.
            body_from: Источник содержимого (``"body"`` / ``"properties"``).
            username: SFTP-пользователь.
            password_from: Источник пароля.
            key_file: Путь к private key.
            timeout: Таймаут в секундах.
            result_property: Куда писать результат.

        Returns:
            RouteBuilder с добавленным ``SftpPutProcessor`` в pipeline.
        """
        return self._add(  # type: ignore[attr-defined]
            SftpPutProcessor(
                host=host,
                remote_path=remote_path,
                body_from=body_from,
                username=username,
                password_from=password_from,
                key_file=key_file,
                timeout=timeout,
                result_property=result_property,
            )
        )

    # ── SQL (1) ──

    def sql_exec(self, query: str, *, params: dict | None = None) -> RouteBuilder:
        """INSERT/UPDATE/DELETE с bind-параметрами ``:name``."""
        return self._add(  # type: ignore[attr-defined]
            SqlExecProcessor(query=query, params=params or {})
        )
