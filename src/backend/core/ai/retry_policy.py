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
from src.backend.core.logging import get_logger


from pydantic import BaseModel, ConfigDict, Field

logger = get_logger(__name__)



class RetryPolicy(BaseModel):
    """Retry-настройки activity-шага (Temporal-совместимые).

    Originally из ``src/backend/dsl/workflow/spec/policies.py`` (S31+).
    S68 W2: moved в ``core/ai/`` для устранения core→dsl reverse import
    violation (TD-S65-W2). dsl/workflow/spec/policies.py re-export'ит для
    backward compat.
    """

    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, description="Максимум попыток.")
    initial_interval_s: float = Field(
        default=1.0, gt=0.0, description="Начальный интервал retry в секундах."
    )
    backoff_coefficient: float = Field(
        default=2.0, ge=1.0, description="Коэффициент экспоненциального backoff."
    )
    maximum_interval_s: float | None = Field(
        default=None,
        gt=0.0,
        description="Верхняя граница интервала retry; None — без ограничения.",
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
