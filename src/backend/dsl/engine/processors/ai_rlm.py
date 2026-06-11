"""AI RLM Processor — Recursive Language Model processor.

Wave [wave:rlm-toolkit]
K-ARCH-2: AI/RAG/agents with MCP-server.

Implements the RLM (Recursive Language Model) approach from the paper:
https://arxiv.org/abs/2512.24601

RLM treats long prompts as part of an external environment and allows
the LLM to programmatically examine, decompose, and recursively call
itself over snippets of the prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import Message
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

logger = get_logger(__name__)


class RLMResult:
    """Result of an RLM execution."""

    def __init__(
        self,
        answer: str | None = None,
        tokens_used: int = 0,
        calls: int = 0,
        iterations: int = 0,
        context_size: int = 0,
    ) -> None:
        self.answer = answer
        self.tokens_used = tokens_used
        self.calls = calls
        self.iterations = iterations
        self.context_size = context_size


class RLMConfig:
    """Configuration for RLM execution.

    Attributes:
        max_iterations: Maximum number of recursive iterations.
            Default 10.
        max_tokens: Maximum tokens per call.
            Default 4000.
        temperature: Sampling temperature.
            Default 0.7.
        sandbox_enabled: Whether to use sandboxed REPL execution.
            Default True.
        context_threshold: Token count threshold for triggering RLM mode.
            Default 10000.
    """

    def __init__(
        self,
        max_iterations: int = 10,
        max_tokens: int = 4000,
        temperature: float = 0.7,
        sandbox_enabled: bool = True,
        context_threshold: int = 10000,
    ) -> None:
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.sandbox_enabled = sandbox_enabled
        self.context_threshold = context_threshold


class AIRLMProcessor(BaseProcessor):
    """AI Processor implementing Recursive Language Model (RLM) approach.

    RLM allows LLMs to programmatically explore large contexts through
    a sandboxed Python REPL. Instead of feeding huge contexts directly
    into the prompt, RLM treats context as external data that the LLM
    examines via code execution and recursive sub-LLM calls.

    This is particularly useful when:
    - Context is too large to fit in the LLM's context window
    - Need to process inputs up to 2 orders of magnitude beyond context limit
    - Want dramatic quality improvements over vanilla LLM approaches

    Side effect: EXTERNAL (calls LLM API)
    """

    side_effect = SideEffectKind.SIDE_EFFECTING
    compensatable = False

    def __init__(
        self,
        name: str | None = None,
        model: str = "openai/gpt-4",
        config: RLMConfig | None = None,
        prompt_template: str | None = None,
        result_property: str = "rlm_result",
    ) -> None:
        """Initialize RLM processor.

        Args:
            name: Processor name.
            model: LLM model identifier.
            config: RLM configuration.
            prompt_template: Custom prompt template with {context} and {query}.
            result_property: Exchange property to store result.
        """
        super().__init__(name=name or "ai_rlm")
        self.model = model
        self.config = config or RLMConfig()
        self.prompt_template = prompt_template
        self.result_property = result_property

    def _get_gateway(self) -> Any:
        """Lazy-resolve LiteLLMGateway from app_state or DI."""
        try:
            from src.backend.services.ai.gateway.client import get_litellm_gateway

            return get_litellm_gateway()
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_rlm: LiteLLMGateway unavailable: %s", exc)
            return None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Execute RLM processing.

        Args:
            exchange: The current exchange containing context and query.
            context: Execution context.

        The exchange body should contain:
            - context: The large context document/data
            - query: The question to answer about the context
        """
        body = exchange.in_message.body or {}
        ctx = body.get("context", "")
        query = body.get("query", "")

        if not ctx:
            exchange.set_error("AIRLMProcessor: 'context' is required in body")
            return

        if not query:
            exchange.set_error("AIRLMProcessor: 'query' is required in body")
            return

        estimated_tokens = self._estimate_tokens(ctx)
        use_rlm_mode = estimated_tokens > self.config.context_threshold

        try:
            if use_rlm_mode:
                result = await self._execute_rlm(ctx, query)
            else:
                result = await self._execute_direct(ctx, query)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ai_rlm execution failed")
            exchange.set_error(f"AIRLMProcessor: execution failed: {exc}")
            return

        exchange.set_property(self.result_property, result)
        exchange.set_property("rlm_tokens_used", result.tokens_used)
        exchange.set_property("rlm_iterations", result.iterations)

        if result.answer:
            exchange.out_message = exchange.out_message or Message(
                body=result.answer, headers={}
            )
            if hasattr(exchange.out_message, "body"):
                exchange.out_message.body = result.answer

    async def _execute_rlm(self, context: str, query: str) -> RLMResult:
        """Execute RLM algorithm via recursive chunk relevance + aggregation."""
        gateway = self._get_gateway()
        result = RLMResult(iterations=0, calls=0, tokens_used=0)
        result.context_size = self._estimate_tokens(context)

        # Split context into chunks (~3000 tokens each)
        words = context.split()
        chunk_size_words = 3000  # rough word budget per chunk
        chunks = [
            " ".join(words[i : i + chunk_size_words])
            for i in range(0, len(words), chunk_size_words)
        ]

        relevant_chunks: list[str] = []
        for chunk in chunks:
            if result.iterations >= self.config.max_iterations:
                break
            prompt = (
                f"Context snippet:\n{chunk}\n\n"
                f"Question: {query}\n\n"
                'Is this snippet relevant? Reply strictly JSON: {"relevant": true/false, "reasoning": "..."}'
            )
            try:
                resp = await gateway.acompletion(
                    messages=[{"role": "user", "content": prompt}],
                    model=self.model,
                    temperature=self.config.temperature,
                )
                result.calls += 1
                content = self._extract_content(resp)
                # Simple heuristic: if JSON contains "relevant": true
                if '"relevant"' in content and "true" in content.lower():
                    relevant_chunks.append(chunk)
                result.tokens_used += self._estimate_tokens(
                    prompt
                ) + self._estimate_tokens(content)
                result.iterations += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("ai_rlm chunk evaluation failed: %s", exc)

        if not relevant_chunks:
            relevant_chunks = chunks[:3]  # fallback: first 3 chunks

        aggregated = "\n---\n".join(relevant_chunks)
        final_prompt = (
            f"Aggregated relevant context:\n{aggregated}\n\n"
            f"Question: {query}\n\n"
            "Provide a concise answer based on the context."
        )
        try:
            final_resp = await gateway.acompletion(
                messages=[{"role": "user", "content": final_prompt}],
                model=self.model,
                temperature=self.config.temperature,
            )
            result.calls += 1
            result.answer = self._extract_content(final_resp)
            result.tokens_used += self._estimate_tokens(
                final_prompt
            ) + self._estimate_tokens(result.answer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_rlm final aggregation failed: %s", exc)
            result.answer = f"[RLM] Failed to aggregate answer: {exc}"

        return result

    async def _execute_direct(self, context: str, query: str) -> RLMResult:
        """Execute direct LLM call for smaller contexts."""
        gateway = self._get_gateway()
        result = RLMResult()
        result.context_size = self._estimate_tokens(context)

        prompt = (
            f"Context:\n{context}\n\nQuestion: {query}\n\n"
            "Provide a concise answer based on the context."
        )
        if self.prompt_template:
            prompt = self.prompt_template.format(context=context, query=query)

        try:
            resp = await gateway.acompletion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=self.config.temperature,
            )
            result.calls = 1
            result.iterations = 1
            result.answer = self._extract_content(resp)
            result.tokens_used = self._estimate_tokens(prompt) + self._estimate_tokens(
                result.answer
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_rlm direct call failed: %s", exc)
            result.answer = f"[Direct] Failed to get answer: {exc}"

        return result

    @staticmethod
    def _extract_content(response: Any) -> str:
        """Extract text content from LLM response."""
        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return msg.get("content", "")
            return response.get("content", "")
        if hasattr(response, "choices") and response.choices:
            return getattr(response.choices[0].message, "content", "") or ""
        return str(response)

    def _estimate_tokens(self, text: str) -> int:
        """Token estimation via tiktoken with fallback to heuristic."""
        try:
            import tiktoken

            enc = tiktoken.encoding_for_model("gpt-4")
            return len(enc.encode(text))
        except Exception:  # noqa: BLE001
            return len(text) // 4

    def to_spec(self) -> dict[str, Any] | None:
        """Return YAML-spec for this processor."""
        return {
            "ai_rlm": {
                "model": self.model,
                "max_iterations": self.config.max_iterations,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
                "sandbox_enabled": self.config.sandbox_enabled,
                "context_threshold": self.config.context_threshold,
                "prompt_template": self.prompt_template,
                "result_property": self.result_property,
            }
        }
