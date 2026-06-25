"""Agent-specific PII DSL processors (Sprint 170 S170 — user-requested feature).

User explicitly requested: "Дополнительный DSL-процессор для маскирования,
если есть сомнения, что общий PII не справится".

Two specialized scenarios (both delegate to same recursive mask helper):

1. :class:`AgentDictPIIMaskProcessor.for_tools` — masks PII in tool_call
   args BEFORE tool execution (defense-in-depth).

2. :class:`AgentDictPIIMaskProcessor.for_actions` — masks PII in action
   params (DB queries, API requests, MCP tool calls).

Ponytail: один класс с classmethods для разных scope-семантик.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("AgentDictPIIMaskProcessor",)
_logger = get_logger(__name__)


async def _mask_dict_values(
    d: dict[str, Any],
    tokenizer: Any,
    language: str,
) -> tuple[dict[str, Any], dict[str, str], bool]:
    """Mask all string values in dict recursively.

    Returns: (masked_dict, merged_token_map, any_pii_detected)
    """
    merged_tokens: dict[str, str] = {}
    detected = False
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, str):
            result = await tokenizer.mask_reversible(v, language=language)
            text = result.get("text", v) if isinstance(result, dict) else v
            tok_map = result.get("token_map", {}) if isinstance(result, dict) else {}
            if tok_map:
                detected = True
                merged_tokens.update(tok_map)
            out[k] = text
        elif isinstance(v, dict):
            sub_out, sub_tok, sub_det = await _mask_dict_values(v, tokenizer, language)
            merged_tokens.update(sub_tok)
            detected = detected or sub_det
            out[k] = sub_out
        else:
            out[k] = v
    return out, merged_tokens, detected


def _resolve_dict_at_path(exchange: Any, path: str) -> dict[str, Any] | None:
    """Resolve dot-path ``body.x.y.z`` against exchange.in_message.body.

    Returns dict at end of path, or None if any segment missing/non-dict.
    """
    head, _, rest = path.partition(".")
    if head != "body":
        return None
    cursor: Any = exchange.in_message.body
    if not isinstance(cursor, dict):
        return None
    for part in rest.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor if isinstance(cursor, dict) else None


def _write_dict_at_path(exchange: Any, path: str, value: Any) -> None:
    """Write value to dot-path against exchange.in_message.body (mutates)."""
    head, _, rest = path.partition(".")
    if head != "body":
        return
    body = exchange.in_message.body
    if not isinstance(body, dict):
        return
    parts = rest.split(".")
    parent: Any = body
    for p in parts[:-1]:
        parent = parent.get(p, {}) if isinstance(parent, dict) else {}
    if parts:
        if isinstance(parent, dict):
            parent[parts[-1]] = value


class AgentDictPIIMaskProcessor(BaseAIProcessor):
    """Маскирует PII в dict (tool args / action params) перед исполнением.

    Args:
        scope: Capability scope (``"banking"`` / ``"hr"``).
        source_property: Где искать dict (default ``"body.args"``).
        target_property: Куда записать masked dict (default = source).
        language: Presidio NER language (default ``"ru"``).

    Use classmethods:
        - :meth:`for_tools` — для tool_call args (capability/audit pre-set)
        - :meth:`for_actions` — для action params (capability/audit pre-set)

    Example::

        - agent_pii_mask: for_tools
        - agent_pii_mask: for_actions
    """

    _CAPABILITY_FOR_TOOLS: ClassVar[str] = "pii.tokenize.reversible.agent_tools"
    _AUDIT_FOR_TOOLS: ClassVar[str] = "ai.agent.pii.tool_mask"
    _CAPABILITY_FOR_ACTIONS: ClassVar[str] = "pii.tokenize.reversible.agent_actions"
    _AUDIT_FOR_ACTIONS: ClassVar[str] = "ai.agent.pii.action_mask"

    required_capability: ClassVar[str | None] = _CAPABILITY_FOR_TOOLS
    audit_event: ClassVar[str | None] = _AUDIT_FOR_TOOLS

    def __init__(
        self,
        *,
        scope: str,
        source_property: str = "body.args",
        target_property: str | None = None,
        language: str = "ru",
        name: str | None = None,
    ) -> None:
        if not scope:
            raise ValueError("AgentDictPIIMaskProcessor: scope обязателен")
        super().__init__(name=name or f"agent_pii_mask:{scope}")
        self.scope = scope
        self.source_property = source_property
        self.target_property = target_property or source_property
        self.language = language

    @classmethod
    def for_tools(
        cls,
        *,
        scope: str,
        source_property: str = "body.args",
        target_property: str | None = None,
        language: str = "ru",
    ) -> "AgentDictPIIMaskProcessor":
        """Маскирование tool_call args.

        Capability: pii.tokenize.reversible.agent_tools
        Audit: ai.agent.pii.tool_mask
        """
        instance = cls(
            scope=scope,
            source_property=source_property,
            target_property=target_property,
            language=language,
        )
        instance.required_capability = cls._CAPABILITY_FOR_TOOLS
        instance.audit_event = cls._AUDIT_FOR_TOOLS
        instance.name = f"agent_pii_tool_mask:{scope}"
        return instance

    @classmethod
    def for_actions(
        cls,
        *,
        scope: str,
        source_property: str = "body.params",
        target_property: str | None = None,
        language: str = "ru",
    ) -> "AgentDictPIIMaskProcessor":
        """Маскирование action params.

        Capability: pii.tokenize.reversible.agent_actions
        Audit: ai.agent.pii.action_mask
        """
        instance = cls(
            scope=scope,
            source_property=source_property,
            target_property=target_property,
            language=language,
        )
        instance.required_capability = cls._CAPABILITY_FOR_ACTIONS
        instance.audit_event = cls._AUDIT_FOR_ACTIONS
        instance.name = f"agent_pii_action_mask:{scope}"
        return instance

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.ai import get_pii_tokenizer_provider

        provider = get_pii_tokenizer_provider()
        tokenizer = provider() if provider else None
        # Always set token_map (even if empty) — pii_unmask expects consistent schema
        if tokenizer is None:
            _logger.warning("%s: PIITokenizer недоступен — pass-through", self.name)
            exchange.set_property("pii_token_map", {})
            exchange.set_property("pii_detected", False)
            return

        cursor = _resolve_dict_at_path(exchange, self.source_property)
        if cursor is None:
            # Source path missing or non-dict — no PII to mask, but still set token_map
            exchange.set_property("pii_token_map", {})
            exchange.set_property("pii_detected", False)
            return

        masked, token_map, detected = await _mask_dict_values(
            cursor, tokenizer, self.language
        )
        _write_dict_at_path(exchange, self.target_property, masked)
        exchange.set_property("pii_token_map", token_map)
        exchange.set_property("pii_detected", detected)


