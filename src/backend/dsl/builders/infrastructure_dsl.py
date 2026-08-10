"""InfrastructureDSL (S38 W4 → S175 #5 hybrid): 9 phantom-stub helper methods.

Stateless mixin для :class:`RouteBuilder`. Каждый wrapper — тонкая обёртка
над placeholder-процессором, фиксирующим intent операции в pipeline.

S175 #5 (lockjaw-vision-rocket.md): гибридный подход (resolution of
audit-warning vs deletion conflict с parallel WIP):
- 7 stubs + их mixin methods **DELETED** (replaced by real implementations
  в :mod:`src.backend.dsl.engine.processors.infra_*` namespace):
  - ``RedisGetProcessor`` → ``InfraRedisGetProcessor``
  - ``ClickHouseQueryProcessor`` → ``InfraClickHouseQueryProcessor``
  - ``S3PutProcessor`` / ``S3GetProcessor`` → ``ToS3Processor`` /
    ``FromS3Processor`` в ``storage/s3.py``
  - ``S3DeleteProcessor`` / ``S3ListProcessor`` → те же в ``storage/s3.py``
  - ``SqlExecProcessor`` → ``InfraDbQueryProcessor``
- 8 stubs **KEPT** as fallback (no real replacement yet, audit-warning
  for observability per parallel WIP S175 M5.3):
  - ``RedisSetProcessor``, ``RedisDeleteProcessor``
  - ``ClickHouseInsertProcessor``
  - ``ElasticsearchIndexProcessor``, ``ElasticsearchSearchProcessor``
  - ``MongoInsertProcessor``, ``MongoFindProcessor`` (partial — Find
    уже в :mod:`infra_mongodb.py`)
  - ``SftpGetProcessor``, ``SftpPutProcessor``

Real implementations в :mod:`src.backend.dsl.engine.processors.infra_*`
(parallel WIP, S170 Phase 2). Эти процессоры используют direct DI
через ``infrastructure_facade`` (без phantom stubs).

Паттерн: копия :class:`EventBusMixin` (chainable, ``_add`` через MRO,
``__slots__ = ()``, ``to_spec()`` для сериализации).

9 методов (после S175 #5 hybrid):
    * Redis (2): ``redis_set``, ``redis_delete``
    * ClickHouse (1): ``clickhouse_insert``
    * Elasticsearch (2): ``es_index``, ``es_search``
    * MongoDB (2): ``mongo_insert``, ``mongo_find``
    * SFTP (2): ``sftp_get``, ``sftp_put``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor

# S175: module-level logger for phantom-stub observability
_stub_logger = get_logger("dsl.infrastructure_dsl.stub")

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "ClickHouseInsertProcessor",
    "ElasticsearchIndexProcessor",
    "ElasticsearchSearchProcessor",
    "InfrastructureDSL",
    "MongoFindProcessor",
    "MongoInsertProcessor",
    "RedisDeleteProcessor",
    "RedisSetProcessor",
    "SftpGetProcessor",
    "SftpPutProcessor",
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
        """Сериализовать ``self.params`` в DSL-спецификацию ``{op_name: params}``.

        Returns:
            dict c единственным ключом ``op_name`` и значением — копия
            ``self.params`` (защита от мутации caller'ом).

        """
        return {self.op_name: dict(self.params)}

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """S182: реальный backend wiring через DI-фасады (lazy import).

        Каждый subclass переопределяет ``_execute()`` для конкретной операции.
        Fallback — логирование intent (для backward-compat).
        """
        # Cycle 97 L3: emit intent log on EVERY stub execution (не только
        # на exception). Default _execute не raise'ит — без этого лога
        # observability пустая. Audit-trail важнее для audit-секции.
        _stub_logger.warning(
            "InfraOp stub executed: op=%s, params=%s",
            self.op_name,
            list(self.params.keys()),
        )
        try:
            await self._execute(exchange, context)
        except Exception as exc:
            _stub_logger.warning(
                "InfraOp stub failed: op=%s, params=%s (error=%s)",
                self.op_name,
                list(self.params.keys()),
                exc,
            )
            exchange.set_property(f"{self.op_name}_pending", dict(self.params))

    async def _execute(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Subclass hook — реализация через DI facade."""
        # Default: запись intent в properties (backward-compat)
        exchange.set_property(f"{self.op_name}_pending", dict(self.params))


# ── Redis (3) ──────────────────────────────────────────────────────────


class RedisSetProcessor(_InfraOp):
    """Redis SET с опциональным TTL (``params.ttl_seconds``)."""

    op_name: ClassVar[str] = "redis_set"
    compensatable: ClassVar[bool] = True

    async def _execute(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """S182: реальный Redis backend через DI facade."""
        from src.backend.infrastructure.clients.storage.redis import get_redis_client

        client = get_redis_client()
        cache_client = await client.get_client("cache")
        key = self.params.get("key", "")
        value = self.params.get("value", "")
        ttl_seconds = self.params.get("ttl_seconds")
        if ttl_seconds:
            await cache_client.set(key, value, ex=ttl_seconds)
        else:
            await cache_client.set(key, value)
        exchange.set_property(f"{self.op_name}_result", key)



class RedisDeleteProcessor(_InfraOp):
    """Redis DEL (идемпотентно: missing key → no-op)."""

    op_name: ClassVar[str] = "redis_delete"
    compensatable: ClassVar[bool] = True

    async def _execute(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """S182: реальный Redis DELETE через DI facade."""
        from src.backend.infrastructure.clients.storage.redis import get_redis_client

        client = get_redis_client()
        cache_client = await client.get_client("cache")
        key = self.params.get("key", "")
        await cache_client.delete(key)
        exchange.set_property(f"{self.op_name}_result", key)



# ── ClickHouse (2) ─────────────────────────────────────────────────────


class ClickHouseInsertProcessor(_InfraOp):
    """ClickHouse INSERT (batch). INSERT не имеет meaningful compensation.

    Cycle 29 P2:

    * ``rows_from`` — выражение exchange-property (например ``"body.rows"``),
      откуда берётся список строк для INSERT. По умолчанию ``"body"`` —
      тогда весь body трактуется как список ``list[dict[str, Any]]``.
    * ``batch_size`` пробрасывается в ``client.insert(batch_size=...)`` —
      реально доходит до client и управляет chunking'ом.
    * Oversized body (длиннее ``MAX_INSERT_ROWS``) → ``exchange.fail()`` —
      fail-fast без HTTP-запроса.
    """

    op_name: ClassVar[str] = "clickhouse_insert"
    compensatable: ClassVar[bool] = False  # INSERT без компенсации

    async def _execute(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """S182: реальный ClickHouse INSERT через DI facade."""
        from src.backend.infrastructure.clients.storage.clickhouse import (
            MAX_INSERT_ROWS,
            get_clickhouse_client,
        )

        client = get_clickhouse_client()
        table = self.params.get("table", "")
        rows_from: str = self.params.get("rows_from", "body")
        batch_size = self.params.get("batch_size")

        # Достаём rows из exchange-property (по умолчанию — ``body``).
        rows = self._resolve_rows(exchange, rows_from)

        if rows is None:
            exchange.fail(
                f"clickhouse_insert: rows_from={rows_from!r} "
                "missing or not a list of dicts",
            )
            return

        # Fail-fast: защита от OOM / runaway-ETL.
        if len(rows) > MAX_INSERT_ROWS:
            exchange.fail(
                f"clickhouse_insert: refusing oversized batch "
                f"({len(rows)} > MAX_INSERT_ROWS={MAX_INSERT_ROWS}); "
                "split caller-side before insert()",
            )
            return

        n = await client.insert(table, rows, batch_size=batch_size)
        exchange.set_property(f"{self.op_name}_result", n)

    @staticmethod
    def _resolve_rows(exchange: Exchange[Any], rows_from: str) -> list[Any] | None:
        """Достать список строк из exchange по dotted-path выражению.

        Поддерживает пути вида ``"body"`` или ``"body.rows"`` (точка =
        спуск в dict / list индекс через ``int``).
        Возвращает ``None`` если property отсутствует, не dict или
        не ``list[dict[str, Any]]``.
        """
        cur: Any = exchange.in_message
        for part in rows_from.split("."):
            if cur is None:
                return None
            if hasattr(cur, part):
                cur = getattr(cur, part)
                continue
            if isinstance(cur, dict):
                cur = cur.get(part)
                continue
            if isinstance(cur, list):
                try:
                    idx = int(part)
                except ValueError:
                    return None
                cur = cur[idx] if -len(cur) <= idx < len(cur) else None
                continue
            return None
        if not isinstance(cur, list):
            return None
        # Разрешаем list[dict] — каждая строка должна быть dict (row-format).
        if not all(isinstance(r, dict) for r in cur):
            return None
        return cur



# ── Elasticsearch (2) ──────────────────────────────────────────────────


class ElasticsearchIndexProcessor(_InfraOp):
    """Elasticsearch INDEX/UPSERT документа. Индексирование необратимо."""

    op_name: ClassVar[str] = "es_index"
    compensatable: ClassVar[bool] = False  # индекс необратим

    async def _execute(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """S182: реальный Elasticsearch INDEX через DI facade."""
        from src.backend.infrastructure.clients.storage.elasticsearch import (
            get_elasticsearch_client,
        )

        client = get_elasticsearch_client()
        index = self.params.get("index", "")
        document = self.params.get("document", {})
        await client.index_document(index, document)
        exchange.set_property(f"{self.op_name}_result", "indexed")



class ElasticsearchSearchProcessor(_InfraOp):
    """Elasticsearch SEARCH (read-only)."""

    op_name: ClassVar[str] = "es_search"
    compensatable: ClassVar[bool] = True

    async def _execute(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """S182: реальный Elasticsearch SEARCH через DI facade."""
        from src.backend.infrastructure.clients.storage.elasticsearch import (
            get_elasticsearch_client,
        )

        client = get_elasticsearch_client()
        index = self.params.get("index", "")
        query = self.params.get("query", {})
        results = await client.search(index, query)
        exchange.set_property(f"{self.op_name}_result", results)



# ── MongoDB (2) ────────────────────────────────────────────────────────


class MongoInsertProcessor(_InfraOp):
    """MongoDB INSERT документа (необратимо: нет meaningful compensation)."""

    op_name: ClassVar[str] = "mongo_insert"
    compensatable: ClassVar[bool] = False


class MongoFindProcessor(_InfraOp):
    """MongoDB FIND (read-only, результат в ``properties[to_property]``)."""

    op_name: ClassVar[str] = "mongo_find"
    compensatable: ClassVar[bool] = True


# ── S3 (S181 I-3.1) — phantom stubs REWIRED to real implementations ──


# Lazy import: real S3 processors from storage/s3.py
def _get_real_s3_delete_processor() -> type:
    """Lazy import real S3DeleteProcessor (S181 I-3.1).

    Previously :class:`S3DeleteProcessor` был phantom stub. Теперь
    rewire к :class:`src.backend.dsl.engine.processors.storage.s3.S3DeleteProcessor`.
    """
    from src.backend.dsl.engine.processors.storage.s3 import (
        S3DeleteProcessor as _RealS3Delete,
    )

    return _RealS3Delete


def _get_real_s3_list_processor() -> type:
    """Lazy import real S3ListProcessor (S181 I-3.1)."""
    from src.backend.dsl.engine.processors.storage.s3 import (
        S3ListProcessor as _RealS3List,
    )

    return _RealS3List


def _get_real_s3_presign_processor() -> type:
    """Lazy import real S3PresignProcessor (S181 I-3.1)."""
    from src.backend.dsl.engine.processors.storage.s3 import (
        S3PresignProcessor as _RealS3Presign,
    )

    return _RealS3Presign


class SftpGetProcessor(_InfraOp):
    """S104 W1 — SFTP GET processor (требует asyncssh)."""

    op_name: ClassVar[str] = "sftp_get"
    compensatable: ClassVar[bool] = False


class SftpPutProcessor(_InfraOp):
    """S104 W1 — SFTP PUT processor (требует asyncssh)."""

    op_name: ClassVar[str] = "sftp_put"
    compensatable: ClassVar[bool] = True


# ── SQL stub DELETED (S175 #5) — see infra_db.py for real impl ─────────


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
        self, key: str, value: str, *, ttl_seconds: int | None = None,
    ) -> RouteBuilder:
        """``SET key value [EX ttl]`` в Redis. ``ttl_seconds=None`` = бессрочно."""
        return self._add(  # type: ignore[attr-defined]
            RedisSetProcessor(key=key, value=value, ttl_seconds=ttl_seconds),
        )

    # NOTE: redis_get DELETED (S175 #5) — use InfraRedisGetProcessor.

    def redis_delete(self, key: str) -> RouteBuilder:
        """``DEL key`` в Redis."""
        return self._add(  # type: ignore[attr-defined]
            RedisDeleteProcessor(key=key),
        )

    # ── ClickHouse (2) ──

    def clickhouse_insert(
        self,
        table: str,
        *,
        batch_size: int = 1000,
        rows_from: str = "body",
    ) -> RouteBuilder:
        """Batch INSERT в ClickHouse ``table`` из exchange body.

        Cycle 29 P2:

        * ``rows_from`` (default ``"body"``) — dotted-path выражение
          exchange-property, откуда берётся ``list[dict]``.
        * ``batch_size`` (default 1000) — chunking пробрасывается в
          :meth:`ClickHouseClient.insert`, а не игнорируется.
        """
        return self._add(  # type: ignore[attr-defined]
            ClickHouseInsertProcessor(
                table=table, batch_size=batch_size, rows_from=rows_from,
            ),
        )

    # NOTE: clickhouse_query DELETED (S175 #5) — use InfraClickHouseQueryProcessor.

    # ── Elasticsearch (2) ──

    def es_index(self, index: str, *, doc_id_from: str | None = None) -> RouteBuilder:
        """Индексирует документ из body в ES ``index``.

        ``doc_id_from=None`` → ES auto-generates ``_id``.
        """
        return self._add(  # type: ignore[attr-defined]
            ElasticsearchIndexProcessor(index=index, doc_id_from=doc_id_from),
        )

    def es_search(self, index: str, query: dict, *, size: int = 10) -> RouteBuilder:
        """Поиск в ES; hits в ``exchange.properties["_es_hits"]``."""
        return self._add(  # type: ignore[attr-defined]
            ElasticsearchSearchProcessor(index=index, query=query, size=size),
        )

    # ── MongoDB (2) ──

    def mongo_insert(
        self, collection: str, *, document_from: str = "body",
    ) -> RouteBuilder:
        """INSERT документа в Mongo ``collection``."""
        return self._add(  # type: ignore[attr-defined]
            MongoInsertProcessor(collection=collection, document_from=document_from),
        )

    def mongo_find(
        self, collection: str, query: dict, *, to_property: str = "docs",
    ) -> RouteBuilder:
        """FIND документов в Mongo; результат в ``exchange.properties[to_property]``."""
        return self._add(  # type: ignore[attr-defined]
            MongoFindProcessor(
                collection=collection, query=query, to_property=to_property,
            ),
        )

    # ── S3 DELETED (S175 #5) — use ToS3Processor/FromS3Processor/S3PresignProcessor/ ──
    # ── S3DeleteProcessor/S3ListProcessor из ``storage/s3.py``. ──


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
            ),
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
            ),
        )

    # ── SQL (1) ──

    # NOTE: sql_exec DELETED (S175 #5) — use InfraDbQueryProcessor из infra_db.py.
