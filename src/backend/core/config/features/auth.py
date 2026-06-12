"""Auth feature-flags (T1.3.1 split from core.config.features.__init__).

Извлечено 2 K1 — Auth flags (S38 P1.1 epic, T1.3.1 PR). Pattern: each
domain имеет свой ``<Domain>Flags(BaseSettings)`` subclass. ``__init__.py``
композирует их через multiple inheritance в единый ``FeatureFlags`` class
с сохранением public API (``feature_flags.X``).

Future T1.3.1+ extensions (deferred to S39+):
- authz_gateway_enabled (S17 W2)
- tenant_token_budget_enabled (S9)
- route_authz_requires_permission (S19 W3)
- ai_pii_tokenizer_enabled (S25 W4, K1 PII adjacent)
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthFlags(BaseSettings):
    """K1 — Auth (Wave 1+3). Owner: K1 Auth.

    Per S38 T1.3.1, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.auth import AuthFlags
        class FeatureFlags(AuthFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    # S68 W1: auth_mtls_client остаётся (НЕ удалён в scope W1 — ТОЛЬКО
    # auth_joserfc). Subagent S68 W1 случайно удалил оба; orchestrator
    # restore, чтобы не ломать 2 pre-existing tests.
    auth_mtls_client: bool = False


__all__ = ("AuthFlags",)
