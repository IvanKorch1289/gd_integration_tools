"""Auto-generated from ai_processors.py — single processor files."""
from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

class GetFeedbackExamplesProcessor(BaseProcessor):
    """Достаёт примеры из AI Feedback RAG для few-shot prompting.

    Ищет похожие размеченные ответы агентов в RAG-индексе с
    фильтрацией по метке оператора: отдельно ``positive`` (как
    пример хороших ответов) и ``negative`` (примеры ответов,
    которых следует избегать). Результат складывается в
    ``exchange.properties[inject_as]`` в формате::

        {
          "positive": [{"query": "...", "response": "..."}, ...],
          "negative": [{"query": "...", "response": "..."}, ...],
        }

    Используется как шаг перед ``LLMCallProcessor`` / шаблонизацией
    промпта агента.

    Пример DSL YAML::

        - kind: get_feedback_examples
          config:
            query_from: body.query
            agent_id: risk_assessor
            positive_k: 3
            negative_k: 2
            min_similarity: 0.75
            inject_as: feedback_examples
    """

    _NAMESPACE = "ai_feedback"

    def __init__(
        self,
        *,
        query_from: str = "body.query",
        agent_id: str | None = None,
        positive_k: int = 3,
        negative_k: int = 2,
        min_similarity: float = 0.0,
        inject_as: str = "feedback_examples",
        name: str | None = None,
    ) -> None:
        """Инициализирует процессор.

        Args:
            query_from: Путь к тексту запроса в exchange
                (``body.<field>`` или ``property:<name>``).
            agent_id: Фильтрация примеров по агенту (только если
                ``metadata.agent_id`` совпадает).
            positive_k: Сколько положительных примеров брать.
            negative_k: Сколько отрицательных примеров брать.
            min_similarity: Минимальный порог сходства (0..1).
            inject_as: Ключ в ``exchange.properties`` для результата.
            name: Имя процессора для трейсов/метрик.
        """
        super().__init__(name or "get_feedback_examples")
        self._query_from = query_from
        self._agent_id = agent_id
        self._positive_k = max(0, positive_k)
        self._negative_k = max(0, negative_k)
        self._min_similarity = min_similarity
        self._inject_as = inject_as

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет поиск feedback-примеров и помещает их в properties."""
        query = self._extract_query(exchange)
        if not query:
            exchange.set_property(self._inject_as, {"positive": [], "negative": []})
            return

        positive = await self._search(query, "positive", self._positive_k)
        negative = await self._search(query, "negative", self._negative_k)
        exchange.set_property(
            self._inject_as, {"positive": positive, "negative": negative}
        )

    def _extract_query(self, exchange: Exchange[Any]) -> str:
        """Извлекает query-текст из exchange по пути ``query_from``.

        Args:
            exchange: Текущий exchange.

        Returns:
            Строковое представление запроса.
        """
        path = self._query_from
        body = exchange.in_message.body
        if path.startswith("property:"):
            return str(exchange.properties.get(path.split(":", 1)[1], "") or "")
        if path.startswith("body."):
            field = path.split(".", 1)[1]
            if isinstance(body, dict):
                return str(body.get(field, "") or "")
            return str(body or "")
        if path == "body":
            return str(body or "")
        if isinstance(body, dict) and path in body:
            return str(body[path] or "")
        return str(body or "")

    async def _search(self, query: str, label: str, top_k: int) -> list[dict[str, str]]:
        """Ищет примеры по метке и формирует пары ``{query, response}``.

        Args:
            query: Запрос пользователя.
            label: ``positive`` / ``negative``.
            top_k: Сколько примеров запрашивать.

        Returns:
            Список пар (может быть пустым при отсутствии RAG-данных).
        """
        if top_k <= 0:
            return []
        try:
            from src.backend.services.ai.rag_service import get_rag_service

            rag = get_rag_service()
            results = await rag.search(
                query=query, top_k=top_k * 2, namespace=self._NAMESPACE
            )
        except Exception as _:
            return []

        examples: list[dict[str, str]] = []
        for row in results or []:
            metadata = row.get("metadata") or {}
            if metadata.get("source") != "ai_feedback":
                continue
            if metadata.get("label") != label:
                continue
            if self._agent_id and metadata.get("agent_id") != self._agent_id:
                continue
            score = float(row.get("score") or row.get("similarity") or 0.0)
            if score < self._min_similarity:
                continue
            examples.append(self._parse_example(row.get("document", "")))
            if len(examples) >= top_k:
                break
        return examples

    @staticmethod
    def _parse_example(content: str) -> dict[str, str]:
        """Парсит чанк вида ``Q: ...\\nA: ...`` в словарь.

        Args:
            content: Текст чанка из RAG-store.

        Returns:
            ``{"query": str, "response": str}``.
        """
        q_part = ""
        a_part = ""
        if content.startswith("Q:"):
            parts = content.split("\nA:", 1)
            q_part = parts[0][2:].strip()
            if len(parts) == 2:
                a_part = parts[1].strip()
        else:
            a_part = content.strip()
        return {"query": q_part, "response": a_part}
