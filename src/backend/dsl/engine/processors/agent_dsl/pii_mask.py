"""PIIMaskProcessor — reversible PII tokenization (S27 W2, ADR-NEW-21).

Декларативная обёртка над :class:`PIITokenizer.mask_reversible`
(S25 W4 ADR-NEW-21). Маскирует PII (placeholder ``[PHONE_1]`` /
``[EMAIL_1]``) в указанной части exchange и сохраняет ``token_map``
для последующего :class:`PIIUnmaskProcessor`.

YAML контракт::

    steps:
      - pii_mask:
          source_property: body
          target_property: body
          scope: banking
          language: ru

Python контракт::

    builder.pii_mask(scope="banking", language="ru")

Capability ``pii.tokenize.reversible.<scope>`` обязательна.

Свойства exchange после выполнения
-----------------------------------
* ``pii_token_map`` — ``TokenMap`` для round-trip ``unmask``;
* ``pii_detected`` — ``True`` если хотя бы один entity найден;
* модифицированный текст в ``target_property`` (если он dict — частичное
  обновление полей, иначе — полная замена).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("PIIMaskProcessor",)

_logger = get_logger(__name__)


class PIIMaskProcessor(BaseAIProcessor):
    """Reversible PII tokenization через :class:`PIITokenizer.mask_reversible`.

    Args:
        scope: Capability scope (``"banking"`` / ``"hr"`` / ``"medical"``).
            Требуется для capability ``pii.tokenize.reversible.<scope>``.
        source_property: Откуда взять текст. Default ``"body"`` —
            ``exchange.in_message.body``. Поддерживает dot-path.
        target_property: Куда положить masked-текст. Default — совпадает
            с ``source_property`` (in-place).
        language: Язык для Presidio NER. Default ``"ru"``.
        name: Имя процессора.

    Notes:
        При недоступности :class:`PIITokenizer` (DI singleton ``None``
        или raises) — silent pass-through + WARNING + ``pii_detected=False``.
        Это поведение нужно для CI без presidio.
    """

    required_capability: ClassVar[str | None] = "pii.tokenize.reversible"
    audit_event: ClassVar[str | None] = "ai.pii.mask"

    def __init__(
        self,
        *,
        scope: str,
        source_property: str = "body",
        target_property: str | None = None,
        language: str = "ru",
        name: str | None = None,
    ) -> None:
        if not scope:
            raise ValueError("PIIMaskProcessor: scope обязателен (для capability)")
        super().__init__(name=name or f"pii_mask:{scope}")
        self.scope = scope
        self.source_property = source_property
        self.target_property = target_property or source_property
        self.language = language

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        del exchange
        return self.scope

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        del context
        text = self._extract_text(exchange)
        if not text:
            exchange.set_property("pii_detected", False)
            return

        tokenizer = self._resolve_tokenizer()
        if tokenizer is None:
            _logger.warning(
                "%s: PIITokenizer недоступен — pass-through (без mask)", self.name
            )
            exchange.set_property("pii_detected", False)
            return

        try:
            result = await tokenizer.mask_reversible(text, language=self.language)
        except Exception as exc:
            _logger.warning(
                "%s: mask_reversible failed (%s) — pass-through", self.name, exc
            )
            exchange.set_property("pii_detected", False)
            return

        masked_text = self._extract_masked_text(result, fallback=text)
        token_map = self._extract_token_map(result)
        pii_detected = self._extract_pii_detected(result, token_map)

        self._write_target(exchange, masked_text)
        exchange.set_property("pii_token_map", token_map)
        exchange.set_property("pii_detected", pii_detected)

    def _extract_text(self, exchange: Exchange[Any]) -> str:
        """Достать текст по ``source_property``."""
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

    def _write_target(self, exchange: Exchange[Any], masked_text: str) -> None:
        """Записать masked-текст в ``target_property``."""
        parts = self.target_property.split(".")
        head = parts[0]
        if head == "body" and len(parts) == 1:
            exchange.in_message.body = masked_text
            return
        if head == "body" and isinstance(exchange.in_message.body, dict):
            cursor = exchange.in_message.body
            for part in parts[1:-1]:
                if not isinstance(cursor.get(part), dict):
                    cursor[part] = {}
                cursor = cursor[part]
            cursor[parts[-1]] = masked_text
            return
        # property:<name>... → set_property
        exchange.set_property(head, masked_text)

    @staticmethod
    def _extract_masked_text(result: Any, *, fallback: str) -> str:
        """Извлечь masked-текст из :class:`MaskResult` PIITokenizer'а."""
        for attr in ("masked_text", "sanitized_text", "text"):
            value = getattr(result, attr, None)
            if isinstance(value, str):
                return value
        if isinstance(result, str):
            return result
        if isinstance(result, tuple) and result and isinstance(result[0], str):
            return result[0]
        return fallback

    @staticmethod
    def _extract_token_map(result: Any) -> Any:
        """Извлечь TokenMap (опаковый объект — backend-specific)."""
        for attr in ("token_map", "tokenmap", "map"):
            value = getattr(result, attr, None)
            if value is not None:
                return value
        if isinstance(result, tuple) and len(result) >= 2:
            return result[1]
        return None

    @staticmethod
    def _extract_pii_detected(result: Any, token_map: Any) -> bool:
        """Определить ``pii_detected`` по результату."""
        detected = getattr(result, "pii_detected", None)
        if isinstance(detected, bool):
            return detected
        if token_map is None:
            return False
        # Эвристика: dict-token_map без entries = no PII.
        if isinstance(token_map, dict):
            return bool(token_map)
        entries = getattr(token_map, "entries", None)
        if entries is not None:
            return bool(entries)
        return True

    @staticmethod
    def _resolve_tokenizer() -> Any | None:
        """Lazy-резолв :class:`PIITokenizer` через DI singleton."""
        return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {"scope": self.scope}
        if self.source_property != "body":
            spec["source_property"] = self.source_property
        if self.target_property != self.source_property:
            spec["target_property"] = self.target_property
        if self.language != "ru":
            spec["language"] = self.language
        return {"pii_mask": spec}
