"""Per-domain constants: resilience (CB + retry defaults) (S168 W10 P1-14).

Extracted from ``core/config/constants.py`` per master prompt P1-14:
"extract per-domain from core/config/constants.py (81 lines)".

Ponytail: minimum surgical extraction. CB + retry defaults grouped
(share domain). RETRIABLE_DB_CODES остаётся в constants.py
(separate DB-domain extraction — separate WIP).
"""

from __future__ import annotations

__all__ = ("DEFAULT_CB_FAILURE_THRESHOLD", "DEFAULT_CB_RECOVERY_SECONDS",
           "DEFAULT_CB_FAST_FAILURE_THRESHOLD", "DEFAULT_CB_FAST_RECOVERY_SECONDS",
           "DEFAULT_RETRY_MAX_ATTEMPTS", "DEFAULT_RETRY_INITIAL_BACKOFF",
           "DEFAULT_RETRY_BACKOFF_MULTIPLIER", "DEFAULT_RETRY_JITTER")

# Wave 6: дефолты circuit-breaker'а для инфраструктурных зависимостей
# (используются, если в соответствующих *_settings нет своего значения).
DEFAULT_CB_FAILURE_THRESHOLD: int = 5
DEFAULT_CB_RECOVERY_SECONDS: float = 30.0
DEFAULT_CB_FAST_FAILURE_THRESHOLD: int = 3
DEFAULT_CB_FAST_RECOVERY_SECONDS: float = 15.0

# Wave 6.3: дефолты retry-политики (используются, если callsite не
# переопределил RetryPolicy полями).
DEFAULT_RETRY_MAX_ATTEMPTS: int = 3
DEFAULT_RETRY_INITIAL_BACKOFF: float = 0.5
DEFAULT_RETRY_BACKOFF_MULTIPLIER: float = 2.0
DEFAULT_RETRY_JITTER: float = 0.5
