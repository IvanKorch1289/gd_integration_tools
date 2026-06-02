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

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


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

        # Check if context is large enough to warrant RLM
        estimated_tokens = self._estimate_tokens(ctx)
        use_rlm_mode = estimated_tokens > self.config.context_threshold

        if use_rlm_mode:
            result = await self._execute_rlm(ctx, query)
        else:
            result = await self._execute_direct(ctx, query)

        # Store result
        exchange.set_property(self.result_property, result)
        exchange.set_property("rlm_tokens_used", result.tokens_used)
        exchange.set_property("rlm_iterations", result.iterations)

        # Set output message
        if result.answer:
            exchange.out_message = exchange.out_message or Message(
                body=result.answer, headers={}
            )
            if hasattr(exchange.out_message, "body"):
                exchange.out_message.body = result.answer

    async def _execute_rlm(self, context: str, query: str) -> RLMResult:
        """Execute RLM algorithm.

        This is a stub implementation that demonstrates the RLM approach.
        Full implementation would use Deno/Pyodide for sandboxed execution.
        """
        result = RLMResult()
        result.context_size = len(context.split())

        # Stub: simulate RLM behavior
        # In production, this would:
        # 1. Create a sandboxed Python REPL environment
        # 2. Load context into the REPL variable space
        # 3. Have LLM write code to examine context
        # 4. Execute code in sandbox
        # 5. Feed results back to LLM for refinement
        # 6. Repeat until SUBMIT() is called

        result.answer = (
            f"[RLM stub] Processed {result.context_size} tokens for query: {query}"
        )
        result.iterations = min(3, result.context_size // 1000)
        result.calls = result.iterations
        result.tokens_used = result.context_size * 2  # Rough estimate

        return result

    async def _execute_direct(self, context: str, query: str) -> RLMResult:
        """Execute direct LLM call for smaller contexts."""
        result = RLMResult()
        result.context_size = len(context.split())

        # Stub: direct LLM call
        result.answer = (
            f"[Direct stub] Processed {result.context_size} tokens for query: {query}"
        )
        result.tokens_used = result.context_size
        result.calls = 1
        result.iterations = 1

        return result

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (1 token ≈ 4 chars for English)."""
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
