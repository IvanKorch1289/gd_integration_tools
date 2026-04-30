"""Протоколы для AI-клиентов и зависимостей services/ai/.

Wave 6.3: вынесено для устранения layer-violations в services/ai/*,
которые ранее напрямую импортировали ``infrastructure.*``.

Контракты описывают только публичную поверхность, нужную AI-сервисам:
* :class:`HttpClientProtocol` — HTTP-вызов внешних провайдеров (Perplexity,
  HuggingFace, OpenWebUI), реализован в
  ``infrastructure.clients.transport.http.HttpClient``.
* :class:`AISanitizerProtocol` — маскирование PII перед отправкой в LLM,
  реализован в ``infrastructure.security.ai_sanitizer.AIDataSanitizer``.
* :class:`MongoClientProtocol` — persistence слой agent memory,
  реализован в ``infrastructure.clients.storage.mongodb.MongoDBClient``.
* :class:`RedisStreamClientProtocol` — async Redis stream/get/set,
  реализован в ``infrastructure.clients.storage.redis.RedisClient``.
* :class:`LLMJudgeMetricsProtocol` — публикация LLM-judge метрик,
  реализован в ``infrastructure.observability.metrics``.

Все Protocol помечены ``@runtime_checkable``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = (
    "HttpClientProtocol",
    "AISanitizerProtocol",
    "MongoClientProtocol",
    "RedisStreamClientProtocol",
    "LLMJudgeMetricsProtocol",
)


@runtime_checkable
class HttpClientProtocol(Protocol):
    """Контракт async HTTP-клиента для внешних AI-провайдеров.

    Реализация: ``infrastructure.clients.transport.http.HttpClient``.
    """

    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: Any | None = None,
        connect_timeout: float | None = None,
        read_timeout: float | None = None,
        total_timeout: float | None = None,
        **kwargs: Any,
    ) -> Any:
        """Выполняет HTTP-запрос и возвращает разобранный ответ."""
        ...


@runtime_checkable
class AISanitizerProtocol(Protocol):
    """Контракт маскировщика PII перед отправкой в LLM.

    Реализация: ``infrastructure.security.ai_sanitizer.AIDataSanitizer``.
    """

    def sanitize_text(self, text: str) -> Any:
        """Маскирует PII в тексте, возвращает SanitizationResult."""
        ...

    def sanitize_messages(
        self, messages: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], dict[str, str]]:
        """Маскирует PII в списке chat-сообщений."""
        ...

    @staticmethod
    def restore_text(text: str, mapping: dict[str, str]) -> str:
        """Восстанавливает оригинальные значения по mapping."""
        ...


@runtime_checkable
class MongoClientProtocol(Protocol):
    """Контракт async MongoDB-клиента для agent memory.

    Реализация: ``infrastructure.clients.storage.mongodb.MongoDBClient``.
    """

    def collection(self, name: str) -> Any: ...

    async def find(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        projection: dict[str, Any] | None = None,
        limit: int | None = None,
        skip: int | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]: ...

    async def find_one(
        self, collection: str, query: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    async def insert_one(self, collection: str, document: dict[str, Any]) -> str: ...

    async def update_one(
        self,
        collection: str,
        query: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> int: ...

    async def delete_one(self, collection: str, query: dict[str, Any]) -> int: ...

    async def count(
        self, collection: str, query: dict[str, Any] | None = None
    ) -> int: ...


@runtime_checkable
class RedisStreamClientProtocol(Protocol):
    """Контракт Redis-клиента для LLM-judge / semantic-cache.

    Реализация: ``infrastructure.clients.storage.redis.RedisClient``
    (singleton ``redis_client``).
    """

    async def add_to_stream(
        self, stream_name: str, data: dict[str, Any]
    ) -> Any: ...

    async def read_stream(
        self, stream_name: str, count: int = 50
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class LLMJudgeMetricsProtocol(Protocol):
    """Контракт публикации LLM-judge метрик.

    Реализация: ``infrastructure.observability.metrics.record_llm_judge``.
    """

    def __call__(
        self,
        *,
        model: str,
        hallucination: float,
        relevance: float,
        toxicity: float,
    ) -> None: ...
