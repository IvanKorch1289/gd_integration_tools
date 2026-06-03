"""Experimental feature-flags (T1.3.9 split from core.config.features.__init__).

Извлечено 7 flags из 4 sections (S38 P1.1 epic, T1.3.9 PR):
- K7 — EventBus (2 fields): eventbus_facade, eventbus_file_watcher
- Sprint 4 (2 fields): activity_capability_gate_enabled, ai_workflow_activity_enabled
- Sprint 7 T5 (1 field): openfeature_external
- K1 — Plugin semver (1 field): plugin_semver_strict
- Sprint 5 K5 Frontend (1 field): frontend_plugin_marketplace

Final domain split (9 of 9) for S38 P1.1 W1 T1.3.x. T1.4 (shim) follows.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExperimentalFlags(BaseSettings):
    """K7 EventBus + Sprint 4/5/7 T5 + K1 Plugin semver. Owner: multi-team.

    Per S38 T1.3.9, извлечено из monolithic ``core.config.features.FeatureFlags``
    для eventual multi-inheritance split (9 доменов, 10 PRs).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.experimental import ExperimentalFlags
        class FeatureFlags(..., ExperimentalFlags, ...):
            ...

    Env-var prefix: ``FEATURE_`` (inherited from parent pydantic-settings config).
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    eventbus_facade: bool = Field(
        default=False,
        title="EventBus: единая абстракция (Kafka/RabbitMQ/NATS)",
        description=(
            "K7 Wave 1. Owner: K7 EventBus. ETA: S2-W1. "
            "Активирует EventBusBackend ABC + 3 backend'а. "
            "default-OFF до прохождения shared protocol-тестов."
        ),
    )

    eventbus_file_watcher: bool = Field(
        default=False,
        title="EventBus: FileWatcherSource через watchfiles.awatch",
        description=(
            "K7 Wave 4. Owner: K7 EventBus. ETA: S2-W4. "
            "Активирует регистрацию FileWatcherSource в routes-discovery. "
            "default-OFF до подключения в reference route."
        ),
    )

    activity_capability_gate_enabled: bool = Field(
        default=False,
        title="Sprint 4 Wave E: capability-проверка для Temporal activities",
        description=(
            "K1 Sprint 4 Wave E. Включает CapabilityGate-проверку до вызова "
            "Temporal-activity (V15 R-V15-1). При False декоратор "
            "capability_guarded_activity превращается в NoOp. "
            "default-OFF до интеграции с PluginLoaderV11 runtime-контекстом."
        ),
    )

    ai_workflow_activity_enabled: bool = Field(
        default=False,
        title="Sprint 4 Wave C: LLM-activity wrapper для Temporal",
        description=(
            "K4 Sprint 4 Wave C. Включает регистрацию llm_activity в Temporal "
            "Worker через register_llm_activity(). При False регистрация — "
            "NoOp; activity-функция импортируется, но не подключается. "
            "default-OFF до staging-теста с реальным LiteLLM gateway."
        ),
    )

    openfeature_external: bool = Field(
        default=False,
        title="Sprint 7 T5: OpenFeature external provider (Flagsmith)",
        description=(
            "Sprint 7 Team T5. Owner: T5 Plugin/Platform. ETA: S7. "
            "При True FlagsmithProvider начинает резолвить feature-flag из "
            "external Flagsmith instance (per-tenant scope через "
            "EvaluationContext). При False — все resolve_* возвращают default, "
            "приложение использует только локальный feature_flags.<name>. "
            "default-OFF до развёртывания Flagsmith instance и smoke-теста."
        ),
    )

    plugin_semver_strict: bool = Field(
        default=False,
        title="K1: Plugin semver strict-режим (requires_core обязан иметь верхний bound)",
        description=(
            "K1 Wave 5 (S3-W5). Owner: K1 Plugin/Platform. ETA: S3-W5. "
            "При True check_plugin_semver() и semver_checker дополнительно проверяют, "
            "что requires_core содержит явный верхний ограничитель (<X.Y или ~=X.Y). "
            "default-OFF до завершения аудита всех plugin.toml манифестов."
        ),
    )

    frontend_plugin_marketplace: bool = Field(
        default=False,
        title="K5: Plugin Marketplace Streamlit UI (таблица плагинов + toggle)",
        description=(
            "K5 Wave 3. Owner: K5 DSL. ETA: S3-W3. "
            "Активирует страницу 60_Plugin_Marketplace.py — список installed plugins, "
            "фильтр по status (active/all/disabled), manifest-expander, action-toggle. "
            "default-OFF до staging-smoke + REST /api/v1/admin/plugins/* endpoints."
        ),
    )


__all__ = ("ExperimentalFlags",)
