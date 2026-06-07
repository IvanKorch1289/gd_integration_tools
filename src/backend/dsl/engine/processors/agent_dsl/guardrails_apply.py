"""GuardrailsApplyProcessor — content safety через :class:`LlamaGuardRuntime` (S27 W2).

Декларативный шаг проверки prompt'а / completion'а через Llama Guard 3
(:mod:`core.ai.guardrails.llamaguard`). Поддерживает 3 политики при unsafe:

* ``"dlq"`` — отправить в DLQ через ``exchange.set_property("dlq", ...)`` + stop;
* ``"fail"`` — установить error и остановить exchange;
* ``"warn"`` — записать verdict в ``properties["guardrails_verdict"]``,
  pipeline продолжается.

YAML контракт::

    steps:
      - guardrails_apply:
          stage: input
          source_property: body
          on_block: fail
          categories: ["hate", "violence"]

Python контракт::

    builder.guardrails_apply(
        stage="output",
        source_property="agent_result.content",
        on_block="warn",
    )
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from typing import TYPE_CHECKING, Any, ClassVar, Literal

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("GuardrailsApplyProcessor",)

_logger = get_logger(__name__)

_StageLiteral = Literal["input", "output"]
_OnBlockLiteral = Literal["dlq", "fail", "warn"]


class GuardrailsApplyProcessor(BaseAIProcessor):
    """Применить Llama Guard к input или output stage'у agent pipeline'а.

    Args:
        stage: ``"input"`` — проверить prompt (по ``source_property``,
            default ``"body"``); ``"output"`` — проверить completion
            (по ``source_property``, default ``"agent_result.content"``).
        source_property: Dot-path к тексту для проверки. Default
            зависит от ``stage`` (см. выше).
        on_block: Политика при ``unsafe``: ``"dlq"`` / ``"fail"`` / ``"warn"``.
        categories: Опц. список категорий Llama Guard
            (``"hate"`` / ``"violence"`` / ``"sexual"`` / ``"unsafe"``).
            ``None`` = DEFAULT_CATEGORIES от LlamaGuardRuntime.
        name: Имя процессора.

    Notes:
        При недоступности :class:`LlamaGuardRuntime` (lazy-import упал или
        runtime ``None``) — silent pass-through + WARNING лог. Это нужно
        чтобы CI/dev окружения без llama-cpp-python не падали на DSL-routes.
    """

    audit_event: ClassVar[str | None] = "ai.guardrails.apply"

    def __init__(
        self,
        *,
        stage: _StageLiteral = "input",
        source_property: str | None = None,
        on_block: _OnBlockLiteral = "warn",
        categories: list[str] | None = None,
        name: str | None = None,
    ) -> None:
        if stage not in ("input", "output"):
            raise ValueError(
                f"GuardrailsApplyProcessor: stage must be 'input'|'output', "
                f"got {stage!r}"
            )
        if on_block not in ("dlq", "fail", "warn"):
            raise ValueError(
                f"GuardrailsApplyProcessor: on_block must be "
                f"'dlq'|'fail'|'warn', got {on_block!r}"
            )
        super().__init__(name=name or f"guardrails_apply:{stage}")
        self.stage = stage
        self.source_property = source_property or (
            "body" if stage == "input" else "agent_result.content"
        )
        self.on_block = on_block
        self.categories = list(categories) if categories else None

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        del context
        text = self._extract_text(exchange)
        if not text:
            return

        runtime = self._resolve_runtime()
        if runtime is None:
            _logger.warning(
                "%s: LlamaGuardRuntime недоступен — pass-through", self.name
            )
            return

        try:
            result = await runtime.classify(text, categories=self.categories)
        except Exception as exc:
            _logger.warning("%s: classify failed (%s) — pass-through", self.name, exc)
            return

        verdict = {
            "safe": bool(getattr(result, "safe", True)),
            "flagged_categories": list(getattr(result, "flagged_categories", []) or []),
            "stage": self.stage,
        }
        existing = exchange.get_property("guardrails_verdict")
        if isinstance(existing, dict):
            merged = dict(existing)
            merged[self.stage] = verdict
            exchange.set_property("guardrails_verdict", merged)
        else:
            exchange.set_property("guardrails_verdict", {self.stage: verdict})

        if verdict["safe"]:
            return

        # Unsafe — apply on_block policy.
        if self.on_block == "fail":
            exchange.set_error(
                f"{self.name}: blocked by Llama Guard "
                f"(stage={self.stage}, "
                f"categories={verdict['flagged_categories']})"
            )
            exchange.stop()
            return
        if self.on_block == "dlq":
            exchange.set_property(
                "dlq_reason",
                {
                    "processor": self.name,
                    "stage": self.stage,
                    "flagged_categories": verdict["flagged_categories"],
                },
            )
            exchange.stop()
            return
        # on_block == "warn" — verdict уже записан, pipeline продолжается.

    def _extract_text(self, exchange: Exchange[Any]) -> str:
        """Достать текст из exchange по ``source_property`` (dot-path)."""
        parts = self.source_property.split(".")
        head = parts[0]
        if head == "body":
            cursor: Any = exchange.in_message.body
            for part in parts[1:]:
                if cursor is None:
                    return ""
                cursor = (
                    cursor.get(part)
                    if isinstance(cursor, dict)
                    else getattr(cursor, part, None)
                )
            return str(cursor) if cursor is not None else ""

        cursor = exchange.get_property(head)
        for part in parts[1:]:
            if cursor is None:
                return ""
            cursor = (
                cursor.get(part)
                if isinstance(cursor, dict)
                else getattr(cursor, part, None)
            )
        return str(cursor) if cursor is not None else ""

    @staticmethod
    def _resolve_runtime() -> Any | None:
        """Lazy-резолв :class:`LlamaGuardRuntime` (S24 W2 partial)."""
        try:
            from src.backend.core.di.container import get_container

            container = get_container()
            if container is not None:
                runtime = container.resolve_optional("llama_guard_runtime")
                if runtime is not None:
                    return runtime
        except Exception as exc:
            _logger.debug("DI container resolve failed: %s", exc)
        return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {"stage": self.stage, "on_block": self.on_block}
        # Записываем source_property только если он отличается от default
        default_source = "body" if self.stage == "input" else "agent_result.content"
        if self.source_property != default_source:
            spec["source_property"] = self.source_property
        if self.categories is not None:
            spec["categories"] = list(self.categories)
        return {"guardrails_apply": spec}
