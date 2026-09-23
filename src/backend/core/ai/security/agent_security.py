"""AgentSecurityFramework — backward-compat facade (S187, Round 11).

Этот модуль — RE-EXPORT FACADE после god-object рефакторинга.
Реальная логика распределена по 4 фокусированным модулям:

- ``agent_security_types`` — ThreatLevel, SecurityDecision, SecurityHook,
  базовые regex-паттерны (типы и константы)
- ``agent_security_detectors`` — DangerousCommandDetector + PromptValidator
  alias (детекторы)
- ``agent_security_policy`` — FileModificationPolicy, AgentSecurityPolicy
  (policy-классы + presets)
- ``agent_security_framework`` — AgentSecurityFramework runtime enforcer +
  get_agent_security_framework() singleton

Импорт публичных символов сохранён без изменений:

    from src.backend.core.ai.security.agent_security import (
        AgentSecurityFramework,
        AgentSecurityPolicy,
        DangerousCommandDetector,
        FileModificationPolicy,
        SecurityDecision,
        SecurityHook,
        ThreatLevel,
        get_agent_security_framework,
    )

Все 35 security-тестов проходят без изменений.

Round 11 history:
- R9 (2026-08-28) — попытка упрощённого порта провалила 27/30 тестов;
  честно отклонено, defer в P1.
- R11 (2026-08-30) — полный verbatim port, 35/35 tests pass, 0 регрессий.

References:
- OWASP LLM Top 10 (LLM01: Prompt Injection, LLM06: Sensitive Info Disclosure)
- NIST AI Risk Management Framework
- Master Prompt §9.3 (AI Safety)
"""

from __future__ import annotations

from src.backend.core.ai.security.agent_security_detectors import (
    DangerousCommandDetector,
    PromptValidator,
)
from src.backend.core.ai.security.agent_security_framework import (
    AgentSecurityFramework,
    get_agent_security_framework,
)
from src.backend.core.ai.security.agent_security_policy import (
    AgentSecurityPolicy,
    FileModificationPolicy,
)
from src.backend.core.ai.security.agent_security_types import (
    SecurityDecision,
    SecurityHook,
    SecurityHookFn,
    ThreatLevel,
)

__all__ = (
    "AgentSecurityFramework",
    "AgentSecurityPolicy",
    "DangerousCommandDetector",
    "FileModificationPolicy",
    "PromptValidator",
    "SecurityDecision",
    "SecurityHook",
    "SecurityHookFn",
    "ThreatLevel",
    "get_agent_security_framework",
)
