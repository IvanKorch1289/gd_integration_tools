"""K9 Extensions plugins feature-flags (T1.3.13 split from core.config.features.__init__).

Извлечено 2 flags (S38 P1.1 W1 T1.3.13):
- K9 Wave 4 (1):
  - extensions_credit_workflow (K9 Wave 4, credit_workflow первый reference plugin)
- T3 Sprint 7 (1):
  - credit_pipeline_v2 (T3 S7, credit_pipeline plugin (SKB/НБКИ) — V11 layout)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PluginsFlags(BaseSettings):
    """K9 Extensions + T3 Sprint 7 plugins. Owner: K9 Frontend&Ext, T3.

    Per S38 T1.3.13, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.plugins import PluginsFlags
        class FeatureFlags(..., PluginsFlags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    extensions_credit_workflow: bool = Field(
        default=False,
        title="Extensions: credit_workflow первый reference plugin",
        description=(
            "K9 Wave 4. Owner: K9 Frontend&Ext. ETA: S2-W4. "
            "Активирует extensions/credit_workflow/ как первый business plugin. "
            "default-OFF до запуска reference workflow через Temporal."
        ),
    )

    credit_pipeline_v2: bool = Field(
        default=False,
        title="T3 S7: credit_pipeline plugin (SKB/НБКИ) — V11 layout",
        description=(
            "Sprint 7 Team T3. Owner: T3. Активирует "
            "extensions/credit_pipeline/* как канонический credit-bus "
            "(SKB-Техно клиент через BaseExternalAPIClient + WAF) + "
            "Workflow DSL credit_assessment + DSL routes. "
            "При False — используется legacy services/integrations/skb.py. "
            "default-OFF до завершения миграции (Sprint 8 flip ON)."
        ),
    )


__all__ = ("PluginsFlags",)
