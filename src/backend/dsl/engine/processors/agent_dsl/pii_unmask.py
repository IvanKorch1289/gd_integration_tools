"""PIIUnmaskProcessor — обратная операция к :class:`PIIMaskProcessor` (S27 W2).

Восстанавливает оригинальный PII из ``exchange.properties["pii_token_map"]``
+ masked text. Требует ``token_map`` в exchange — иначе raise (если
``strict=True``) или pass-through (если ``strict=False``).

YAML контракт::

    steps:
      - pii_mask: { scope: banking }
      - agent_run: { workflow_id: credit_check, prompt_inline: "..." }
      - pii_unmask: { source_property: agent_result.content, strict: true }
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("PIIUnmaskProcessor",)

_logger = logging.getLogger(__name__)


class PIIUnmaskProcessor(BaseAIProcessor):
    """Восстановить PII из ``token_map`` (round-trip к ``pii_mask``).

    Args:
        source_property: Откуда взять masked-текст. Default ``"body"``.
        target_property: Куда записать восстановленный текст. Default
            совпадает с ``source_property``.
        token_map_property: Где искать ``TokenMap``. Default
            ``"pii_token_map"`` (выставляется :class:`PIIMaskProcessor`).
        strict: При ``True`` — raise если ``token_map`` отсутствует.
            При ``False`` — silent pass-through.
        name: Имя процессора.
    """

    required_capability: ClassVar[str | None] = "pii.tokenize.reversible"
    audit_event: ClassVar[str | None] = "ai.pii.unmask"

    def __init__(
        self,
        *,
        source_property: str = "body",
        target_property: str | None = None,
        token_map_property: str = "pii_token_map",  # noqa: S107  # config field name, not a password
        scope: str = "default",
        strict: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "pii_unmask")
        self.source_property = source_property
        self.target_property = target_property or source_property
        self.token_map_property = token_map_property
        self.scope = scope
        self.strict = strict

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        del exchange
        return self.scope

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        del context
        token_map = exchange.get_property(self.token_map_property)
        if token_map is None:
            if self.strict:
                exchange.set_error(
                    f"{self.name}: "
                    f"token_map отсутствует в exchange.properties[{self.token_map_property!r}]"
                )
                exchange.stop()
                return
            _logger.debug("%s: token_map=None и strict=False — pass-through", self.name)
            return

        text = self._extract_text(exchange)
        if not text:
            return

        tokenizer = self._resolve_tokenizer()
        if tokenizer is None:
            _logger.warning("%s: PIITokenizer недоступен — pass-through", self.name)
            return

        try:
            unmasked = await tokenizer.unmask(text, token_map)
        except Exception as exc:
            _logger.warning("%s: unmask failed (%s) — pass-through", self.name, exc)
            return

        unmasked_text = self._extract_unmasked_text(unmasked, fallback=text)
        self._write_target(exchange, unmasked_text)

    def _extract_text(self, exchange: Exchange[Any]) -> str:
        """Достать masked-текст по ``source_property`` (dot-path)."""
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
            return (
                cursor
                if isinstance(cursor, str)
                else (str(cursor) if cursor is not None else "")
            )

        cursor = exchange.get_property(head)
        for part in parts[1:]:
            if cursor is None:
                return ""
            cursor = (
                cursor.get(part)
                if isinstance(cursor, dict)
                else getattr(cursor, part, None)
            )
        return (
            cursor
            if isinstance(cursor, str)
            else (str(cursor) if cursor is not None else "")
        )

    def _write_target(self, exchange: Exchange[Any], text: str) -> None:
        """Записать восстановленный текст в ``target_property``."""
        parts = self.target_property.split(".")
        head = parts[0]
        if head == "body" and len(parts) == 1:
            exchange.in_message.body = text
            return
        if head == "body" and isinstance(exchange.in_message.body, dict):
            cursor = exchange.in_message.body
            for part in parts[1:-1]:
                if not isinstance(cursor.get(part), dict):
                    cursor[part] = {}
                cursor = cursor[part]
            cursor[parts[-1]] = text
            return
        exchange.set_property(head, text)

    @staticmethod
    def _extract_unmasked_text(unmasked: Any, *, fallback: str) -> str:
        """Извлечь plaintext из результата ``unmask`` (различные форматы)."""
        if isinstance(unmasked, str):
            return unmasked
        for attr in ("text", "unmasked_text", "plaintext"):
            value = getattr(unmasked, attr, None)
            if isinstance(value, str):
                return value
        return fallback

    @staticmethod
    def _resolve_tokenizer() -> Any | None:
        """Lazy-резолв :class:`PIITokenizer`."""
        try:
            from src.backend.core.di.container import get_container

            container = get_container()
            if container is not None:
                return container.resolve_optional("pii_tokenizer")
        except Exception as exc:
            _logger.debug("DI container resolve failed: %s", exc)
        return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {}
        if self.source_property != "body":
            spec["source_property"] = self.source_property
        if self.target_property != self.source_property:
            spec["target_property"] = self.target_property
        if self.token_map_property != "pii_token_map":  # noqa: S105  # config field name, not a password
            spec["token_map_property"] = self.token_map_property
        if self.scope != "default":
            spec["scope"] = self.scope
        if self.strict:
            spec["strict"] = True
        return {"pii_unmask": spec}
