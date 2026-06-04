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
from src.backend.core.config.features.sprint6 import Sprint6Flags
from src.backend.core.config.features.sprint7 import Sprint7Flags
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
    Sprint5DSLFlags,
    Sprint6Flags,
    Sprint7Flags,
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

    Composition (S38 P1.1 W1 — 22 mixins after T1.3.20 sprints_18_21):
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
    - Sprint5DSLFlags (Sprint 5 K3 DSL+Workflow: 25 fields, T1.3.16 → features/sprint5_dsl.py)
    - Sprint6Flags (Sprint 6 K1 Security + K2 Resilience+Perf + K3 DSL+Workflow +
      K4 AI+Quality + K5 Frontend+Chaos: 21 fields, T1.3.14 → features/sprint6.py)
    - Sprint7Flags (Sprint 7 K4 AI+RAG + K3 DSL+Workflow: 5 fields, T1.3.15 → features/sprint7.py)
    - Sprints1821Flags (Sprint 18 Operational+Security GAP + Sprint 21 Resilience & Multi-tenancy:
      18 fields, T1.3.20 → features/sprints_18_21.py)
    - Sprints2427Flags (Sprint 24 K4 AI Safety + Sprint 25 K4 AI Gateway+Policy + Sprint 26 K4 Prompts+Skills + Sprint 27 K2/K3 Agent DSL+MCP+Audit: 13 fields, T1.3.21 → features/sprints_24_27.py)
    - BaseSettingsWithLoader (settings + YAML loader)
    Total extracted: 140 flags (out of 229 total).
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

    # K1 — Auth fields (auth_joserfc, auth_mtls_client) — extracted в
    # features/auth.py::AuthFlags (T1.3.1). Наследуются через multiple
    # inheritance. См. class FeatureFlags(AuthFlags, BaseSettingsWithLoader).

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
    # dlq_unified_enabled — extracted в features/sprint5.py::Sprint5Flags (T1.3.12).

    inbox_fail_closed: bool = Field(
        default=False,
        title="K2 S5 W3: Inbox dedup fail-closed (Redis-error → InboxUnavailable)",
        description=(
            "K2 Sprint 5 Wave 3. Owner: K2 Resilience. ETA: S5-W3. "
            "При True seen_or_mark() поднимает InboxUnavailable при Redis-error "
            "вместо silently-allowing duplicate. default-OFF до stress-теста."
        ),
    )

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

    tenacity_finalized: bool = Field(
        default=False,
        title="K2 S5 W6: Tenacity unification финал (RetryPolicy/Budget → make_async_retry)",
        description=(
            "K2 Sprint 5 Wave 6. Owner: K2 Resilience. ETA: S5-W6. "
            "Активирует строгий режим: legacy RetryPolicy/RetryBudget classes "
            "поднимают DeprecationWarning. default-OFF до миграции callsites."
        ),
    )

    per_tenant_rate_limit: bool = Field(
        default=False,
        title="K2 S5 W7: per-tenant namespace в RateLimiter (scope=tenant)",
        description=(
            "K2 Sprint 5 Wave 7. Owner: K2 Resilience. ETA: S5-W7. "
            "Активирует scope=tenant key prefix в RateLimiter ключах. "
            "default-OFF до интеграции с TenantContext и smoke."
        ),
    )

    graylog_chain_enabled: bool = Field(
        default=False,
        title="K2 S5 W5: Graylog fallback chain (TCP→HTTPS→disk)",
        description=(
            "K2 Sprint 5 Wave 5. Owner: K2 Resilience. ETA: S5-W5. "
            "Активирует graylog_chain.py — fallback при недоступности Graylog: "
            "TCP-pool → HTTPS-batch → disk-rotating buffer. "
            "default-OFF до прохождения chaos-теста."
        ),
    )

    genai_chain_enabled: bool = Field(
        default=False,
        title="K2 S5 W5: GenAI provider fallback chain (primary→secondary→degraded)",
        description=(
            "K2 Sprint 5 Wave 5. Owner: K2 Resilience. ETA: S5-W5. "
            "Активирует genai_chain.py — fallback при недоступности primary "
            "LLM-провайдера: openai → anthropic → degraded local model. "
            "default-OFF до интеграции с LiteLLM gateway."
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
    workflow_versioning_routes: bool = Field(
        default=False,
        title="K3 S19 W1: workflow SemVer versioning in route.toml [requires_workflows]",
        description=(
            "K3 Sprint 19 Wave 1 (PLAN.md V22 §S19 W1, Func-rec #1). Owner: K3 DSL/Workflow. "
            'При True route.toml поддерживает секцию [requires_workflows] = { wf_name = ">=1.0,<2.0" }. '
            "RouteLoader.load() проверяет совместимость версий workflow при загрузке. "
            "RouteBuilder.invoke_workflow(name, version=...) принимает SemVer-range. "
            "Audit-event workflow.version.mismatch при несовместимости. "
            "default-OFF до integration-test на reference route."
        ),
    )

    route_composition_include: bool = Field(
        default=False,
        title="K3 S19 W2: route composition via include:/extends: с cycle detection",
        description=(
            "K3 Sprint 19 Wave 2 (PLAN.md V22 §S19 W2, Func-rec #2). Owner: K3 DSL. "
            'При True *.dsl.yaml поддерживает include: ["./common-steps.yaml"] (один уровень) '
            'и extends: "./base-route.yaml". YAML-loader разрешает дерево включений '
            "с cycle detection (RuntimeError при цикле). JSON-Schema каталог обновляется. "
            "default-OFF до DSL linter integration и smoke-test."
        ),
    )

    route_authz_requires_permission: bool = Field(
        default=False,
        title="K3 S19 W3: AuthorizationGateway route-level requires_permission",
        description=(
            "K3 Sprint 19 Wave 3 (PLAN.md V22 §S19 W3, Func-rec #3). Owner: K3 DSL/Security. "
            'При True route.toml поддерживает [security] requires_permission = ["role:admin", "scope:credit.read"]. '
            "AuthorizationGateway (S17 ADR-NEW-1) проверяет permissions перед dispatch на route. "
            "Capability-gate в RouteLoader.load() валидирует синтаксис permission-string. "
            "default-OFF до integration-test с AuthorizationGateway."
        ),
    )

    rag_multipart_ingest: bool = Field(
        default=False,
        title="K4 S19 W1: RAG bulk-ingest multipart endpoint + Streamlit UI",
        description=(
            "K4 Sprint 19 Wave 1 (PLAN.md V22 §S19 W4, Func-rec #4). Owner: K4 AI/RAG. "
            "При True активирует POST /api/v1/ai/rag/bulk-ingest multipart endpoint "
            "для bulk document upload (PDF/DOCX/TXT) + Streamlit page bulk-ingest UI. "
            "Capability rag.ingest.<collection> обязательна. "
            "default-OFF до integration-test с real documents."
        ),
    )

    reranking_pipeline_enabled: bool = Field(
        default=False,
        title="K4 S19 W2: RerankerProcessor cross-encoder reranking pipeline",
        description=(
            "K4 Sprint 19 Wave 2 (PLAN.md V22 §S19 W5, Func-rec #5). Owner: K4 AI/RAG. "
            "При True RerankerProcessor интегрируется в RagQueryProcessor (default-OFF). "
            "Поддержка cross-encoder моделей (BAAI/bge-reranker-v1.5, cohere-rerank-v3). "
            "Latency budget tracking. "
            "default-OFF до bench-test reranking accuracy +15%."
        ),
    )

    rpa_session_persistence: bool = Field(
        default=False,
        title="K5 S19 W1: RPA browser session persistence via Redis (S-L5-2 closure)",
        description=(
            "K5 Sprint 19 Wave 1 (PLAN.md V22 §S19 W6, Func-rec #6, S-L5-2 closure). Owner: K5 RPA. "
            "При True BrowserCookieStore (S21 W7) интегрируется в BrowserLaunchProcessor "
            "с lazy-restore. Redis-backed session-store key = tenant_id:session_id с cookies/auth/local-storage. "
            "TTL configurable. RPA-route routes/banking_legacy_session_demo/ как reference. "
            "default-OFF до smoke-test session persistence after browser restart."
        ),
    )

    banking_ai_processors_impl: bool = Field(
        default=False,
        title="K4 S19 W3: Banking AI processors implementation (S-L4-1 closure)",
        description=(
            "K4 Sprint 19 Wave 3 (PLAN.md V22 §S19 W8, S-L4-1 closure). Owner: K4 AI. "
            "При True реализует логику в dsl/engine/processors/ai_banking.py: "
            "KycAmlVerifyProcessor / AntiFraudScoreProcessor / CreditScoringRagProcessor / "
            "DocumentClassifierProcessor / FrancotypingProcessor — LLM call + structured output Pydantic + "
            "capability-gate ai.banking.* + audit-event + cost budget tracking. "
            "default-OFF до LLM integration smoke-tests."
        ),
    )

    banking_ai_processors_enabled: bool = Field(
        default=False,
        title="K4 S19 W3: Banking AI processors - CreditScore, FraudDetection, RiskAssessment, CustomerSegmentation, LoanEligibility",
        description=(
            "K4 Sprint 19 Wave 3 (S-L4-1 closure). Owner: K4 AI. "
            "При True активирует 5 AI-процессоров в dsl/engine/processors/ai/banking_processors.py: "
            "CreditScoreProcessor / FraudDetectionProcessor / RiskAssessmentProcessor / "
            "CustomerSegmentationProcessor / LoanEligibilityProcessor — LLM call через "
            "instructor/litellm + structured output Pydantic + capability-gate ai.llm.litellm. "
            "default-OFF до LLM integration smoke-tests."
        ),
    )

    langmem_consolidation_impl: bool = Field(
        default=False,
        title="K4 S19 W4: LangMemService.consolidate() implementation (S-L4-3 closure)",
        description=(
            "K4 Sprint 19 Wave 4 (PLAN.md V22 §S19 W9, S-L4-3 closure). Owner: K4 AI/RAG. "
            "При True реализует LangMemService.consolidate(): episodic → semantic compaction "
            "через LLM-summarisation. Интеграция с langmem package. Запуск через APScheduler "
            "daily + admin-trigger. Metrics: consolidation_count + token_usage. "
            "default-OFF до consolidation quality smoke-test."
        ),
    )

    vscode_extension_published: bool = Field(
        default=False,
        title="K5 S19 W2: VSCode extension .vsix published (ADR R1.14)",
        description=(
            "K5 Sprint 19 Wave 2 (PLAN.md V22 §S19 W10). Owner: K5 Frontend/DX. "
            "При True tools/vscode-extension/ содержит готовый .vsix: syntax highlighting + "
            "hover docs + 'Run step' CodeLens + LSP client. Private marketplace publish. "
            "default-OFF до VSCode team validation."
        ),
    )

    lsp_server_strict: bool = Field(
        default=False,
        title="K3 S19 W4: DSL LSP server YAML schema completion + diagnostics",
        description=(
            "K3 Sprint 19 Wave 4 (PLAN.md V22 §S19 W11). Owner: K3 DSL/LSP. "
            "При True tools/dsl_lsp/server.py расширяется: YAML schema completion + "
            "diagnostics через DSL Linter. Integration test pygls test-client. "
            "default-OFF до LSP smoke-test."
        ),
    )

    testkit_public_api: bool = Field(
        default=False,
        title="K5 S19 W3: src/testkit/ public API для extensions/plugin authors (S-L10-1)",
        description=(
            "K5 Sprint 19 Wave 3 (PLAN.md V22 §S19 W14, S-L10-1). Owner: K5 DX. "
            "При True src/testkit/ (NEW) предоставляет public API: RouteRunner, WorkflowRunner, "
            "MockCapabilityGateway, FakeWorkflowBackend, recorder/replay fixtures, "
            "assert_audit_event, assert_metric_recorded. Документация в docs/testkit/. "
            "default-OFF до testkit API review."
        ),
    )

    adaptive_timeout_enabled: bool = Field(
        default=False,
        title="K2 S19 W3: .policy.adaptive_timeout(percentile=99, safety_factor=1.5) builder API",
        description=(
            "K2 Sprint 19 Wave 3 (PLAN.md V22 §S19 W15). Owner: K2 Resilience. "
            "При True RouteBuilder и WorkflowBuilder поддерживают "
            ".policy.adaptive_timeout(percentile=99, safety_factor=1.5) — адаптивный "
            "timeout на основе historical latency. "
            "default-OFF до adaptive timeout smoke-test."
        ),
    )

    multi_replica_failover: bool = Field(
        default=False,
        title="K2 S19 W1: SmartSessionManager multi-replica failover (S-L6-4)",
        description=(
            "K2 Sprint 19 Wave 1 (PLAN.md V22 §S19 W10, S-L6-4). Owner: K2 Resilience. "
            "При True SmartSessionManager поддерживает multi-replica failover: "
            "replication-lag monitoring через pg_stat_replication + auto-routing по lag-budget. "
            "Chaos test (kill replica) должен проходить. "
            "default-OFF до chaos-test validation."
        ),
    )

    vault_zero_downtime_rotation: bool = Field(
        default=False,
        title="K1 S19 W1: Vault zero-downtime secret rotation (S-L6-6)",
        description=(
            "K1 Sprint 19 Wave 1 (PLAN.md V22 §S19 W10, S-L6-6). Owner: K1 Security. "
            "При True graceful Vault reconnect: сохранение старого secret N минут drift-toleration + "
            "validation новых credentials ДО активации. "
            "default-OFF до rotation smoke-test."
        ),
    )

    manage_py_diagnose: bool = Field(
        default=False,
        title="K2 S19 W2: manage.py diagnose aggregator JSON output для CI",
        description=(
            "K2 Sprint 19 Wave 2 (PLAN.md V22 §S19 W16). Owner: K2 DevOps. "
            "При True manage.py diagnose выводит JSON со status всех subsystems: "
            "db/redis/kafka/vault/llm-gateway/health/endpoints. "
            "CI-gate: diagnose JSON exit 0 только при all-healthy. "
            "default-OFF до diagnose output schema review."
        ),
    )

    current_frames_fallback: bool = Field(
        default=False,
        title="K1 S19 W2: sys._current_frames() graceful fallback для PyPy/Jython (F-6)",
        description=(
            "K1 Sprint 19 Wave 2 (PLAN.md V22 §S19 W17, F-6 carryover). Owner: K1 Security. "
            "При True tools/checks/check_deadlock.py использует sys._current_frames() "
            "с graceful fallback на PyPy/Jython (где отсутствует). "
            "default-OFF до fallback smoke-test на PyPy."
        ),
    )

    adaptive_rag_strategy_enabled: bool = Field(
        default=False,
        title="K4 S19 W6: Adaptive RAG strategy finale (dense/hybrid/hyde/multi_query)",
        description=(
            "K4 Sprint 19 Wave 6 (PLAN.md V22 §S19 W18). Owner: K4 AI/RAG. "
            "При True RagQueryProcessor расширяется: dense/hybrid/hyde/multi_query "
            "через LLM-classifier. Accuracy +15% bench. Latency <50ms. "
            "default-OFF до adaptive RAG bench validation."
        ),
    )

    ai_safety_capability_unify: bool = Field(
        default=False,
        title="K1 S19 W5: AI Safety fs.write.<scope> unified capability (ADR-NEW-16/17/18 closure)",
        description=(
            "K1 Sprint 19 Wave 5 (PLAN.md V22 §S19 W19). Owner: K1 Security/AI Safety. "
            "При True AI workspace fs.write.<scope> унифицирован: все write-operations "
            "проходят через AIWorkspaceManager с capability-checked scopes. "
            "fs.write.artifact / fs.write.session / fs.write.tenant. "
            "default-OFF до AI Safety audit."
        ),
    )

    prod_hot_reload_disable: bool = Field(
        default=False,
        title="K1 S19 W6: APP_PROFILE=prod hot-reload disabled",
        description=(
            "K1 Sprint 19 Wave 6 (PLAN.md V22 §S19 W20). Owner: K1 Security/DevOps. "
            "При True hot-reload деактивируется при APP_PROFILE=prod "
            "(settings.app.profile == 'prod'). "
            "default-OFF до prod hot-reload validation."
        ),
    )

    dsl_usage_audit_enabled: bool = Field(
        default=False,
        title="K3 S19 W6: DSL usage audit tools/audit/dsl_usage_audit.py",
        description=(
            "K3 Sprint 19 Wave 6 (PLAN.md V22 §S19 W21). Owner: K3 DSL. "
            "При True tools/audit/dsl_usage_audit.py собирает статистику использования "
            "DSL процессоров: top-20 steps, avg latency, error rate per step type. "
            "default-OFF до audit dashboard integration."
        ),
    )

    admin_react_mvp: bool = Field(
        default=False,
        title="K5 S19 W5: frontend/admin-react/ MVP (React-based admin UI)",
        description=(
            "K5 Sprint 19 Wave 5 (PLAN.md V22 §S19 W22). Owner: K5 Frontend. "
            "При True frontend/admin-react/ содержит MVP React admin UI: "
            "routes dashboard + feature-flag toggle + audit viewer. "
            "default-OFF до admin MVP review."
        ),
    )

    quick_wins_pack: bool = Field(
        default=False,
        title="K5 S19 W4: make new-adr + completions + release-notes + D3.js arch map",
        description=(
            "K5 Sprint 19 Wave 4 (PLAN.md V22 §S19 W16). Owner: K5 DX. "
            'При True: make new-adr TITLE="..." + manage.py completions install + '
            "make release-notes + frontend/streamlit_app/pages/05_Architecture_Map.py (D3.js). "
            "default-OFF до quick-wins review."
        ),
    )


feature_flags = FeatureFlags()
