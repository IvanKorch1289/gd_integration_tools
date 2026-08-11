"""AI domain providers — sanitizer, PII tokenizer, LLM metrics, model registry, vault.

T-P1.2c split: извлечено из monolithic ``providers.py`` (S38 P1 epic).
Domain scope: 14 funcs (7 get + 7 set) + 3 private helpers
(``_resolve_pii_token_registry``, ``_resolve_unified_audit_service``,
``_noop_llm_judge_metrics``, ``_build_ai_gateway_singleton``).

Singleton cache ``_overrides`` is per-domain (NOT shared).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


# ─────────────── AI sanitizer (Wave 6.3) ───────────────


def get_ai_sanitizer_provider() -> Any:
    """Возвращает реализацию ``AISanitizerProtocol``.

    Feature-flag ``PRESIDIO_PII_ENABLED`` (S24 W1, ADR-NEW-16) переключает
    реализацию: при True используется ``PresidioSanitizerAdapter``
    (Presidio + ru NER + 4 custom recognizers); при False — legacy
    ``AIDataSanitizer`` (regex-based). Override через
    :func:`set_ai_sanitizer_provider` имеет приоритет над feature-flag.
    """
    if "ai_sanitizer" in _overrides:
        return _overrides["ai_sanitizer"]
    from src.backend.core.config.features import feature_flags

    if feature_flags.presidio_pii_enabled:
        from src.backend.services.ai.pii.presidio_analyzer import (
            get_presidio_sanitizer_adapter,
        )

        return get_presidio_sanitizer_adapter()
    module = resolve_module("security.ai_sanitizer")
    return module.get_ai_sanitizer()


def set_ai_sanitizer_provider(sanitizer: Any) -> None:
    """Установить override для ``ai_sanitizer`` provider (test-инжекция)."""
    _overrides["ai_sanitizer"] = sanitizer


# ─────────────── PII Tokenizer (Wave S25 W4, ADR-0068) ───────────────


def get_pii_tokenizer_provider() -> Any:
    """Возвращает singleton :class:`PIITokenizer` (S25 W4, ADR-NEW-21).

    Lazy-сборка из :class:`PresidioSanitizerAdapter` (S24 W1),
    :class:`RedisTokenRegistry` (S25 W4) и :class:`AuditService` (S17/K3).
    Feature-flag ``ai_pii_tokenizer_enabled`` — на стороне callers (AIGateway
    ``_resolve_sanitizer`` switch); этот provider всегда отдаёт работающий
    объект. Override через :func:`set_pii_tokenizer_provider` имеет приоритет.
    """
    if "pii_tokenizer" in _overrides:
        return _overrides["pii_tokenizer"]
    from src.backend.core.security.pii_tokenizer import PIITokenizer
    from src.backend.services.ai.pii.presidio_analyzer import (
        get_presidio_sanitizer_adapter,
    )

    return PIITokenizer(
        token_registry=_resolve_pii_token_registry(),
        audit=_resolve_unified_audit_service(),
        presidio_analyzer=get_presidio_sanitizer_adapter(),
    )


def set_pii_tokenizer_provider(impl: Any) -> None:
    """Test-override для PIITokenizer."""
    _overrides["pii_tokenizer"] = impl


# ─────────────── Agent security framework (S172 facade promotion) ───────────────


def get_agent_security_framework_provider() -> Any:
    """Возвращает singleton :class:`AgentSecurityFramework` (S172 facade).

    Lazy-провайдер для framework-фасада ``core.ai.security``. Использует
    ``@lru_cache`` singleton из самого модуля — здесь просто реэкспорт
    для консистентности с остальными DI-провайдерами (test-инжекция через
    :func:`set_agent_security_framework_provider` если потребуется).
    """
    if "agent_security_framework" in _overrides:
        return _overrides["agent_security_framework"]
    from src.backend.core.ai.security import get_agent_security_framework

    return get_agent_security_framework()


def set_agent_security_framework_provider(framework: Any) -> None:
    """Test-override для ``agent_security_framework`` provider."""
    _overrides["agent_security_framework"] = framework


def _resolve_pii_token_registry() -> Any:
    """Lazy-собирает :class:`RedisTokenRegistry` с :class:`EnvAESGCMKeyProvider`.

    Для production AES-GCM ключ читается из env ``PII_AES_KEY_V{version}``
    (base64 → 32 raw bytes). Vault-источник — carry-over в S25 closure.
    """
    from src.backend.core.di.providers.infrastructure_locator import (
        get_env_aesgcm_key_provider_class as _get_eakp_cls,
    )
    from src.backend.core.di.providers.infrastructure_locator import (
        get_redis_token_registry_class as _get_rtr_cls,
    )
    EnvAESGCMKeyProvider = _get_eakp_cls()
    RedisTokenRegistry = _get_rtr_cls()

    redis_module = resolve_module("clients.storage.redis")
    return RedisTokenRegistry(
        redis_client=redis_module.redis_client,
        key_provider=EnvAESGCMKeyProvider(current_version=1),
        audit_service=_resolve_unified_audit_service(),
    )


def _resolve_unified_audit_service() -> Any | None:
    """Lazy-резолв :class:`AuditService` (S17/K3); ``None`` при недоступности."""
    try:
        from src.backend.core.audit.facade.audit_service import (
            get_unified_audit_service,
        )

        return get_unified_audit_service()
    except Exception as _:
        return None


# ─────────────── LLM-judge metrics recorder (Wave 6.3) ───────────────


def get_llm_judge_metrics_provider() -> Any:
    """Возвращает callable ``record_llm_judge`` (см. ``LLMJudgeMetricsProtocol``).

    Реализация: ``infrastructure.observability.metrics.record_llm_judge``.
    Если функция отсутствует (минимальный профиль без prometheus_client),
    возвращается no-op.
    """
    if "llm_judge_metrics" in _overrides:
        return _overrides["llm_judge_metrics"]
    module = resolve_module("observability.metrics")
    return getattr(module, "record_llm_judge", _noop_llm_judge_metrics)


def set_llm_judge_metrics_provider(recorder: Any) -> None:
    """Установить override для ``llm_judge_metrics`` provider (test-инжекция)."""
    _overrides["llm_judge_metrics"] = recorder


def _noop_llm_judge_metrics(
    *, model: str, hallucination: float, relevance: float, toxicity: float,
) -> None:
    """Заглушка, если backend метрик недоступен."""
    return


# ─────────────── Model enum registry ───────────────


def get_model_enum_provider() -> Any:
    """Возвращает callable ``get_model_enum`` (Enum-фабрика SQLA-моделей)."""
    if "model_enum" in _overrides:
        return _overrides["model_enum"]
    module = resolve_module("database.model_registry")
    return module.get_model_enum


def set_model_enum_provider(callable_: Any) -> None:
    """Установить override для ``model_enum`` provider (test-инжекция)."""
    _overrides["model_enum"] = callable_


# ─────────────── Vault secret refresher ───────────────


def get_vault_refresher_provider() -> Any:
    """Возвращает singleton ``VaultSecretRefresher`` (см. ``VaultRefresherProtocol``)."""
    if "vault_refresher" in _overrides:
        return _overrides["vault_refresher"]
    module = resolve_module("app.vault_refresher")
    return module.VaultSecretRefresher.get()


def set_vault_refresher_provider(refresher: Any) -> None:
    """Установить override для ``vault_refresher`` provider (test-инжекция)."""
    _overrides["vault_refresher"] = refresher


# ─────────────── Antivirus service ───────────────


def get_antivirus_service_provider() -> Any:
    """Возвращает singleton ``AntivirusService``."""
    if "antivirus_service" in _overrides:
        return _overrides["antivirus_service"]
    module = resolve_module("antivirus.service")
    return module.get_antivirus_service_dependency()


def set_antivirus_service_provider(service: Any) -> None:
    """Установить override для ``antivirus_service`` provider (test-инжекция)."""
    _overrides["antivirus_service"] = service


# ─────────────── Skill registry (S202 audit fix) ───────────────


def get_skill_registry() -> Any:
    """Возвращает singleton :class:`SkillRegistry` для DSL ``skill_invoke``.

    S202 audit: ``SkillInvokeProcessor._resolve_registry`` возвращал ``None``
    (scaffold), что делало каждый ``skill_invoke`` step silent no-op.
    Composition root должен зарегистрировать singleton через
    ``app.state.skill_registry = SkillRegistry()``.

    Returns:
        :class:`SkillRegistry` или ``None`` если singleton не зарегистрирован.

    """
    try:
        from src.backend.core.di import app_state_singleton

        return app_state_singleton("skill_registry", factory=None)()
    except (ImportError, AttributeError, RuntimeError, KeyError, TypeError) as di_exc:
        # cycle-9/D-AUDIT-1000: narrow exceptions + observability.
        # ImportError — app_state_singleton missing, AttributeError — API
        # change, RuntimeError — DI unavailable, KeyError — singleton not
        # registered, TypeError — factory type.
        import logging
        logging.getLogger(__name__).debug(
            "di.providers.skill_registry_fallback",
            extra={"error": str(di_exc)},
        )
        # Round 12 fix: убрана dead-строка ``_overrides.get("_skill_registry_error")``
        # — функция и так возвращает None, ключа нигде нет, .get() ничего не делает.
        return None


# ─────────────── LLM Guard runtime (cycle-6/D-AUDIT-605) ───────────────


def get_llm_guard_runtime_provider() -> Any:
    """Возвращает singleton :class:`LlamaGuardRuntime` для ``guardrails_apply``.

    cycle-6/D-AUDIT-605: ``GuardrailsApplyProcessor._resolve_runtime`` ранее
    возвращал ``None`` hardcoded, из-за чего DSL-шаг молча превращался в
    pass-through (fail-open safety gate). Теперь резолвит runtime через
    :mod:`src.backend.core.ai.guardrails`; при сбое импорта или инстанциации
    возвращает ``None`` (callers обязаны логировать WARNING и продолжать
    silent pass-through — см. ``_resolve_runtime``).
    """
    if "llm_guard_runtime" in _overrides:
        return _overrides["llm_guard_runtime"]
    try:
        from src.backend.core.ai.guardrails import LlamaGuardRuntime

        return LlamaGuardRuntime()
    except Exception as exc:
        # `core.ai.guardrails.__init__` импортирует из несуществующего
        # `llamaguard.py` (upstream stale); не наша ответственность.
        import logging

        logging.getLogger(__name__).debug(
            "get_llm_guard_runtime_provider: LlamaGuardRuntime unavailable: %s",
            exc,
        )
        return None


def set_llm_guard_runtime_provider(impl: Any) -> None:
    """Test-override для ``llm_guard_runtime`` provider."""
    if impl is None:
        _overrides.pop("llm_guard_runtime", None)
    else:
        _overrides["llm_guard_runtime"] = impl


# ─────────────── AIGateway composition root (Sprint 1.3, ADR-NEW-19) ───────────────


@lru_cache(maxsize=1)
def _build_ai_gateway_singleton() -> Any:
    """Строит :class:`AIGateway` со всеми обязательными DI (Sprint 1.3).

    Composition-root singleton с тремя обязательными зависимостями
    (Sprint 1.3, ADR-NEW-19):
    * :class:`core.ai.policy.resolver.PolicyResolver` — резолвер
      :class:`AIPolicySpec` по ``workflow_id`` + ``tenant_id``.
    * :class:`core.security.capabilities.gate.CapabilityGate` — fail-closed
      gate для ``ai.invoke.<workflow_id>``.
    * :class:`core.tenancy.token_budget.InMemoryTokenBudgetBackend` —
      счётчик токенов для per-tenant budget enforcement
      (S172 M4 ARC-007).

    Использует существующие фасады/классы без новых абстракций.

    Returns:
        :class:`AIGateway` instance с полным DI.

    """
    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.policy.resolver import PolicyResolver
    from src.backend.core.security.capabilities.gate import CapabilityGate
    from src.backend.core.tenancy.token_budget import InMemoryTokenBudgetBackend

    return AIGateway(
        policy_resolver=PolicyResolver(),
        capability_gate=CapabilityGate(),
        token_budget=InMemoryTokenBudgetBackend(),
    )


def get_ai_gateway_provider() -> Any:
    """Возвращает :class:`AIGateway` с обязательными DI (Sprint 1.3).

    Сначала проверяет override из :func:`set_ai_gateway_provider`
    (test-инжекция); при отсутствии — лениво строит и кеширует через
    :func:`_build_ai_gateway_singleton` (``@lru_cache(maxsize=1)``).
    Callers должны вызывать :meth:`_build_ai_gateway_singleton.cache_clear`
    для сброса lru-cache между тестами.

    Returns:
        :class:`AIGateway` instance с инжектированными
        ``policy_resolver``, ``capability_gate``, ``token_budget``.

    """
    if "ai_gateway" in _overrides:
        return _overrides["ai_gateway"]
    return _build_ai_gateway_singleton()


def set_ai_gateway_provider(impl: Any) -> None:
    """Установить / сбросить override для ``ai_gateway`` provider.

    Args:
        impl: :class:`AIGateway` instance для тестового инжекта;
            ``None`` сбрасывает override (lru-cache сбрасывается
            отдельно через :func:`_build_ai_gateway_singleton.cache_clear`).

    """
    if impl is None:
        _overrides.pop("ai_gateway", None)
    else:
        _overrides["ai_gateway"] = impl


__all__ = (
    "get_agent_security_framework_provider",
    "get_ai_gateway_provider",
    "get_ai_sanitizer_provider",
    "get_antivirus_service_provider",
    "get_llm_guard_runtime_provider",
    "get_llm_judge_metrics_provider",
    "get_model_enum_provider",
    "get_pii_tokenizer_provider",
    "get_skill_registry",
    "get_vault_refresher_provider",
    "set_agent_security_framework_provider",
    "set_ai_gateway_provider",
    "set_ai_sanitizer_provider",
    "set_antivirus_service_provider",
    "set_llm_guard_runtime_provider",
    "set_llm_judge_metrics_provider",
    "set_model_enum_provider",
    "set_pii_tokenizer_provider",
    "set_vault_refresher_provider",
)
