"""AI domain providers — sanitizer, PII tokenizer, LLM metrics, model registry, vault.

T-P1.2c split: извлечено из monolithic ``providers.py`` (S38 P1 epic).
Domain scope: 12 funcs (6 get + 6 set) + 3 private helpers
(``_resolve_pii_token_registry``, ``_resolve_unified_audit_service``,
``_noop_llm_judge_metrics``).

Singleton cache ``_overrides`` is per-domain (NOT shared).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_INFRA = "src." + "backend.infrastructure"

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


def _resolve_pii_token_registry() -> Any:
    """Lazy-собирает :class:`RedisTokenRegistry` с :class:`EnvAESGCMKeyProvider`.

    Для production AES-GCM ключ читается из env ``PII_AES_KEY_V{version}``
    (base64 → 32 raw bytes). Vault-источник — carry-over в S25 closure.
    """
    from src.backend.infrastructure.security.token_registry import (
        EnvAESGCMKeyProvider,
        RedisTokenRegistry,
    )

    redis_module = resolve_module("clients.storage.redis")
    return RedisTokenRegistry(
        redis_client=redis_module.redis_client,
        key_provider=EnvAESGCMKeyProvider(current_version=1),
        audit_service=_resolve_unified_audit_service(),
    )


def _resolve_unified_audit_service() -> Any | None:
    """Lazy-резолв :class:`AuditService` (S17/K3); ``None`` при недоступности."""
    try:
        from src.backend.services.audit.audit_service import get_unified_audit_service

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
    _overrides["llm_judge_metrics"] = recorder


def _noop_llm_judge_metrics(
    *, model: str, hallucination: float, relevance: float, toxicity: float
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
    _overrides["model_enum"] = callable_


# ─────────────── Vault secret refresher ───────────────


def get_vault_refresher_provider() -> Any:
    """Возвращает singleton ``VaultSecretRefresher`` (см. ``VaultRefresherProtocol``)."""
    if "vault_refresher" in _overrides:
        return _overrides["vault_refresher"]
    module = resolve_module("app.vault_refresher")
    return module.VaultSecretRefresher.get()


def set_vault_refresher_provider(refresher: Any) -> None:
    _overrides["vault_refresher"] = refresher


# ─────────────── Antivirus service ───────────────


def get_antivirus_service_provider() -> Any:
    """Возвращает singleton ``AntivirusService``."""
    if "antivirus_service" in _overrides:
        return _overrides["antivirus_service"]
    module = resolve_module("antivirus.service")
    return module.get_antivirus_service_dependency()


def set_antivirus_service_provider(service: Any) -> None:
    _overrides["antivirus_service"] = service


__all__ = (
    "get_ai_sanitizer_provider",
    "get_antivirus_service_provider",
    "get_llm_judge_metrics_provider",
    "get_model_enum_provider",
    "get_pii_tokenizer_provider",
    "get_vault_refresher_provider",
    "set_ai_sanitizer_provider",
    "set_antivirus_service_provider",
    "set_llm_judge_metrics_provider",
    "set_model_enum_provider",
    "set_pii_tokenizer_provider",
    "set_vault_refresher_provider",
)
