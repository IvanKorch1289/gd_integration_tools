"""Единый реестр feature-flag'ов проекта.

Назначение:
    Централизованное место для всех runtime feature-flag'ов, влияющих на
    поведение приложения. По правилу проекта (PLAN.md V18.1, git-модель):
    любой новый код, влияющий на runtime — под default-OFF feature-flag.

Принципы:
    - default-OFF для всех новых flag'ов;
    - переход на default-ON — отдельным PR с указанием Wave/staging-smoke;
    - переменная окружения переопределяет default;
    - flag-deprecation — отдельный шаг (после Wave закрытия) с TODO в коде.

Использование:
    Через pydantic-settings (env_prefix=FEATURE_):

        from src.backend.core.config.features import feature_flags

        if feature_flags.waf_outbound_via_facade:
            await OutboundHttpClient.request(...)
        else:
            await httpx_legacy.request(...)

Аудит:
    tools/checks/check_feature_flags.py --strict проверяет, что все
    feature-flag, упомянутые в коде через `feature_flags.<name>`, имеют
    запись в этом модуле и соответствующий audit-комментарий.

Package structure (S38 T1.3.0)
------------------------------
Файл мигрирован ``git mv features.py → features/__init__.py`` (2026-06-03,
T1.3.0). 884 import sites работают без изменений (``from features import X``
эквивалентно ``from features/__init__.py import X``).

Planned subdomain layout (T1.3.1+, итеративно по 1 домену за PR):

    src/backend/core/config/features/
    ├── __init__.py     # this file (canonical feature_flags singleton)
    ├── auth.py         # ~15 flags: K1 security/auth (T1.3.1)
    ├── security.py     # ~15 flags: PII, secrets, jwt (T1.3.2)
    ├── resilience.py   # ~35 flags: CB, rate-limit, fallback (T1.3.3)
    ├── observability.py# ~10 flags: metrics, tracing, audit (T1.3.4)
    ├── net.py          # ~8 flags: HTTP, retries, timeouts (T1.3.5)
    ├── workflow.py     # ~10 flags: scheduler, pg_runner (T1.3.6)
    ├── ai.py           # ~70 flags: gateway, LLM, sanitizer (T1.3.7)
    ├── dsl.py          # ~70 flags: route builders, processors (T1.3.8)
    └── experimental.py # ~10 flags: K5 quick-wins (T1.3.9)

Re-export pattern: каждый submodule export свой ``*_flags`` BaseSettings
subclass; ``__init__.py`` собирает их в единый :class:`FeatureFlags` (pydantic
multi-inheritance composition) с сохранением public API.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader
from src.backend.core.config.features.ai import AIFlags
from src.backend.core.config.features.ai_rag import AIRAGFlags
from src.backend.core.config.features.auth import AuthFlags
from src.backend.core.config.features.billing import BillingFlags
from src.backend.core.config.features.dsl import DSLFlags
from src.backend.core.config.features.experimental import ExperimentalFlags
from src.backend.core.config.features.infrastructure import InfrastructureFlags
from src.backend.core.config.features.net import NetFlags
from src.backend.core.config.features.observability import ObservabilityFlags
from src.backend.core.config.features.plugins import PluginsFlags
from src.backend.core.config.features.resilience import ResilienceFlags
from src.backend.core.config.features.security import SecurityFlags
from src.backend.core.config.features.sprint5 import Sprint5Flags
from src.backend.core.config.features.sprint5_dsl import Sprint5DSLFlags
from src.backend.core.config.features.sprint5_k2 import Sprint5K2Flags
from src.backend.core.config.features.sprint6 import Sprint6Flags
from src.backend.core.config.features.sprint7 import Sprint7Flags
from src.backend.core.config.features.sprint19_ai import Sprint19AIFlags
from src.backend.core.config.features.sprint19_dx import Sprint19DXFlags
from src.backend.core.config.features.sprints_15_17 import Sprints1517Flags
from src.backend.core.config.features.sprints_18_21 import Sprints1821Flags
from src.backend.core.config.features.sprints_24_27 import Sprints2427Flags
from src.backend.core.config.features.workflow import WorkflowFlags

__all__ = ("FeatureFlags", "feature_flags")


class FeatureFlags(
    AuthFlags,
    SecurityFlags,
    ObservabilityFlags,
    NetFlags,
    PluginsFlags,
    WorkflowFlags,
    AIFlags,
    AIRAGFlags,
    DSLFlags,
    ExperimentalFlags,
    InfrastructureFlags,
    ResilienceFlags,
    BillingFlags,
    Sprint5Flags,
    Sprint5K2Flags,
    Sprint5DSLFlags,
    Sprint6Flags,
    Sprint7Flags,
    Sprint19AIFlags,
    Sprint19DXFlags,
    Sprints1517Flags,
    Sprints1821Flags,
    Sprints2427Flags,
    BaseSettingsWithLoader,
):
    """Реестр runtime feature-flag.

    Все flag — default-OFF. Имя поля → переменная окружения с префиксом FEATURE_,
    верхним регистром (waf_outbound_via_facade → FEATURE_WAF_OUTBOUND_VIA_FACADE).

    После закрытия Wave и подтверждения staging-smoke owner-команда переводит
    flag в default-ON в отдельном PR с обновлением audit-комментария.

    Composition (S38 P1.1 W1 — 22 mixins after T1.3.24 sprint19_ai):
    - AuthFlags (K1 — Auth: 2 fields, T1.3.1 → features/auth.py)
    - SecurityFlags (K1 — Secrets & Vault: 1 field, T1.3.2 → features/security.py)
    - ObservabilityFlags (K1 Tracing + K8 Audit: 2 fields, T1.3.4 → features/observability.py)
    - NetFlags (K2 — Net & WAF: 3 fields, T1.3.5 → features/net.py)
    - PluginsFlags (K9 Extensions + T3 S7: 2 fields, T1.3.13 → features/plugins.py)
    - WorkflowFlags (K4 — Workflow: 4 fields, T1.3.6 → features/workflow.py)
    - AIFlags (K6 — AI: 9 fields, T1.3.7 → features/ai.py)
    - AIRAGFlags (Sprint 11 AI/RAG Completion + Sprint 12 Workflow Enhancement:
      29 fields, T1.3.18 → features/ai_rag.py)
    - DSLFlags (K5 DSL + K3 sources: 12 fields, T1.3.8 → features/dsl.py)
    - ExperimentalFlags (K7 EventBus + Sprint 4/5/7 T5 + K1 Plugin: 7 fields, T1.3.9 → features/experimental.py)
    - InfrastructureFlags (Sprint 5 K4 AI+RAG + K5 Frontend + Sprint 8 Rule Engine + HTTP/3 +
      Sprint 9 GAP closure + Sprint 10 DSL Blueprint: 26 fields, T1.3.17 → features/infrastructure.py)
    - ResilienceFlags (K3 Resilience + K8 Storage: 6 fields, T1.3.10 → features/resilience.py)
    - BillingFlags (Sprint 7 K1 per-tenant + K9 Extensions: 4 fields, T1.3.11 → features/billing.py)
    - Sprint5Flags (Sprint 5 K1 Security + K2 DLQ: 4 fields, T1.3.12 → features/sprint5.py)
    - Sprint5K2Flags (Sprint 5 K2 Resilience+Perf: 5 fields, T1.3.22 → features/sprint5_k2.py)
    - Sprint5DSLFlags (Sprint 5 K3 DSL+Workflow: 25 fields, T1.3.16 → features/sprint5_dsl.py)
    - Sprint6Flags (Sprint 6 K1 Security + K2 Resilience+Perf + K3 DSL+Workflow +
      K4 AI+Quality + K5 Frontend+Chaos: 21 fields, T1.3.14 → features/sprint6.py)
    - Sprint7Flags (Sprint 7 K4 AI+RAG + K3 DSL+Workflow: 5 fields, T1.3.15 → features/sprint7.py)
    - Sprint19AIFlags (Sprint 19 K1 Security + K2 Resilience + K4 AI/RAG + K5 Frontend/DX:
      11 fields, T1.3.24 → features/sprint19_ai.py)
    - Sprint19DXFlags (Sprint 19 DSL+AI Extensions + DX first 12 of 23 fields:
      12 fields, T1.3.23 → features/sprint19_dx.py)
    - Sprints1821Flags (Sprint 18 Operational+Security GAP + Sprint 21 Resilience & Multi-tenancy:
      18 fields, T1.3.20 → features/sprints_18_21.py)
    - Sprints2427Flags (Sprint 24 K4 AI Safety + Sprint 25 K4 AI Gateway+Policy + Sprint 26 K4 Prompts+Skills + Sprint 27 K2/K3 Agent DSL+MCP+Audit: 13 fields, T1.3.21 → features/sprints_24_27.py)
    - BaseSettingsWithLoader (settings + YAML loader)
    Total extracted: 145 flags (out of 229 total).
    Remaining: 102 flags в __init__.py (Sprint 15/17/19 + etc).
    T1.3.19+ future domains: ai_advanced.py, observability_advanced.py, etc.
    """

    yaml_group: ClassVar[str] = "features"
    model_config = SettingsConfigDict(
        env_prefix="FEATURE_", extra="forbid", validate_default=True
    )

    # K2 — Net & WAF fields (metering_per_host, connection_reuse_manager,
    # waf_outbound_via_facade) — extracted в features/net.py::NetFlags (T1.3.5).
    # Наследуются через multiple inheritance. См. class FeatureFlags(...).

    # K4 — Workflow fields (workflow_legacy_disabled, workflow_yaml_round_trip,
    # workflow_bpmn_import, workflow_gateways_enabled) — extracted в
    # features/workflow.py::WorkflowFlags (T1.3.6). Наследуются через
    # multiple inheritance. См. class FeatureFlags(...).

    # K5 — DSL fields (frontend_schema_registry_ui, frontend_action_bus_ui,
    # dsl_processor_registry_strict, dsl_route_hot_reload, lsp_server_published,
    # admin_marketplace_endpoints, dsl_visual_editor_enabled) +
    # K3 — sources (builder_source_sugar, service_toml_loader,
    # graphql_subscription_source, email_imap_source, notification_dsl_enabled)
    # — extracted в features/dsl.py::DSLFlags (T1.3.8). Наследуются через
    # multiple inheritance. См. class FeatureFlags(...).

    # K3 — Resilience & Scaling + K8 Storage fields — extracted в
    # features/resilience.py::ResilienceFlags (T1.3.10). Наследуются
    # через multiple inheritance. См. class FeatureFlags(...).

    # K7 — EventBus + Sprint 4 + Sprint 7 T5 + K1 Plugin semver +
    # Sprint 5 K5 Frontend fields — extracted в
    # features/experimental.py::ExperimentalFlags (T1.3.9). Наследуются
    # через multiple inheritance. См. class FeatureFlags(...).

    # K1 — Tracing + K8 — Audit (см. observability.py comment выше)

    # K1 — Tracing & Observability fields (tracing_baggage_strict) +
    # K8 — Audit & ClickHouse fields (audit_clickhouse_enabled) — extracted в
    # features/observability.py::ObservabilityFlags (T1.3.4). Наследуются
    # через multiple inheritance. См. class FeatureFlags(AuthFlags,
    # SecurityFlags, ObservabilityFlags, BaseSettingsWithLoader).

    # Sprint 7 K1 per-tenant billing/quotas + K9 — Extensions fields —
    # extracted в features/billing.py::BillingFlags (T1.3.11). Наследуются
    # через multiple inheritance. См. class FeatureFlags(...).

    # K1 — Plugin semver (plugin_semver_strict) +
    # Sprint 7 T5 OpenFeature (openfeature_external) — extracted в
    # features/experimental.py::ExperimentalFlags (T1.3.9). См. comment
    # выше в EventBus block.

    # K1 — Auth fields (auth_mtls_client) — extracted в
    # features/auth.py::AuthFlags (T1.3.1). Наследуются через multiple
    # inheritance. См. class FeatureFlags(AuthFlags, BaseSettingsWithLoader).
    # NOTE (S68 W1): auth_joserfc field удалён (S67 W2 сделал flag no-op
    # после deletion ``jwt_backend_joserfc.py`` shim). TD-S67-feature-flag-deprecation.

    # Sprint 5 K1 Security + K2 DLQ fields — extracted в
    # features/sprint5.py::Sprint5Flags (T1.3.12). Наследуются через
    # multiple inheritance. См. class FeatureFlags(...).

    # K9 — Plugins fields (extensions_credit_workflow, credit_pipeline_v2) —
    # extracted в features/plugins.py::PluginsFlags (T1.3.13). Наследуются
    # через multiple inheritance. См. class FeatureFlags(...).

    # ─── Sprint 5 — К1 Security ───────────────────────────────────────────
    # dlq_replay_rbac + inbox_audit_pii_mask — extracted в
    # features/sprint5.py::Sprint5Flags (T1.3.12). См. comment выше.

    # ─── Sprint 5 — К2 Resilience+Perf ─────────────────────────────────────
    # 5 bool fields (inbox_fail_closed, tenacity_finalized, per_tenant_rate_limit,
    # graylog_chain_enabled, genai_chain_enabled) — extracted в
    # features/sprint5_k2.py::Sprint5K2Flags (T1.3.22). Наследуются
    # через multiple inheritance. scheduler_backend (Literal) сохранён
    # inline как config type.

    scheduler_backend: Literal["apscheduler", "temporal"] = Field(
        default="apscheduler",
        title="S18 W0: выбор SchedulerBackend (APScheduler default / Temporal stub)",
        description=(
            "Sprint 18 W0 [wave:s18/w0-goal-driven-sweep-8-scheduler-backend-protocol]. "
            "Owner: K2 Platform. Выбор реализации :class:`SchedulerBackend` "
            "из :mod:`core.interfaces.scheduler`. 'apscheduler' — стабильный "
            "production-путь поверх SchedulerManager. 'temporal' — stub "
            "(NotImplementedError) до реализации Temporal Schedule API."
        ),
    )

    # Sprint 5 — К3 DSL+Workflow fields — extracted в
    # features/sprint5_dsl.py::Sprint5DSLFlags (T1.3.16). Наследуются
    # через multiple inheritance. См. class FeatureFlags(...).

    # Sprint 5 K4 AI+RAG (9 fields) — extracted в features/infrastructure.py::InfrastructureFlags
    # (T1.3.17). Наследуются через multiple inheritance. См. class FeatureFlags(...).

    # Sprint 5 K5 Frontend (3 fields) — extracted в features/infrastructure.py::InfrastructureFlags
    # (T1.3.17). Наследуются через multiple inheritance. См. class FeatureFlags(...).

    # Sprint 10 DSL Blueprint (5 fields) — extracted в features/infrastructure.py::InfrastructureFlags
    # (T1.3.17). Наследуются через multiple inheritance. См. class FeatureFlags(...).

    # ─── Sprint 15 — DX Tooling + Innovation + Sprint 17 GAP P0 Closure ───
    # 17 flags (5 + 12) extracted в features/sprints_15_17.py::Sprints1517Flags
    # (T1.3.19). Наследуются через multiple inheritance. См. class FeatureFlags(...).

    # Sprint 21 fields — extracted в features/sprints_18_21.py::Sprints1821Flags (T1.3.20).

    # ─── K4 — Sprint 24-27 (S24 AI Safety + S25 AI Gateway/Policy + S26 Prompts/Skills + S27 Agent DSL/MCP/Audit) ───
    # 13 fields extracted в features/sprints_24_27.py::Sprints2427Flags (S38 T1.3.21). Наследуются через multiple inheritance.
    # См. class FeatureFlags(..., Sprints2427Flags, ...).

    # Sprint 18 fields — extracted в features/sprints_18_21.py::Sprints1821Flags (T1.3.20).

    # ─── Sprint 19 — DSL+AI Extensions + DX ────────────────────────────────
    # Sprint 19 DSL+AI Extensions + DX — first 12 of 23 fields extracted в
    # features/sprint19_dx.py::Sprint19DXFlags (S38 T1.3.23). Наследуются
    # через multiple inheritance. См. class FeatureFlags(..., Sprint19DXFlags, ...).
    # Remaining 11 Sprint 19 fields (K1 Security + K2 Resilience + K4 AI/RAG + K5 Frontend/DX):
    # adaptive_timeout_enabled, multi_replica_failover, vault_zero_downtime_rotation,
    # manage_py_diagnose, current_frames_fallback, adaptive_rag_strategy_enabled,
    # ai_safety_capability_unify, prod_hot_reload_disable, dsl_usage_audit_enabled,
    # admin_react_mvp, quick_wins_pack — extracted в features/sprint19_ai.py (T1.3.24).

    # ─── Sprint 19 — вторая половина (K1 Security + K2 Resilience + K4 AI/RAG + K5 Frontend/DX) ──
    # 11 bool fields (adaptive_timeout_enabled, multi_replica_failover, vault_zero_downtime_rotation,
    # manage_py_diagnose, current_frames_fallback, adaptive_rag_strategy_enabled,
    # ai_safety_capability_unify, prod_hot_reload_disable, dsl_usage_audit_enabled,
    # admin_react_mvp, quick_wins_pack) — extracted в
    # features/sprint19_ai.py::Sprint19AIFlags (T1.3.24). Наследуются через
    # multiple inheritance. См. class FeatureFlags(..., Sprint19AIFlags, ...).
    # (Владение wave: S19 W1..W22 из K1/K2/K4/K5; подробное распределение — в sprint19_ai.py.)


feature_flags = FeatureFlags()
