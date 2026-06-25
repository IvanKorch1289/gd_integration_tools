from __future__ import annotations

import os
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.services.ai.ai_providers.claude import ClaudeProvider
from src.backend.services.ai.ai_providers.gemini import GeminiProvider
from src.backend.services.ai.ai_providers.ollama import OllamaProvider
from src.backend.services.ai.ai_providers.minimax import MiniMaxProvider
from src.backend.services.ai.ai_providers.openai import OpenAIProvider

logger = get_logger("services.ai.ai_providers.helpers")


def register_extended_providers(agent: Any) -> int:
    """Регистрирует OpenAI/Claude/Gemini/Ollama в ``agent._providers``.

    Вызвать при startup после ``get_ai_agent_service()``. Каждый провайдер
    активируется только при наличии соответствующих env-переменных — никаких
    хардкод-умолчаний, никаких исключений при отсутствии ключей.

    Returns:
        Количество успешно зарегистрированных провайдеров.
    """
    registered = 0

    if os.environ.get("OPENAI_API_KEY"):
        openai_p = OpenAIProvider()
        agent._providers["openai"] = openai_p.chat
        agent._providers["gpt"] = openai_p.chat
        registered += 1

    if os.environ.get("ANTHROPIC_API_KEY"):
        claude = ClaudeProvider()
        agent._providers["anthropic"] = claude.chat
        agent._providers["claude"] = claude.chat
        registered += 1

    if os.environ.get("GEMINI_API_KEY"):
        gemini = GeminiProvider()
        agent._providers["gemini"] = gemini.chat
        agent._providers["google"] = gemini.chat
        registered += 1

    if (
        os.environ.get("OLLAMA_URL")
        or os.environ.get("OLLAMA_ENABLED", "").lower() == "true"
    ):
        ollama = OllamaProvider()
        agent._providers["ollama"] = ollama.chat

    if os.environ.get("MINIMAX_API_KEY"):
        minimax_p = MiniMaxProvider()
        agent._providers["minimax"] = minimax_p.chat
        registered += 1

    logger.info("Registered %d extended AI providers", registered)
    return registered
