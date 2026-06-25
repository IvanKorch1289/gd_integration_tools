"""Agent-specific PII DSL processors (Sprint 170 S170 — user-requested feature).

User explicitly requested: "Дополнительный DSL-процессор для маскирования,
если есть сомнения, что общий PII не справится".

Two specialized processors:

1. :class:`AgentToolPIIMaskProcessor` — masks PII in tool_call args BEFORE
   tool execution (defense-in-depth: tool args may contain sensitive data
   that general PII misses — e.g., bearer tokens in headers, internal IDs,
   free-form text from LLM with non-standard PII).

2. :class:`AgentActionPIIMaskProcessor` — masks PII in action params
   (DB queries, API requests, MCP tool calls). Same rationale: action
   params may have custom PII patterns not covered by general recognizers.

Both use the same :class:`PIITokenizer` (Presidio-backed) but with
agent-specific audit + capability scopes:
- ``pii.tokenize.reversible.agent_tools`` — for tool calls
- ``pii.tokenize.reversible.agent_actions`` — for actions

Pattern: thin wrapper (Ponytail) — no new abstractions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "AgentToolPIIMaskProcessor",
    "AgentActionPIIMaskProcessor",
)
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
            text = result.get("text", v) if isinstance(result, dict) else v  # already awaited
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


class AgentToolPIIMaskProcessor(BaseAIProcessor):
    """Маскирует PII в tool_call args ПЕРЕД выполнением tool.

    Используется в agent workflows между dispatch и execution::

        - ai_tool_dispatch:
            available_tool_ids: [send_email]
        - agent_pii_tool_mask:
            scope: banking
        - tool: send_email

    Args:
        scope: Capability scope (``"banking"`` / ``"hr"``).
        source_property: Где искать ``args`` dict (default ``body.args``).
        target_property: Куда записать masked ``args`` (default in-place).
        language: Presidio NER language (default ``"ru"``).
    """

    required_capability: ClassVar[str | None] = "pii.tokenize.reversible.agent_tools"
    audit_event: ClassVar[str | None] = "ai.agent.pii.tool_mask"

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
            raise ValueError("AgentToolPIIMaskProcessor: scope обязателен")
        super().__init__(name=name or f"agent_pii_tool_mask:{scope}")
        self.scope = scope
        self.source_property = source_property
        self.target_property = target_property or source_property
        self.language = language

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.ai import get_pii_tokenizer_provider

        provider = get_pii_tokenizer_provider()
        tokenizer = provider() if provider else None
        if tokenizer is None:
            _logger.warning(
                "%s: PIITokenizer недоступен — pass-through", self.name
            )
            exchange.set_property("pii_detected", False)
            return

        # Resolve args dict from source_property (supports body.args, body.tool_call.args, etc.)
        head, _, rest = self.source_property.partition(".")
        cursor: Any = (
            exchange.in_message.body if head == "body" else None
        )
        for part in [rest] if not rest else rest.split("."):
            if cursor is None:
                break
            cursor = cursor.get(part) if isinstance(cursor, dict) else None

        if not isinstance(cursor, dict):
            exchange.set_property("pii_detected", False)
            return

        masked, token_map, detected = await _mask_dict_values(
            cursor, tokenizer, self.language
        )

        # Write masked back to target_property
        target_head, _, target_rest = self.target_property.partition(".")
        target_body: Any = (
            exchange.in_message.body if target_head == "body" else None
        )
        if target_body is not None and isinstance(target_body, dict):
            # Last segment is the dict key itself
            parts = target_rest.split(".") if target_rest else []
            if parts:
                parent = target_body
                for p in parts[:-1]:
                    parent = parent.get(p, {}) if isinstance(parent, dict) else {}
                parent[parts[-1]] = masked
            else:
                exchange.in_message.body = masked

        exchange.set_property("pii_token_map", token_map)
        exchange.set_property("pii_detected", detected)


class AgentActionPIIMaskProcessor(BaseAIProcessor):
    """Маскирует PII в action params ПЕРЕД action execution (DB/API/MCP).

    Args:
        scope: Capability scope.
        source_property: Где искать ``params`` dict (default ``body.params``).
        target_property: Куда записать masked ``params`` (default in-place).
        language: Presidio NER language (default ``"ru"``).
    """

    required_capability: ClassVar[str | None] = (
        "pii.tokenize.reversible.agent_actions"
    )
    audit_event: ClassVar[str | None] = "ai.agent.pii.action_mask"

    def __init__(
        self,
        *,
        scope: str,
        source_property: str = "body.params",
        target_property: str | None = None,
        language: str = "ru",
        name: str | None = None,
    ) -> None:
        if not scope:
            raise ValueError("AgentActionPIIMaskProcessor: scope обязателен")
        super().__init__(name=name or f"agent_pii_action_mask:{scope}")
        self.scope = scope
        self.source_property = source_property
        self.target_property = target_property or source_property
        self.language = language

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.ai import get_pii_tokenizer_provider

        provider = get_pii_tokenizer_provider()
        tokenizer = provider() if provider else None
        if tokenizer is None:
            exchange.set_property("pii_detected", False)
            return

        head, _, rest = self.source_property.partition(".")
        cursor: Any = (
            exchange.in_message.body if head == "body" else None
        )
        for part in [rest] if not rest else rest.split("."):
            if cursor is None:
                break
            cursor = cursor.get(part) if isinstance(cursor, dict) else None

        if not isinstance(cursor, dict):
            exchange.set_property("pii_detected", False)
            return

        masked, token_map, detected = await _mask_dict_values(
            cursor, tokenizer, self.language
        )

        target_head, _, target_rest = self.target_property.partition(".")
        target_body: Any = (
            exchange.in_message.body if target_head == "body" else None
        )
        if target_body is not None and isinstance(target_body, dict):
            parts = target_rest.split(".") if target_rest else []
            if parts:
                parent = target_body
                for p in parts[:-1]:
                    parent = parent.get(p, {}) if isinstance(parent, dict) else {}
                parent[parts[-1]] = masked
            else:
                exchange.in_message.body = masked

        exchange.set_property("pii_token_map", token_map)
        exchange.set_property("pii_detected", detected)
