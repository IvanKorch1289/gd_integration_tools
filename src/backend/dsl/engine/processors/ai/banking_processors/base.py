from __future__ import annotations

"""S59 W1 — base.py part of banking_processors decomp.

Classes: _BankingAIProcessor.

_BankingAIProcessor (5 methods, base for all processors).
"""

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.processors.ai.banking")

# ─── Pydantic schemas for structured output ─────────────────────────────────


class _BankingAIProcessor(BaseProcessor):
    """Base for banking AI processors — общая логика LLM-вызова."""

    # Override in subclass
    ResultSchema: type[BaseModel] = BaseModel
    prompt_template: str = ""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self, model: str = "anthropic/claude-sonnet-4-6", *, name: str | None = None
    ) -> None:
        super().__init__(name=name or self.__class__.__name__)
        if not model or "/" not in model:
            raise ValueError(
                f"{self.__class__.__name__}: model должен быть в формате "
                f"'<provider>/<name>', получено {model!r}"
            )
        self._model = model
        self._provider = model.split("/", 1)[0]

    def _build_prompt(self, exchange: "Exchange[Any]") -> str:
        """Строит prompt из шаблона с подстановкой ${body.field}."""
        body = exchange.in_message.body
        body_dict = body if isinstance(body, dict) else {"_raw": body}

        import re

        pattern = re.compile(r"\$\{([^}]+)\}")

        def _replace(match: "re.Match[str]") -> str:
            path = match.group(1).strip()
            if path == "body":
                return str(body)
            if path.startswith("body."):
                key = path[len("body.") :]
                return str(body_dict.get(key, ""))
            if path.startswith("properties."):
                key = path[len("properties.") :]
                return str(exchange.properties.get(key, ""))
            return match.group(0)

        return pattern.sub(_replace, self.prompt_template)

    def _write_result(self, exchange: "Exchange[Any]", result: BaseModel) -> None:
        """Пишет Pydantic-результат в body.<field>."""
        field_name = self.__class__.__name__.replace("Processor", "").lower()
        body = exchange.in_message.body
        if not isinstance(body, dict):
            body = {}
        body[field_name] = result.model_dump()
        exchange.in_message.body = body

    @handle_processor_error
    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        # Feature gate
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.banking_ai_processors_enabled:
                exchange.set_property(f"{self.name}_status", "skipped")
                return
        except Exception:  # noqa: BLE001
            pass

        prompt = self._build_prompt(exchange)

        try:
            import instructor  # type: ignore[import-not-found]
            import litellm  # type: ignore[import-not-found]
        except ImportError as exc:
            exchange.fail(
                f"{self.name}: instructor/litellm не установлены; "
                f"добавьте extras 'ai-2026' (uv sync --extra ai-2026): {exc}"
            )
            return

        from src.backend.infrastructure.resilience.retry import make_async_retry

        client = instructor.from_litellm(litellm.acompletion)

        @make_async_retry(
            max_attempts=2,
            initial_backoff=1.0,
            multiplier=2.0,
            on=(ConnectionError, TimeoutError),
        )
        async def _call() -> BaseModel:
            return await client.create(
                model=self._model,
                response_model=self.ResultSchema,
                messages=[{"role": "user", "content": prompt}],
                max_retries=3,
                temperature=0.0,
            )

        try:
            result = await _call()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "%s failed: model=%s provider=%s error=%s",
                self.name,
                self._model,
                self._provider,
                exc,
            )
            exchange.fail(f"{self.name} failed: {exc}")
            return

        # Cost tracking
        exchange.set_property("llm.provider", self._provider)
        exchange.set_property("llm.model", self._model)
        exchange.set_property(
            "banking_action", f"ai.banking.{self.name.lower().replace('processor', '')}"
        )

        self._write_result(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        return {
            self.__class__.__name__.lower().replace("processor", "_ai"): {
                "model": self._model
            }
        }
