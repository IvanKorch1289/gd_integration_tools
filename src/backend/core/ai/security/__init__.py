"""AI Agent security framework — facade entry-point (S172 audit).

Single import location для всего agent-security пайплайна, чтобы бизнес-логика
НЕ импортировала напрямую из ``agent_security.py`` (deep path).

Поверхностный API:
- ``AgentSecurityFramework`` — main runtime enforcer
- ``AgentSecurityPolicy`` — declarative policy (strict/dev/custom)
- ``get_agent_security_framework()`` — lazy singleton через @lru_cache
- ``SecurityDecision``, ``ThreatLevel`` — типы решений
- ``DangerousCommandDetector``, ``FileModificationPolicy`` — детекторы
- ``SecurityHook``, ``SecurityHookFn`` — расширяемая hook-система

Использование (extension/plugin code)::

    from src.backend.core.ai.security import get_agent_security_framework

    framework = get_agent_security_framework()
    decision = framework.validate_prompt(prompt)
    if not decision.allowed:
        raise SecurityViolationError(decision.reason)

Использование (DSL route) — см. ``dsl/engine/processors/agent_dsl/agent_security_check.py``.

Архитектура (не ad-hoc правила, а фреймворк):
- Threat detector — pattern-based + extensible hook system
- Policy enforcement — strict-mode default for production
- PII masking интеграция — через core.security.pii_masker.default_masker
- Hook system — pre_tool/post_tool/pre_llm/post_llm для DSL-расширений

Основан на:
- OWASP LLM Top 10 (LLM01: Prompt Injection, LLM06: Sensitive Info Disclosure)
- NIST AI Risk Management Framework
- Master Prompt §9.3 (AI Safety)

Note:
    ``PromptValidator`` объявлен в ``agent_security.__all__`` (S187 scaffold),
    но concrete class ещё не реализован — намеренно НЕ реэкспортируется здесь.
    Когда появится, добавить в этот facade + ``__all__``.

"""

from src.backend.core.ai.security.agent_security import (
    AgentSecurityFramework,
    AgentSecurityPolicy,
    DangerousCommandDetector,
    FileModificationPolicy,
    SecurityDecision,
    SecurityHook,
    SecurityHookFn,
    ThreatLevel,
    get_agent_security_framework,
)

__all__ = (
    "AgentSecurityFramework",
    "AgentSecurityPolicy",
    "DangerousCommandDetector",
    "FileModificationPolicy",
    "SecurityDecision",
    "SecurityHook",
    "SecurityHookFn",
    "ThreatLevel",
    "get_agent_security_framework",
)
