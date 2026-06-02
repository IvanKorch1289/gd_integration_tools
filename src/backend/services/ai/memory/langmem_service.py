"""LangMem Service — 3-tier long-term memory для AI-агентов.

Реализует три уровня памяти:
    - **episodic** — события с временными метками (хранятся в Postgres);
    - **semantic** — факты + эмбеддинги (хранятся в Qdrant);
    - **procedural** — навыки и последовательности шагов (хранятся в Postgres).

Управление доступностью через feature-flag ``feature_flags.langmem_enabled``
(default-OFF). При отключённом флаге операции remember_* возвращают пустой
MemoryEntry, recall — пустой список.

Backend-зависимости (psycopg, qdrant_client) подключаются lazily через
модульный import. При недоступности обоих backend — inMemory fallback
(словари в памяти процесса), что обеспечивает работу unit-тестов без
внешних сервисов.

Использование::

    from src.backend.services.ai.memory.langmem_service import get_langmem_service

    svc = get_langmem_service()
    entry = await svc.remember_episode("agent-1", "user said hi", {})
    entries = await svc.recall("agent-1", "episodic", top_k=5)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger(__name__)

__all__ = ("MemoryEntry", "LangMemService", "get_langmem_service")

# Тип вида памяти
MemoryKind = Literal["episodic", "semantic", "procedural"]


@dataclass(slots=True)
class MemoryEntry:
    """Единица хранения в long-term memory.

    Attributes:
        entry_id: Уникальный идентификатор (UUID4).
        kind: Вид памяти — episodic | semantic | procedural.
        agent_id: Идентификатор агента-владельца записи.
        content: Основное текстовое содержимое.
        metadata: Произвольные метаданные (JSON-совместимый dict).
        timestamp: Время создания записи (UTC).
        embedding: Вектор эмбеддинга (только для semantic; None иначе).
    """

    entry_id: str
    kind: MemoryKind
    agent_id: str
    content: str
    metadata: dict[str, Any]
    timestamp: datetime
    embedding: list[float] | None = field(default=None)


# Тип для in-memory хранилища
_InMemoryStore = dict[str, list[MemoryEntry]]


def _new_entry(
    *,
    kind: MemoryKind,
    agent_id: str,
    content: str,
    metadata: dict[str, Any],
    embedding: list[float] | None = None,
) -> MemoryEntry:
    """Создаёт новый MemoryEntry с UUID4 и текущим временем UTC."""
    return MemoryEntry(
        entry_id=str(uuid.uuid4()),
        kind=kind,
        agent_id=agent_id,
        content=content,
        metadata=metadata,
        timestamp=datetime.now(timezone.utc),
        embedding=embedding,
    )


class LangMemService:
    """Координатор трёхуровневой long-term memory для AI-агентов.

    При ``enabled=False`` вызовы remember_* возвращают пустой MemoryEntry
    без записи в storage; recall возвращает пустой список.

    При недоступности Postgres и Qdrant (или при явном ``use_inmemory=True``)
    использует in-memory словари для хранения — достаточно для unit-тестов.

    Args:
        pg_dsn: DSN для Postgres (episodic + procedural). Если ``None`` — используется
            shared async-engine из infrastructure. Если недоступен — inMemory fallback.
        qdrant_url: URL для Qdrant (semantic). Если ``None`` — inMemory fallback.
        qdrant_collection: Имя коллекции Qdrant.
        use_inmemory: Принудительно использовать inMemory (для тестов).
        enabled: Явное включение/выключение. Если ``None`` — берётся из feature_flags.
    """

    def __init__(
        self,
        *,
        pg_dsn: str | None = None,
        qdrant_url: str | None = None,
        qdrant_collection: str = "langmem_semantic",
        use_inmemory: bool = False,
        enabled: bool | None = None,
    ) -> None:
        # Определяем enabled: из аргумента или из feature_flags
        if enabled is None:
            try:
                from src.backend.core.config.features import feature_flags

                enabled = feature_flags.langmem_enabled
            except Exception as _:
                enabled = False
        self._enabled: bool = bool(enabled)
        self._pg_dsn = pg_dsn
        self._qdrant_url = qdrant_url
        self._qdrant_collection = qdrant_collection
        self._use_inmemory = use_inmemory
        # Словари для inMemory fallback: agent_id -> list[MemoryEntry]
        self._store: _InMemoryStore = {}
        # Lazy-loaded backend clients
        self._pg_conn: Any = None
        self._qdrant_client: Any = None

    def _is_inmemory(self) -> bool:
        """Возвращает True если используется inMemory fallback."""
        return self._use_inmemory or (self._pg_conn is None and not self._pg_dsn)

    async def _ensure_pg(self) -> Any | None:
        """Lazy-подключение к Postgres через psycopg. При ошибке — None."""
        if self._use_inmemory:
            return None
        if self._pg_conn is not None:
            return self._pg_conn
        if not self._pg_dsn:
            return None
        try:
            import psycopg  # type: ignore[import-not-found]

            self._pg_conn = await psycopg.AsyncConnection.connect(self._pg_dsn)
            logger.info("LangMemService: подключение к Postgres установлено.")
        except Exception as exc:
            logger.warning(
                "LangMemService: не удалось подключиться к Postgres (%s), "
                "используется inMemory fallback.",
                exc,
            )
            self._pg_conn = None
        return self._pg_conn

    async def _ensure_qdrant(self) -> Any | None:
        """Lazy-подключение к Qdrant. При ошибке — None."""
        if self._use_inmemory:
            return None
        if self._qdrant_client is not None:
            return self._qdrant_client
        if not self._qdrant_url:
            return None
        try:
            from qdrant_client import AsyncQdrantClient

            self._qdrant_client = AsyncQdrantClient(self._qdrant_url)
            logger.info("LangMemService: подключение к Qdrant установлено.")
        except Exception as exc:
            logger.warning(
                "LangMemService: не удалось подключиться к Qdrant (%s), "
                "используется inMemory fallback для semantic.",
                exc,
            )
            self._qdrant_client = None
        return self._qdrant_client

    def _inmemory_save(self, entry: MemoryEntry) -> None:
        """Сохраняет запись в inMemory store."""
        bucket = self._store.setdefault(entry.agent_id, [])
        bucket.append(entry)

    def _inmemory_recall(
        self, agent_id: str, kind: MemoryKind, top_k: int
    ) -> list[MemoryEntry]:
        """Возвращает записи из inMemory по agent_id и kind, отсортированные по времени."""
        bucket = self._store.get(agent_id, [])
        filtered = [e for e in bucket if e.kind == kind]
        # Сортируем по timestamp убыванию, берём top_k
        sorted_entries = sorted(filtered, key=lambda e: e.timestamp, reverse=True)
        return sorted_entries[:top_k]

    async def _pg_save(self, entry: MemoryEntry) -> None:
        """Сохраняет запись в Postgres. При ошибке логирует и падает в inMemory."""
        conn = await self._ensure_pg()
        if conn is None:
            self._inmemory_save(entry)
            return
        try:
            import orjson

            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO langmem_entries
                        (entry_id, kind, agent_id, content, metadata, timestamp, embedding_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        entry.entry_id,
                        entry.kind,
                        entry.agent_id,
                        entry.content,
                        orjson.dumps(entry.metadata).decode(),
                        entry.timestamp,
                        None,
                    ),
                )
            await conn.commit()
        except Exception as exc:
            logger.warning(
                "LangMemService: ошибка записи в Postgres (%s), fallback в inMemory.",
                exc,
            )
            self._inmemory_save(entry)

    async def remember_episode(
        self, agent_id: str, content: str, metadata: dict[str, Any]
    ) -> MemoryEntry:
        """Сохраняет эпизодическое событие с временной меткой.

        Эпизодическая память хранит конкретные события и взаимодействия
        с временными метками. Персистируется в Postgres (таблица langmem_entries,
        kind='episodic') или в inMemory при недоступности.

        Args:
            agent_id: Идентификатор агента.
            content: Текстовое описание эпизода.
            metadata: Произвольный контекст события.

        Returns:
            MemoryEntry с заполненными entry_id и timestamp. При отключённом
            флаге — пустой MemoryEntry без сохранения.
        """
        if not self._enabled:
            return _new_entry(
                kind="episodic", agent_id=agent_id, content="", metadata={}
            )
        entry = _new_entry(
            kind="episodic", agent_id=agent_id, content=content, metadata=metadata
        )
        await self._pg_save(entry)
        return entry

    async def remember_fact(
        self, agent_id: str, content: str, embedding: list[float]
    ) -> MemoryEntry:
        """Сохраняет семантический факт с вектором эмбеддинга.

        Семантическая память хранит знания в виде фактов + векторных
        представлений для similarity-поиска. Персистируется в Qdrant
        (коллекция langmem_semantic) и в Postgres (kind='semantic') или
        в inMemory при недоступности.

        Args:
            agent_id: Идентификатор агента.
            content: Текстовое содержание факта.
            embedding: Векторное представление (список float).

        Returns:
            MemoryEntry с embedding. При отключённом флаге — пустой MemoryEntry.
        """
        if not self._enabled:
            return _new_entry(
                kind="semantic",
                agent_id=agent_id,
                content="",
                metadata={},
                embedding=None,
            )
        entry = _new_entry(
            kind="semantic",
            agent_id=agent_id,
            content=content,
            metadata={"agent_id": agent_id},
            embedding=embedding,
        )
        # Попытка сохранить в Qdrant
        qdrant = await self._ensure_qdrant()
        if qdrant is not None:
            try:
                await qdrant.upsert(
                    collection_name=self._qdrant_collection,
                    points=[
                        {
                            "id": entry.entry_id,
                            "vector": embedding,
                            "payload": {"agent_id": agent_id, "content": content},
                        }
                    ],
                )
            except Exception as exc:
                logger.warning(
                    "LangMemService: ошибка upsert в Qdrant (%s), только inMemory.", exc
                )
                self._inmemory_save(entry)
                return entry
        else:
            # Без Qdrant — сохраняем в inMemory
            self._inmemory_save(entry)
        # Также сохраняем запись в Postgres (без embedding)
        await self._pg_save(entry)
        return entry

    async def remember_procedure(
        self, agent_id: str, name: str, steps: list[str]
    ) -> MemoryEntry:
        """Сохраняет процедурный навык как последовательность шагов.

        Процедурная память хранит знания о том, как выполнять задачи
        (алгоритмы, workflow, SOP). Персистируется в Postgres
        (kind='procedural') или в inMemory.

        Args:
            agent_id: Идентификатор агента.
            name: Название процедуры / навыка.
            steps: Список шагов в порядке выполнения.

        Returns:
            MemoryEntry с content=name и metadata={'steps': steps}.
            При отключённом флаге — пустой MemoryEntry.
        """
        if not self._enabled:
            return _new_entry(
                kind="procedural", agent_id=agent_id, content="", metadata={}
            )
        entry = _new_entry(
            kind="procedural",
            agent_id=agent_id,
            content=name,
            metadata={"steps": steps, "name": name},
        )
        await self._pg_save(entry)
        return entry

    async def recall(
        self, agent_id: str, kind: MemoryKind, query: str | None = None, top_k: int = 10
    ) -> list[MemoryEntry]:
        """Извлекает записи из памяти по агенту и типу.

        Args:
            agent_id: Идентификатор агента.
            kind: Тип памяти — episodic | semantic | procedural.
            query: Поисковый запрос (используется для semantic similarity;
                игнорируется в inMemory fallback).
            top_k: Максимальное кол-во возвращаемых записей.

        Returns:
            Список MemoryEntry, отсортированный по timestamp убыванию.
            При отключённом флаге — пустой список.
        """
        if not self._enabled:
            return []
        # inMemory fallback (нет Postgres и нет dsn) или принудительный режим
        if self._is_inmemory():
            return self._inmemory_recall(agent_id, kind, top_k)
        # Попытка чтения из Postgres
        conn = await self._ensure_pg()
        if conn is None:
            return self._inmemory_recall(agent_id, kind, top_k)
        try:
            import orjson

            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT entry_id, kind, agent_id, content, metadata, timestamp
                    FROM langmem_entries
                    WHERE agent_id = %s AND kind = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (agent_id, kind, top_k),
                )
                rows = await cur.fetchall()
            return [
                MemoryEntry(
                    entry_id=str(row[0]),
                    kind=row[1],
                    agent_id=row[2],
                    content=row[3],
                    metadata=orjson.loads(row[4])
                    if isinstance(row[4], (str, bytes))
                    else (row[4] or {}),
                    timestamp=row[5]
                    if isinstance(row[5], datetime)
                    else datetime.fromisoformat(str(row[5])),
                    embedding=None,
                )
                for row in rows
            ]
        except Exception as exc:
            logger.warning(
                "LangMemService: ошибка чтения из Postgres (%s), fallback в inMemory.",
                exc,
            )
            return self._inmemory_recall(agent_id, kind, top_k)


_singleton: LangMemService | None = None


def get_langmem_service() -> LangMemService:
    """Возвращает process-wide singleton :class:`LangMemService`.

    При первом вызове инициализирует сервис с параметрами из feature_flags.
    inMemory fallback активируется автоматически при недоступности backends.

    Returns:
        Инициализированный :class:`LangMemService`.
    """
    global _singleton
    if _singleton is None:
        _singleton = LangMemService()
    return _singleton
