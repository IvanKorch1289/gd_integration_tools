"""S68 W2 sample refactor: ``RetryPolicy`` moved в core/ai/.

TD-S65-W2 violations (35 core → other layers):
- ``core/ai/agent_registry.py:113``: lazy ``from src.backend.dsl.workflow.spec import RetryPolicy``
- ``core/ai/agent_spec.py:173``: bottom-of-file ``from src.backend.dsl.workflow.spec import RetryPolicy``

Оба файла core/ai/ lazy-import класс, который реально живёт в
``src/backend/dsl/workflow/spec/policies.py``. Это circular smell:
core (база) не должно зависеть от dsl (meta-layer).

Sample refactor (Tier 1, trivial): ``RetryPolicy`` — Pydantic BaseModel
с 6 полями, ZERO internal backend deps (только Pydantic Field
constraints). Trivially moveable в core/ai/.

Backward-compat: dsl/workflow/spec/policies.py re-export'ит из нового
места, чтобы existing imports ``from src.backend.dsl.workflow.spec
import RetryPolicy`` продолжали работать.
"""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class RetryPolicy(BaseModel):
    """Retry-настройки activity-шага (Temporal-совместимые).

    Originally из ``src/backend/dsl/workflow/spec/policies.py`` (S31+).
    S68 W2: moved в ``core/ai/`` для устранения core→dsl reverse import
    violation (TD-S65-W2). dsl/workflow/spec/policies.py re-export'ит для
    backward compat.
    """

    # Cycle 9 swarm (D423 unification): accept legacy field name aliases
    # from the older retry policy classes (initial_interval_s →
    # initial_delay_s, backoff_coefficient → multiplier, maximum_interval_s →
    # max_delay_s). Populated via validation_alias for backward compat
    # with resilience_profile.py and retry.py callers.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    max_attempts: int = Field(
        default=3,
        ge=1,
        description="Максимум попыток.",
        validation_alias=AliasChoices("max_attempts", "maximum_attempts", "max_tries"),
    )
    initial_interval_s: float = Field(
        default=1.0,
        gt=0.0,
        description="Начальный интервал retry в секундах.",
        validation_alias=AliasChoices(
            "initial_interval_s", "initial_delay_s", "delay_s"
        ),
    )
    backoff_coefficient: float = Field(
        default=2.0,
        ge=1.0,
        description="Коэффициент экспоненциального backoff.",
        validation_alias=AliasChoices(
            "backoff_coefficient", "multiplier", "backoff_multiplier"
        ),
    )
    maximum_interval_s: float | None = Field(
        default=None,
        gt=0.0,
        description="Верхняя граница интервала retry; None — без ограничения.",
        validation_alias=AliasChoices(
            "maximum_interval_s", "max_delay_s", "max_interval"
        ),
    )
    non_retryable_errors: tuple[str, ...] = Field(
        default=(), description="Имена ошибок, при которых retry НЕ выполняется."
    )
    jitter: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Jitter: random fraction of interval [0..1].",
    )


__all__ = ("RetryPolicy",)
