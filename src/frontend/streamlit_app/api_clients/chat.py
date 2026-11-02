"""Chat: AI chat endpoint (ai/llm/stream).

ADR-0422: клиент выровнен с роутером сервера (канон). Эндпоинта
``/api/v1/ai/chat`` не существует; сервер отдаёт SSE-поток
``POST /api/v1/ai/llm/stream`` (события ``start`` / ``token`` / ``done`` /
``error``). Клиент разбирает поток и склеивает дельты в текст ответа.
"""

from __future__ import annotations

import json
from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("ChatClient",)


class ChatClient(BaseAPIClient):
    """Клиент для AI chat endpoint (SSE-стрим ``/api/v1/ai/llm/stream``)."""

    def chat(self, message: str, session_id: str = "default") -> str:
        """Отправить сообщение в LLM и вернуть текст ответа.

        Args:
            message: Текст запроса пользователя.
            session_id: Идентификатор сессии (в контексте запроса сервер
                не принимает — оставлен для совместимости вызывающего кода).

        Returns:
            Текст ответа модели (склейка ``delta`` из SSE-событий ``token``).

        """
        result = self._request(
            "POST",
            "/api/v1/ai/llm/stream",
            json={"messages": [{"role": "user", "content": message}]},
        )
        if isinstance(result, dict):
            return str(result.get("response", result))
        return _parse_sse(str(result))


def _parse_sse(payload: str) -> str:
    """Собрать текст ответа из SSE-потока (``event: token`` → ``delta``).

    Если поток не содержит SSE-разметки (например, сервер вернул обычный
    текст), возвращается сам payload — клиент не теряет ответ.
    """
    chunks: list[str] = []
    seen_data = False
    for block in payload.split("\n\n"):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = line[len("data:") :].strip()
        if not data:
            continue
        seen_data = True
        try:
            parsed: Any = json.loads(data)
        except ValueError:
            continue
        if not isinstance(parsed, dict):
            continue
        if event == "error":
            return str(parsed.get("error", ""))
        delta = parsed.get("delta")
        if isinstance(delta, str):
            chunks.append(delta)
    if not seen_data:
        return payload.strip()
    return "".join(chunks)
