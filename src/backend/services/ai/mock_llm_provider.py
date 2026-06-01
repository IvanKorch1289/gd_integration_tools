"""MockLLMProvider — детерминированный LLM-провайдер для dry-run/тестов (S10 K4 W1).

Цель: позволять выполнять AI workflow в dry-run / unit / integration
тестах без реальных API-вызовов. Гарантии:

* нет сетевых вызовов;
* cost = 0 (token_usage = 0);
* ответ детерминирован (хеш от prompt'а как seed);
* support tools (function calling) — возвращает первый tool и заранее
  определённые arguments;
* embeddings: BGE-M3 dim=1024 — нулевой вектор (для consistency).

Использование в тестах::

    from src.backend.services.ai.mock_llm_provider import MockLLMProvider

    provider = MockLLMProvider(canned_response="OK")
    resp = await provider.chat([{"role": "user", "content": "x"}])
    assert resp["content"][0]["text"] == "OK"

Использование в dry-run workflow::

    if settings.ai.dry_run:
        provider = MockLLMProvider()
    else:
        provider = ClaudeProvider(...)
"""

from __future__ import annotations

import hashlib
from typing import Any

__all__ = ("MockLLMProvider",)


class MockLLMProvider:
    """In-memory LLM provider c детерминированным выводом.

    Attributes:
        name: "mock-llm".
        canned_response: явный текст ответа (если None — генерится из prompt).
        tool_arguments: предзаданные args для tool_use (если tools=…).
    """

    name = "mock-llm"

    def __init__(
        self,
        *,
        canned_response: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        embedding_dim: int = 1024,
    ) -> None:
        """Инициализирует mock с опциональным каноничным ответом.

        Args:
            canned_response: если задан, всегда возвращается как content[0].text;
                иначе текст детерминированно генерится из prompt-hash.
            tool_arguments: args для первого tool_use (если в payload tools=…).
            embedding_dim: размерность ноль-вектора для embeddings (default 1024).
        """
        self.canned_response = canned_response
        self.tool_arguments = tool_arguments or {}
        self.embedding_dim = embedding_dim

    def extract_text(self, response: dict[str, Any]) -> str:
        """Совместимый с :class:`ClaudeProvider` интерфейс."""
        blocks = response.get("content", [])
        if blocks and isinstance(blocks, list):
            first = blocks[0]
            if isinstance(first, dict):
                return first.get("text", "")
        return ""

    @staticmethod
    def _digest(messages: list[dict[str, Any]]) -> str:
        """Stable hash от сериализованного prompt-payload."""
        joined = "\n".join(
            f"{m.get('role', '')}|{m.get('content', '')}" for m in messages
        )
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Возвращает детерминированный ответ-эмуляцию Claude-формата.

        Args:
            messages: список prompt-сообщений (role/content).
            model: игнорируется (mock не использует реальную модель).
            max_tokens: игнорируется (cost = 0).
            temperature: игнорируется (детерминизм).
            tools: если задано — содержит ≥1 tool, генерится tool_use block.
            stream: игнорируется (mock возвращает полный ответ).

        Returns:
            Dict с ключами ``id``, ``content``, ``model``, ``usage``.
        """
        digest = self._digest(messages)
        if tools:
            first_tool = tools[0]
            tool_name = first_tool.get("name", "mock_tool")
            content_blocks: list[dict[str, Any]] = [
                {
                    "type": "tool_use",
                    "id": f"toolu_mock_{digest[:8]}",
                    "name": tool_name,
                    "input": dict(self.tool_arguments),
                }
            ]
        else:
            text = self.canned_response or f"[mock-llm] echo for digest={digest}"
            content_blocks = [{"type": "text", "text": text}]

        return {
            "id": f"msg_mock_{digest}",
            "type": "message",
            "role": "assistant",
            "content": content_blocks,
            "model": model or "mock-llm-1.0",
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    async def embeddings(
        self, texts: list[str], *, model: str | None = None
    ) -> list[list[float]]:
        """Возвращает ноль-векторы согласованной размерности (mock-only)."""
        return [[0.0] * self.embedding_dim for _ in texts]
