"""LangFuse клиент — observability для LLM-вызовов.

Предоставляет трассировку и скоринг LLM-вызовов через LangFuse.
Интегрируется с LangChain через callbacks.
"""

import logging
from typing import Any

__all__ = ("LangFuseClient", "get_langfuse_client")

logger = logging.getLogger(__name__)


class LangFuseClient:
    """Клиент для LangFuse — мониторинг LLM-вызовов."""

    def __init__(self) -> None:
        self._client = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Инициализирует LangFuse-клиент при первом вызове."""
        if self._initialized:
            return

        try:
            from langfuse import Langfuse

            self._client = Langfuse()
            self._initialized = True
            logger.info("LangFuse клиент инициализирован")
        except ImportError:
            logger.warning("langfuse не установлен — observability отключена")
            self._initialized = True
        except Exception as exc:
            logger.error("LangFuse init error: %s", exc)
            self._initialized = True

    async def trace(
        self,
        name: str,
        input_data: Any = None,
        output_data: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Создаёт trace в LangFuse.

        Args:
            name: Имя трассировки.
            input_data: Входные данные.
            output_data: Результат.
            metadata: Дополнительные метаданные.

        Returns:
            ID трассировки или None.
        """
        self._ensure_initialized()
        if self._client is None:
            return None

        try:
            trace = self._client.trace(
                name=name, input=input_data, output=output_data, metadata=metadata or {}
            )
            return trace.id
        except Exception as exc:
            logger.error("LangFuse trace error: %s", exc)
            return None

    async def score(self, trace_id: str, name: str, value: float) -> None:
        """Добавляет оценку к трассировке.

        Args:
            trace_id: ID трассировки.
            name: Имя метрики.
            value: Значение (0.0-1.0).
        """
        self._ensure_initialized()
        if self._client is None:
            return

        try:
            self._client.score(trace_id=trace_id, name=name, value=value)
        except Exception as exc:
            logger.error("LangFuse score error: %s", exc)

    def get_langchain_handler(self) -> Any:
        """Возвращает LangChain callback handler для LangFuse."""
        self._ensure_initialized()
        if self._client is None:
            return None

        try:
            from langfuse.callback import CallbackHandler

            return CallbackHandler()
        except ImportError:
            return None


from src.backend.core.di import app_state_singleton


@app_state_singleton("langfuse_client", LangFuseClient)
def get_langfuse_client() -> LangFuseClient:
    """Возвращает LangFuseClient из app.state или lazy-init fallback."""
