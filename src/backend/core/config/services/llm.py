"""LLM service settings (S164 W2).

Centralizes LLM-related configuration:
- Default model + timeout + retry defaults
- CB defaults (failure_threshold, recovery_timeout)
- Streaming + cost tracking toggles

Pattern: ``MailSettings`` / ``WSSettings`` — BaseSettingsWithLoader +
yaml_group + env_prefix.

DSL override (per-route): ``route.toml::[transport] pool_size``,
``message_timeout_s``, etc. — реализуется через ``DslService.get_route_overrides``
(S163 W15) и применяется per-action (W25) или per-connection (W33).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("LLMSettings", "llm_settings")


class LLMSettings(BaseSettingsWithLoader):
    """Стандартные настройки LLM-сервиса.

    Используются в:
        * ``services/ai/llm/tgi_batch_client.py`` (TGI HTTP client)
        * ``services/ai/llm/vllm_batch_client.py`` (vLLM HTTP client)
        * ``services/ai/gateway/client.py`` (LiteLLMGateway facade)
        * ``dsl/engine/processors/ai/llmcall_processor.py`` (call_llm DSL)

    Per-route override через ``route.toml::[transport]`` (S163 W17).
    """

    yaml_group: ClassVar[str] = "llm"
    model_config = SettingsConfigDict(env_prefix="LLM_", extra="forbid")

    # ── Default behavior ────────────────────────────────────────────

    default_model: str = Field(
        default="gpt-4o-mini",
        description="Модель по умолчанию (если не указана в DSL/messages).",
    )
    default_timeout: float = Field(
        default=60.0, gt=0, description="Default timeout для LLM-запросов (seconds)."
    )
    default_max_tokens: int = Field(
        default=1024, gt=0, description="Default max_tokens для generation."
    )

    # ── Retry defaults (tenacity) ────────────────────────────────────

    retry_max_attempts: int = Field(
        default=3,
        gt=0,
        description="Max retry attempts на transient failures (tenacity).",
    )
    retry_initial_backoff: float = Field(
        default=1.0, gt=0, description="Initial backoff между retries (seconds)."
    )
    retry_max_backoff: float = Field(
        default=8.0, gt=0, description="Max backoff cap (seconds)."
    )

    # ── Circuit Breaker defaults (purgatory) ────────────────────────

    cb_failure_threshold: int = Field(
        default=5,
        gt=0,
        description="CB failure threshold (consecutive failures → open).",
    )
    cb_recovery_seconds: float = Field(
        default=30.0,
        gt=0,
        description="CB recovery timeout (seconds before half-open).",
    )

    # ── TGI batch client (specific) ─────────────────────────────────

    tgi_concurrency: int = Field(
        default=10,
        gt=0,
        description="TGI batch client concurrency limit (asyncio.Semaphore).",
    )
    tgi_timeout: float = Field(
        default=60.0, gt=0, description="TGI request timeout (seconds)."
    )

    # ── Cost tracking ────────────────────────────────────────────────

    cost_tracking_enabled: bool = Field(
        default=True, description="Enable cost tracking callbacks (Langfuse)."
    )
    cost_budget_usd_per_hour: float | None = Field(
        default=None,
        gt=0,
        description="Optional hourly budget limit (USD). ``None`` = unlimited.",
    )


# Singleton per pattern (ws_settings, cache_settings, llm_settings, etc.).
llm_settings = LLMSettings()
