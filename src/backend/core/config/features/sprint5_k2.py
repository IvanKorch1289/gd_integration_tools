"""Sprint 5 K2 Resilience+Perf feature-flags (T1.3.22 split from core.config.features.__init__).

Извлечено 5 flags (S38 P1.1 W1 T1.3.22):
- Sprint 5 K2 Resilience+Perf (5):
  - inbox_fail_closed (Sprint 5 K2 W3)
  - tenacity_finalized (Sprint 5 K2 W6)
  - per_tenant_rate_limit (Sprint 5 K2 W7)
  - graylog_chain_enabled (Sprint 5 K2 W5)
  - genai_chain_enabled (Sprint 5 K2 W5)

NB: ``scheduler_backend: Literal["apscheduler", "temporal"]`` is NOT extracted
— это config type (выбор SchedulerBackend impl), а не feature-flag, и остаётся
inline в ``features/__init__.py`` между Sprint5Flags и Sprint5DSLFlags в MRO.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprint5K2Flags(BaseSettings):
    """Sprint 5 K2 Resilience+Perf. Owner: K2 Resilience.

    Per S38 T1.3.22, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprint5_k2 import Sprint5K2Flags
        class FeatureFlags(..., Sprint5Flags, Sprint5K2Flags, Sprint5DSLFlags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    # ─── Sprint 5 — К2 Resilience+Perf ────────────────────────────────────
    inbox_fail_closed: bool = Field(
        default=True,
        title="K2 S5 W3: Inbox dedup fail-closed (Redis-error → InboxUnavailable)",
        description=(
            "K2 Sprint 5 Wave 3. Owner: K2 Resilience. ETA: S5-W3. "
            "При True seen_or_mark() поднимает InboxUnavailable при Redis-error "
            "вместо silently-allowing duplicate. default-OFF до stress-теста."
        ),
    )

    tenacity_finalized: bool = Field(
        default=True,
        title="K2 S5 W6: Tenacity unification финал (RetryPolicy/Budget → make_async_retry)",
        description=(
            "K2 Sprint 5 Wave 6. Owner: K2 Resilience. ETA: S5-W6. "
            "Активирует строгий режим: legacy RetryPolicy/RetryBudget classes "
            "поднимают DeprecationWarning. default-OFF до миграции callsites."
        ),
    )

    per_tenant_rate_limit: bool = Field(
        default=True,
        title="K2 S5 W7: per-tenant namespace в RateLimiter (scope=tenant)",
        description=(
            "K2 Sprint 5 Wave 7. Owner: K2 Resilience. ETA: S5-W7. "
            "Активирует scope=tenant key prefix в RateLimiter ключах. "
            "default-OFF до интеграции с TenantContext и smoke."
        ),
    )

    graylog_chain_enabled: bool = Field(
        default=True,
        title="K2 S5 W5: Graylog fallback chain (TCP→HTTPS→disk)",
        description=(
            "K2 Sprint 5 Wave 5. Owner: K2 Resilience. ETA: S5-W5. "
            "Активирует graylog_chain.py — fallback при недоступности Graylog: "
            "TCP-pool → HTTPS-batch → disk-rotating buffer. "
            "default-OFF до прохождения chaos-теста."
        ),
    )

    genai_chain_enabled: bool = Field(
        default=True,
        title="K2 S5 W5: GenAI provider fallback chain (primary→secondary→degraded)",
        description=(
            "K2 Sprint 5 Wave 5. Owner: K2 Resilience. ETA: S5-W5. "
            "Активирует genai_chain.py — fallback при недоступности primary "
            "LLM-провайдера: openai → anthropic → degraded local model. "
            "default-OFF до интеграции с LiteLLM gateway."
        ),
    )


__all__ = ("Sprint5K2Flags",)
