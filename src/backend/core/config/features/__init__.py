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
from src.backend.core.config.features.auth import AuthFlags
from src.backend.core.config.features.dsl import DSLFlags
from src.backend.core.config.features.experimental import ExperimentalFlags
from src.backend.core.config.features.net import NetFlags
from src.backend.core.config.features.observability import ObservabilityFlags
from src.backend.core.config.features.resilience import ResilienceFlags
from src.backend.core.config.features.security import SecurityFlags
from src.backend.core.config.features.workflow import WorkflowFlags

__all__ = ("FeatureFlags", "feature_flags")


class FeatureFlags(
    AuthFlags,
    SecurityFlags,
    ObservabilityFlags,
    NetFlags,
    WorkflowFlags,
    AIFlags,
    DSLFlags,
    ExperimentalFlags,
    ResilienceFlags,
    BaseSettingsWithLoader,
):
    """Реестр runtime feature-flag.

    Все flag — default-OFF. Имя поля → переменная окружения с префиксом FEATURE_,
    верхним регистром (waf_outbound_via_facade → FEATURE_WAF_OUTBOUND_VIA_FACADE).

    После закрытия Wave и подтверждения staging-smoke owner-команда переводит
    flag в default-ON в отдельном PR с обновлением audit-комментария.

    Composition (S38 P1.1 W1 — original 9 + 1 extension):
    - AuthFlags (K1 — Auth: 2 fields, T1.3.1 → features/auth.py)
    - SecurityFlags (K1 — Secrets & Vault: 1 field, T1.3.2 → features/security.py)
    - ObservabilityFlags (K1 Tracing + K8 Audit: 2 fields, T1.3.4 → features/observability.py)
    - NetFlags (K2 — Net & WAF: 3 fields, T1.3.5 → features/net.py)
    - WorkflowFlags (K4 — Workflow: 4 fields, T1.3.6 → features/workflow.py)
    - AIFlags (K6 — AI: 9 fields, T1.3.7 → features/ai.py)
    - DSLFlags (K5 DSL + K3 sources: 12 fields, T1.3.8 → features/dsl.py)
    - ExperimentalFlags (K7 EventBus + Sprint 4/5/7 T5 + K1 Plugin: 7 fields, T1.3.9 → features/experimental.py)
    - ResilienceFlags (K3 Resilience + K8 Storage: 6 fields, T1.3.10 → features/resilience.py)
    - BaseSettingsWithLoader (settings + YAML loader)

    Total extracted: 46 flags (out of 229 total).
    Remaining: 183 flags в __init__.py (Sprint 5/6/7/8/9/10/11/15/17/21 + K9 + etc).
    T1.3.11+ future domains: extensions.py, billing.py, etc.
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

    # ─── Sprint 7 K1 — per-tenant billing/quotas ──────────────────────────
    per_tenant_billing_enabled: bool = Field(
        default=False,
        title="K1 S7: per-tenant billing/quotas (rpm/rpd/tokens/cost_usd)",
        description=(
            "K1 Sprint 7. Owner: K1 Security. ETA: S7. "
            "Активирует QuotasService (src/backend/services/billing/) и "
            "QuotaCheckMiddleware (src/backend/core/auth/quotas.py) — "
            "проверку per-tenant rpm/rpd/tokens/cost_usd на HTTP-уровне. "
            "При False сервис превращается в no-op (allowed=True для всех). "
            "default-OFF до интеграции с TenantContext + Redis backend и smoke."
        ),
    )

    supply_chain_finale_strict: bool = Field(
        default=False,
        title="K1 S7: supply-chain finale (cosign sign для SBOM+wheels+image)",
        description=(
            "K1 Sprint 7. Owner: K1 Security. ETA: S7. "
            "Активирует strict-режим supply-chain-finale в "
            "tools/checks/check_supply_chain.py — cosign-sign для всех "
            "release-артефактов (SBOM, dist/*.whl, container image при "
            "наличии docker buildx). default-OFF до проверки полного pipeline "
            "и signing keys readiness."
        ),
    )

    openfeature_flagsmith_backend: bool = Field(
        default=False,
        title="K1 S7: OpenFeature SDK через FlagsmithProvider (external)",
        description=(
            "K1 Sprint 7. Owner: K1 Security. ETA: S7. "
            "Активирует миграцию feature-flag backend с InMemoryProvider на "
            "external Flagsmith через core/feature_flags/openfeature_provider.py. "
            "Управляется ENV FEATURE_FLAG_BACKEND=flagsmith. При False — "
            "in-memory provider (поведение совпадает с локальным реестром). "
            "default-OFF до развёртывания Flagsmith instance в staging."
        ),
    )

    # K1 — Plugin semver (plugin_semver_strict) +
    # Sprint 7 T5 OpenFeature (openfeature_external) — extracted в
    # features/experimental.py::ExperimentalFlags (T1.3.9). См. comment
    # выше в EventBus block.

    # K1 — Auth fields (auth_joserfc, auth_mtls_client) — extracted в
    # features/auth.py::AuthFlags (T1.3.1). Наследуются через multiple
    # inheritance. См. class FeatureFlags(AuthFlags, BaseSettingsWithLoader).

    supply_chain_ci_gate: bool = Field(
        default=False,
        title="K1: Supply-chain CI gate (SBOM + pip-audit + cosign)",
        description=(
            "K1 Wave 3. Owner: K1 Auth/Secrets. ETA: S3-W3. "
            "Активирует обязательные supply-chain проверки в release pipeline: "
            "CycloneDX SBOM генерация, pip-audit vulnerability scan, "
            "cosign artifact signing. При False — gates пропускаются (warn-only). "
            "default-OFF до Sprint 4 release-pipeline интеграции (BLOCKER #4)."
        ),
    )

    # K1 — Tracing & Observability + K8 — Audit fields — extracted в
    # features/observability.py::ObservabilityFlags (T1.3.4).

    # Sprint 5 K5 Frontend (frontend_plugin_marketplace) — extracted в
    # features/experimental.py::ExperimentalFlags (T1.3.9).

    # ─── K9 — Extensions Migration ─────────────────────────────────────────
    extensions_core_entities: bool = Field(
        default=False,
        title="Extensions: core_entities (users/orders/orderkinds/files) вынесен",
        description=(
            "K9 Wave 3. Owner: K9 Frontend&Ext. ETA: S2-W3. "
            "При True ядро НЕ регистрирует CRUD из extensions/core_entities/. "
            "default-OFF до golden-test migration + ядро без импортов."
        ),
    )

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

    # ─── Sprint 5 — К1 Security ───────────────────────────────────────────
    dlq_replay_rbac: bool = Field(
        default=False,
        title="K1 S5 W4: DLQ replay endpoint @require_role admin + audit-event",
        description=(
            "K1 Sprint 5 Wave 4. Owner: K1 Security. ETA: S5-W4. "
            "Активирует RBAC-проверку для /api/v1/admin/dlq/replay endpoint: "
            "@require_role('admin') + audit-event + @capability_guarded. "
            "default-OFF до интеграции с CasbinAuthorizationService и smoke-теста."
        ),
    )

    inbox_audit_pii_mask: bool = Field(
        default=False,
        title="K1 S5 W5: Inbox dedup audit с PII masking через presidio",
        description=(
            "K1 Sprint 5 Wave 5. Owner: K1 Security. ETA: S5-W5. "
            "Активирует PII-маскировку (presidio) для audit-записей Inbox dedup. "
            "default-OFF до интеграции с PresidioAnalyzer и audit_events."
        ),
    )

    # ─── Sprint 5 — К2 Resilience+Perf ────────────────────────────────────
    dlq_unified_enabled: bool = Field(
        default=False,
        title="K2 S5 W2: DLQ transport-agnostic facade + Postgres dlq_events",
        description=(
            "K2 Sprint 5 Wave 2. Owner: K2 Resilience. ETA: S5-W2. "
            "Активирует UnifiedDeadLetterQueue (core/messaging/dlq.py) + "
            "Postgres-table dlq_events(transport,action,payload,error,...) + "
            "REST /api/v1/admin/dlq/replay + DSL .dlq(target,max_attempts). "
            "default-OFF до миграции существующих transport-specific DLQ."
        ),
    )

    inbox_fail_closed: bool = Field(
        default=False,
        title="K2 S5 W3: Inbox dedup fail-closed (Redis-error → InboxUnavailable)",
        description=(
            "K2 Sprint 5 Wave 3. Owner: K2 Resilience. ETA: S5-W3. "
            "При True seen_or_mark() поднимает InboxUnavailable при Redis-error "
            "вместо silently-allowing duplicate. default-OFF до stress-теста."
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

    # ─── Sprint 5 — К3 DSL+Workflow ───────────────────────────────────────
    proc_html_template: bool = Field(
        default=False,
        title="K3 S5 W1: HtmlTemplateProcessor (Jinja2 HTML rendering)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует регистрацию HtmlTemplateProcessor в ProcessorRegistry."
        ),
    )

    proc_jsonpath: bool = Field(
        default=False,
        title="K3 S5 W1: JsonPathProcessor (jsonpath-ng query)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует JsonPathProcessor для извлечения поля по JsonPath."
        ),
    )

    proc_jq: bool = Field(
        default=False,
        title="K3 S5 W1: JqProcessor (jmespath query)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует JqProcessor для трансформации JSON через JMESPath."
        ),
    )

    proc_regex_extractor: bool = Field(
        default=False,
        title="K3 S5 W1: RegexExtractorProcessor (re.findall)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует RegexExtractorProcessor (regex named-groups)."
        ),
    )

    proc_webhook_signature: bool = Field(
        default=False,
        title="K3 S5 W2: WebhookSignatureProcessor (standardwebhooks HMAC verify)",
        description=(
            "K3 Sprint 5 Wave 2. Owner: K3 DSL. ETA: S5-W2. "
            "Активирует WebhookSignatureProcessor — HMAC-SHA256 / JWS verify "
            "входящих webhooks (Stripe-style standardwebhooks)."
        ),
    )

    proc_zip_archive: bool = Field(
        default=False,
        title="K3 S5 W2: ZipArchiveProcessor (stdlib zipfile pack/unpack)",
        description=(
            "K3 Sprint 5 Wave 2. Owner: K3 DSL. ETA: S5-W2. "
            "Активирует ZipArchiveProcessor — pack/unpack ZIP-архивов."
        ),
    )

    proc_pdf_template: bool = Field(
        default=False,
        title="K3 S5 W2: PdfTemplateProcessor (reportlab PDF rendering)",
        description=(
            "K3 Sprint 5 Wave 2. Owner: K3 DSL. ETA: S5-W2. "
            "Активирует PdfTemplateProcessor — генерация PDF из шаблона."
        ),
    )

    proc_ldap_query: bool = Field(
        default=False,
        title="K3 S5 W3: LdapQueryProcessor (ldap3 search)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует LdapQueryProcessor — async LDAP search через ldap3."
        ),
    )

    proc_webdav: bool = Field(
        default=False,
        title="K3 S5 W3: WebDavProcessor (webdav4 upload/download)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует WebDavProcessor — file операции через WebDAV."
        ),
    )

    proc_ics_calendar: bool = Field(
        default=False,
        title="K3 S5 W3: IcsCalendarProcessor (ics.py calendar parse/render)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует IcsCalendarProcessor — iCalendar parsing/rendering."
        ),
    )

    proc_unit_conversion: bool = Field(
        default=False,
        title="K3 S5 W3: UnitConversionProcessor (pint quantity convert)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует UnitConversionProcessor — pint-based unit conversion."
        ),
    )

    proc_geo: bool = Field(
        default=False,
        title="K3 S5 W3: GeoProcessor (geopy distance/geocoding)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует GeoProcessor — distance calc + geocoding (sync via thread)."
        ),
    )

    proc_rate_convert: bool = Field(
        default=False,
        title="K3 S5 W4: RateConvertProcessor (currency rates через WAF httpx)",
        description=(
            "K3 Sprint 5 Wave 4. Owner: K3 DSL. ETA: S5-W4. "
            "Активирует RateConvertProcessor — currency rates через "
            "OutboundHttpClient (WAF). default-OFF до интеграции с rate-provider."
        ),
    )

    db_call_procedure_enabled: bool = Field(
        default=False,
        title="K3 S5 W8: DSL .db_call_procedure(name, params, schema)",
        description=(
            "K3 Sprint 5 Wave 8. Owner: K3 DSL. ETA: S5-W8. "
            "Активирует RouteBuilder .db_call_procedure() builder method + "
            "DbCallProcedureProcessor (asyncpg execute SP)."
        ),
    )

    policy_chainable_enabled: bool = Field(
        default=False,
        title="K3 S5 W7: .policy.cache().policy.circuit_breaker() chainable",
        description=(
            "K3 Sprint 5 Wave 7. Owner: K3 DSL. ETA: S5-W7. "
            "Активирует chainable .policy.* API в RouteBuilder — composable "
            "policies через ResilienceCoordinator."
        ),
    )

    web_search_enabled: bool = Field(
        default=False,
        title="K3 S5 W9: .web_search(engine, query, max_results) builder",
        description=(
            "K3 Sprint 5 Wave 9. Owner: K3 DSL. ETA: S5-W9. "
            "Активирует RouteBuilder .web_search() поверх Tavily/Perplexity/SearXNG."
        ),
    )

    workflow_step_log_enabled: bool = Field(
        default=False,
        title="K3 S5 W11: StepAuditMiddleware → ClickHouse workflow_step_log",
        description=(
            "K3 Sprint 5 Wave 11. Owner: K3 DSL. ETA: S5-W11. "
            "Активирует StepAuditMiddleware — запись step-execution в ClickHouse "
            "workflow_step_log + OTel custom span attributes."
        ),
    )

    workflow_dryrun_enabled: bool = Field(
        default=False,
        title="K3 S5 W10: manage.py workflow dryrun (record/replay)",
        description=(
            "K3 Sprint 5 Wave 10. Owner: K3 DSL. ETA: S5-W10. "
            "Активирует manage.py workflow dryrun subcommand + JSON-отчёт."
        ),
    )

    cdc_postgres_enabled: bool = Field(
        default=False,
        title="K3 S5 W5: CDC Postgres logical replication (psycopg3+pgoutput)",
        description=(
            "K3 Sprint 5 Wave 5. Owner: K3 DSL. ETA: S5-W5. "
            "Активирует CdcPostgresLogicalSource + RouteBuilder .from_cdc(). "
            "default-OFF до создания replication-slot и smoke-теста."
        ),
    )

    result_unwrap_processor: bool = Field(
        default=False,
        title="K3 S5 W12: ResultUnwrapProcessor (result>=0.17 monad)",
        description=(
            "K3 Sprint 5 Wave 12. Owner: K3 DSL. ETA: S5-W12. "
            "Активирует ResultUnwrapProcessor — Ok/Err handling в pipeline."
        ),
    )

    blueprint_cdc_enrich: bool = Field(
        default=False,
        title="K3 S5 W6: Blueprint cdc_enrich",
        description=(
            "K3 Sprint 5 Wave 6. Owner: K3 DSL. ETA: S5-W6. "
            "Активирует blueprint cdc_enrich (cdc → enrich → publish)."
        ),
    )

    blueprint_ai_pipeline: bool = Field(
        default=False,
        title="K3 S5 W6: Blueprint ai_pipeline",
        description=(
            "K3 Sprint 5 Wave 6. Owner: K3 DSL. ETA: S5-W6. "
            "Активирует blueprint ai_pipeline (input → preprocess → llm → validate → output)."
        ),
    )

    blueprint_saga_compensation: bool = Field(
        default=False,
        title="K3 S5 W6: Blueprint saga_with_compensation",
        description=(
            "K3 Sprint 5 Wave 6. Owner: K3 DSL. ETA: S5-W6. "
            "Активирует blueprint saga_with_compensation (steps + compensate stages)."
        ),
    )

    taskgroup_processors: bool = Field(
        default=False,
        title="K3 S5 W13: asyncio.TaskGroup migration в parallel/streaming/batch",
        description=(
            "K3 Sprint 5 Wave 13. Owner: K3 DSL. ETA: S5-W13. "
            "Активирует TaskGroup-based реализацию в processors. "
            "default-OFF до перформанс-baseline diff."
        ),
    )

    invoke_workflow_reply_enabled: bool = Field(
        default=False,
        title="K3 S5 W14: .invoke_workflow reply-channels (correlation_id routing)",
        description=(
            "K3 Sprint 5 Wave 14. Owner: K3 DSL. ETA: S5-W14. "
            "Активирует reply-channel routing через correlation_id для "
            "async-api/signal modes invoke_workflow."
        ),
    )

    # ─── Sprint 5 — К4 AI+RAG ─────────────────────────────────────────────
    rag_cache_l3_retrieval_invalidation: bool = Field(
        default=False,
        title="K4 S5 W1: L3 retrieval cache + Redis pub/sub invalidation",
        description=(
            "K4 Sprint 5 Wave 1. Owner: K4 AI/RAG. ETA: S5-W1. "
            "Активирует L3 retrieval-graph cache + cross-instance invalidation "
            "через Redis pub/sub (расширение существующего L1+L2)."
        ),
    )

    multipart_rag_ingest: bool = Field(
        default=False,
        title="K4 W1: Bulk RAG ingest endpoint + Streamlit UI (multipart/form-data)",
        description=(
            "S19 K4 W1. Owner: K4 AI/RAG. "
            "Активирует POST /api/v1/rag/bulk-ingest endpoint, который принимает "
            'список {"content", "metadata"} документов, обрабатывает через embeddings '
            "pipeline и сохраняет в Chroma. Также активирует страницу "
            "85_RAG_Bulk_Upload.py с drag-drop файлом или textarea. "
            "default-OFF до staging-smoke."
        ),
    )

    multimodal_rag_docling: bool = Field(
        default=False,
        title="K4 S5 W3: Multimodal RAG (docling + PaddleOCR/EasyOCR)",
        description=(
            "K4 Sprint 5 Wave 3. Owner: K4 AI/RAG. ETA: S5-W3. "
            "Активирует MultimodalRAGService с docling document parsing и "
            "PaddleOCR fallback для scan-PDF."
        ),
    )

    langgraph_postgres_checkpoint: bool = Field(
        default=False,
        title="K4 S5 W2: LangGraph Postgres checkpoints (AsyncPostgresSaver)",
        description=(
            "K4 Sprint 5 Wave 2. Owner: K4 AI/RAG. ETA: S5-W2. "
            "Активирует AsyncPostgresSaver для LangGraph state persistence."
        ),
    )

    dsl_expose_mcp: bool = Field(
        default=False,
        title="K4 S5 W8: DSL expose_mcp = true в route.toml + MCP auto-registration",
        description=(
            "K4 Sprint 5 Wave 8. Owner: K4 AI/RAG. ETA: S5-W8. "
            "Активирует expose_mcp директиву в route.toml для автоматической "
            "регистрации route как MCP tool."
        ),
    )

    rlm_hierarchical_memory: bool = Field(
        default=False,
        title="K4 S5 W4: RLM-toolkit MemGPT-style hierarchical memory",
        description=(
            "K4 Sprint 5 Wave 4. Owner: K4 AI/RAG. ETA: S5-W4. "
            "Активирует RLM hierarchical memory (working/recall/archival tiers)."
        ),
    )

    unmask_pii_enabled: bool = Field(
        default=False,
        title="K4 S5 W6: .unmask_pii (vault-key restore) processor",
        description=(
            "K4 Sprint 5 Wave 6. Owner: K4 AI/RAG. ETA: S5-W6. "
            "Активирует UnmaskPiiProcessor — обратная операция к mask_pii через vault-key."
        ),
    )

    mem0ai_enabled: bool = Field(
        default=False,
        title="K4 S5 W5: mem0ai memory backend для DSL .memory_*",
        description=(
            "K4 Sprint 5 Wave 5. Owner: K4 AI/RAG. ETA: S5-W5. "
            "Активирует mem0ai backend для DSL .memory_write/.memory_read."
        ),
    )

    langfuse_mcp_prompt: bool = Field(
        default=False,
        title="K4 S5 W8: LangFuse prompts → @mcp.prompt auto-registration",
        description=(
            "K4 Sprint 5 Wave 8. Owner: K4 AI/RAG. ETA: S5-W8. "
            "Активирует автоматическую регистрацию LangFuse prompts как MCP prompts."
        ),
    )

    # ─── Sprint 5 — К5 Frontend ───────────────────────────────────────────
    frontend_workflow_logs_page: bool = Field(
        default=False,
        title="K5 S5 W1: Streamlit 50_Workflow_Logs.py + APIClient list_step_logs",
        description=(
            "K5 Sprint 5 Wave 1. Owner: K5 Frontend. ETA: S5-W1. "
            "Активирует страницу 50_Workflow_Logs.py — фильтр workflow/tenant/date "
            "+ st.dataframe events + waterfall chart + drill-down."
        ),
    )

    # ─── Sprint 6 — К1 Security ───────────────────────────────────────────
    saml_ad_login_enabled: bool = Field(
        default=False,
        title="K1 S6: SAML SSO + AD/LDAP directory integration",
        description=(
            "K1 Sprint 6 Wave 1. Owner: K1 Security. ETA: S6-W1. "
            "Активирует SAML SP-initiated SSO через core/auth/saml_backend.py "
            "+ AD/LDAP-lookups через services/auth/ad_directory_client.py. "
            "default-OFF до integration-теста с mock-IdP (osixia/openldap) и "
            "staging IdP конфигурации."
        ),
    )

    outbound_metering_strict: bool = Field(
        default=False,
        title="K1 S6: PerHostMeter strict mode + quota threshold + alerts",
        description=(
            "K1 Sprint 6 Wave 2. Owner: K1 Security. ETA: S6-W2. "
            "Переключает PerHostMeter (scaffold s3/k2-w1-per-host-metering) "
            "из warning-only в enforce mode — quota threshold + alerts на "
            "превышение per-host rate-limit. default-OFF до staging smoke."
        ),
    )

    supply_chain_strict_mode: bool = Field(
        default=False,
        title="K1 S6: Supply-chain strict CI gate (SBOM+pip-audit ERROR+cosign+bandit-TLS)",
        description=(
            "K1 Sprint 6 Wave 3. Owner: K1 Security. ETA: S6-W3. "
            "Активирует strict-режим supply-chain gate: tools/checks/check_supply_chain.py "
            "оркестрирует generate_sbom + run_pip_audit ERROR-level + cosign_sign + "
            "bandit с TLS-rules. Blocking в .github/workflows/release.yml. "
            "default-OFF до полного аудита transitive deps."
        ),
    )

    owasp_zap_gate_enabled: bool = Field(
        default=False,
        title="K1 S6: OWASP ZAP baseline scan в CI",
        description=(
            "K1 Sprint 6 Wave 4. Owner: K1 Security. ETA: S6-W4. "
            "Активирует .github/workflows/security.yml OWASP ZAP baseline scan "
            "против main-endpoints (5-10 reference targets из tests/security/zap_targets.yml). "
            "Warn-only по решению пользователя — blocking откладывается до Sprint 9."
        ),
    )

    custom_code_audit_enabled: bool = Field(
        default=False,
        title="K1 S6: vulture min-confidence 80 + manual review wrapper",
        description=(
            "K1 Sprint 6 Wave 5. Owner: K1 Security. ETA: S6-W5. "
            "Активирует make custom-code-audit — tools/checks/check_custom_code.py "
            "запускает vulture --min-confidence 80 + сопоставляет с allowlist. "
            "default-OFF до калибровки allowlist (baseline FP ≤5)."
        ),
    )

    codeclone_fail_on_new: bool = Field(
        default=False,
        title="K1 S6: codeclone gate --fail-on-new-clones (strict)",
        description=(
            "K1 Sprint 6 Wave 6. Owner: K1 Security. ETA: S6-W6. "
            "Переключает codeclone CI gate из warning в blocking режим: "
            "только новые клоны сравниваются с baseline в tools/checks/codeclone_baseline.json. "
            "default-OFF до фиксации baseline в master."
        ),
    )

    # ─── Sprint 6 — К2 Resilience+Perf ────────────────────────────────────
    perf_gate_strict: bool = Field(
        default=False,
        title="K2 S6: perf-gate strict (p95<200ms / RPS>1000 blocking)",
        description=(
            "K2 Sprint 6 Wave 1. Owner: K2 Perf. ETA: S6-W1. "
            "Переключает perf-gate в blocking режим: p95<200ms / RPS>1000 для "
            "reference endpoints через k6+locust в docker-compose.perf.yml. "
            "Warn-only по решению пользователя — blocking откладывается до Sprint 9."
        ),
    )

    structlog_batching_enabled: bool = Field(
        default=False,
        title="K2 S6: structlog batching wrapper (50-event / 100ms)",
        description=(
            "K2 Sprint 6 Wave 4. Owner: K2 Perf. ETA: S6-W4. "
            "Активирует BatchingStructlogProcessor — 50-event batch / 100ms timeout "
            "wrapper над structlog pipeline. Ожидаемое улучшение -1..3ms per log. "
            "default-OFF до benchmark подтверждения."
        ),
    )

    processor_health_checks_strict: bool = Field(
        default=False,
        title="K2 S6: /health/processors агрегированный матричный endpoint",
        description=(
            "K2 Sprint 6 Wave 5. Owner: K2 Ops. ETA: S6-W5. "
            "Активирует /health/processors endpoint — матрица health-checks "
            "(Kafka schema-registry, Temporal server, Vault sealed, ClickHouse, "
            "Redis cluster, NATS, Graylog). Каждый возвращает {ok, reason, latency_ms}."
        ),
    )

    backpressure_streaming_enabled: bool = Field(
        default=False,
        title="K2 S6: backpressure model для streaming consumers",
        description=(
            "K2 Sprint 6 Wave 6. Owner: K2 Perf. ETA: S6-W6. "
            "Активирует backpressure: FastStream Kafka consumer.pause/resume на HW, "
            "Redis Streams XREAD count adaptive, AdaptiveBulkhead в DSL-pipeline. "
            "Защита от OOM при 10× spike. default-OFF до chaos-теста."
        ),
    )

    granian_rsgi_mode_enabled: bool = Field(
        default=False,
        title="K2 S6: Granian RSGI production mode + uvloop tuning",
        description=(
            "K2 Sprint 6 Wave 2. Owner: K2 Perf. ETA: S6-W2. "
            "Активирует Granian RSGI как production HTTP server (вместо ASGI) "
            "с uvloop event-loop. ADR-0059. default-OFF до benchmark подтверждения "
            "-10..30% latency improvement."
        ),
    )

    schemathesis_gate_enabled: bool = Field(
        default=False,
        title="K2 S6: API fuzz через schemathesis + asyncapi-diff",
        description=(
            "K2 Sprint 6 Wave 7. Owner: K2 Quality. ETA: S6-W7. "
            "Активирует make api-fuzz — schemathesis run на OpenAPI spec + "
            "asyncapi-diff stage. Warn-only по решению пользователя."
        ),
    )

    service_doc_gate_enabled: bool = Field(
        default=False,
        title="K2 S6: check_service_docs.py CI gate (description/example required)",
        description=(
            "K2 Sprint 6 Wave 8. Owner: K2 Quality. ETA: S6-W8. "
            "Активирует tools/checks/check_service_docs.py — проверка наличия "
            "description/docstring/example у каждого @service_dsl. "
            "Blocking в CI."
        ),
    )

    # ─── Sprint 6 — К3 DSL+Workflow ───────────────────────────────────────
    com_sidecar_enabled: bool = Field(
        default=False,
        title="K3 S6: Windows COM sidecar (pywin32 + comtypes + FastAPI)",
        description=(
            "K3 Sprint 6 Wave 5. Owner: K3 DSL. ETA: S6-W5. "
            "Активирует .call_com(worker, method, params) DSL-шаг → REST к "
            "windows_worker/main.py через services/rpa/com_sidecar_client.py. "
            "default-OFF на Linux (mock); ON на Windows-worker docker."
        ),
    )

    dsl_linter_strict: bool = Field(
        default=False,
        title="K3 S6: DSL Linter CLI + LSP plugin-aware (pygls)",
        description=(
            "K3 Sprint 6 Wave 4. Owner: K3 DSL. ETA: S6-W4. "
            "Активирует manage.py dsl lint <path> + LSP server (dsl/cli/lsp_server.py) "
            "через pygls с plugin-aware schema discovery. "
            "default-OFF до fixture baseline ≥5 типов ошибок."
        ),
    )

    # ─── Sprint 6 — К4 AI+Quality ─────────────────────────────────────────
    inspect_ai_eval_enabled: bool = Field(
        default=False,
        title="K4 S6: Inspect AI nightly eval framework",
        description=(
            "K4 Sprint 6 Wave 1. Owner: K4 AI. ETA: S6-W1. "
            "Активирует manage.py ai-eval nightly + 5-7 reference suites "
            "(knowledge_qa/instruction_following/hallucination/safety/context_recall). "
            ".github/workflows/ai-eval-nightly.yml cron-job."
        ),
    )

    dspy_eval_pipeline_enabled: bool = Field(
        default=False,
        title="K4 S6: DSPy optimizer для critical pipelines",
        description=(
            "K4 Sprint 6 Wave 2. Owner: K4 AI. ETA: S6-W2. "
            "Активирует DSPy optimization для credit.scoring / document.parser / "
            "rag.query_reranker. Bootstrap from few-shot + DSPyOptimizer.compile(). "
            "default-OFF до validation lift ≥10% на reference dataset."
        ),
    )

    ai_cost_dashboard_strict: bool = Field(
        default=False,
        title="K4 S6: AI cost dashboard финал (per-tenant breakdown + alerts)",
        description=(
            "K4 Sprint 6 Wave 3. Owner: K4 AI. ETA: S6-W3. "
            "Активирует services/ai/costs/dashboard.py — агрегация langfuse_reader "
            "+ alerts + per-tenant breakdown + token rate trends. "
            "Streamlit 23_AI_Cost_Tracking.py с фильтрами (date/tenant/model/pipeline)."
        ),
    )

    # ─── Sprint 6 — К5 Frontend+Chaos ─────────────────────────────────────
    chaos_tests_blocking: bool = Field(
        default=False,
        title="K5 S6: 33 chaos-теста blocking в CI",
        description=(
            "K5 Sprint 6 Wave 1. Owner: K5 Chaos. ETA: S6-W1. "
            "Переключает 33 chaos-теста (testcontainers[toxiproxy], 11 chains × 3 сценария) "
            "в blocking режим. Warn-only по решению пользователя — blocking откладывается "
            "до Sprint 9 pre-prod gate."
        ),
    )

    resilience_dashboard_enabled: bool = Field(
        default=False,
        title="K5 S6: Streamlit Resilience Dashboard (CB+RL+Bulkhead+Degradation)",
        description=(
            "K5 Sprint 6 Wave 3. Owner: K5 Frontend. ETA: S6-W3. "
            "Активирует страницу 13_Resilience_Dashboard.py — матрица CB/RL/Bulkhead/"
            "Degradation статусов через ResilienceCoordinator.snapshot() API + "
            "live updates каждые 5 сек."
        ),
    )

    pool_monitor_enabled: bool = Field(
        default=False,
        title="K5 S6: Streamlit Pool Monitor (worker + connection pools)",
        description=(
            "K5 Sprint 6 Wave 4. Owner: K5 Frontend. ETA: S6-W4. "
            "Активирует страницу 15_Pool_Monitor.py — worker pool + connection pool "
            "monitor для PG/Redis/HTTP/Kafka через PoolHealthMonitor API + live metrics."
        ),
    )

    # ─── Sprint 7 — К4 AI+RAG (multi-agent + voice/image) ─────────────────
    multi_agent_supervisor_enabled: bool = Field(
        default=False,
        title="K4 S7: LangGraph multi-agent supervisor (handoff между специализированными агентами)",
        description=(
            "K4 Sprint 7. Owner: K4 AI/RAG. ETA: S7. "
            "Активирует MultiAgentSupervisor (services/ai/multi_agent/supervisor.py) — "
            "LangGraph supervisor pattern + handoff_to(agent_name) tool. "
            "Reference implementation для credit-pipeline "
            "(supervisor=credit_orchestrator, agents=[scoring_agent, document_parser_agent, decision_agent]). "
            "default-OFF до staging-smoke с реальным LLM-провайдером."
        ),
    )

    voice_image_gen_enabled: bool = Field(
        default=False,
        title="K4 S7: Voice (Whisper STT + Coqui TTS) + Image generation wrappers",
        description=(
            "K4 Sprint 7. Owner: K4 AI/RAG. ETA: S7. "
            "Активирует WhisperSTTService / CoquiTTSService (services/ai/voice/) + "
            "LiteLLMImageGenerationService (services/ai/image_generation/litellm_image.py). "
            "Lazy-import openai-whisper / TTS / litellm.image_generation(). "
            "default-OFF до установки voice extras и staging-smoke."
        ),
    )

    voice_stt_tts_enabled: bool = Field(
        default=False,
        title="K4 S7: Whisper STT + Coqui TTS wrappers (voice pipeline)",
        description=(
            "K4 Sprint 7. Owner: K4 AI/RAG. ETA: S7. "
            "Активирует WhisperSTTService.transcribe() / CoquiTTSService.synthesize() "
            "поверх openai-whisper и Coqui TTS (extras [ai-voice]). "
            "Lazy-import тяжёлых SDK; default-OFF до установки extras и staging-smoke."
        ),
    )

    rpa_ocr_enabled: bool = Field(
        default=False,
        title="S18 W0: pytesseract OCR processor (services/rpa/ocr_processor)",
        description=(
            "Sprint 18 W0 [wave:s18/w0-goal-driven-sweep-2-ocr]. "
            "Owner: K3 RPA. Активирует OCRProcessor поверх pytesseract "
            "(extras [rpa-ocr], требует Tesseract на хосте). При False — "
            "OCRProcessor.from_environment() возвращает NoOpOCRProcessor. "
            "Default-OFF до staging-smoke."
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

    cdc_enabled: bool = Field(
        default=False,
        title="S18 W0: включить CDC backends (Poll/Listen-Notify/Debezium)",
        description=(
            "Sprint 18 W0 [wave:s18/w0-goal-driven-sweep-7-cdc-status-doc]. "
            "Owner: K2 Platform. При False CDC-source'ы не активируются в "
            "lifespan; PollCDCBackend и ListenNotifyCDCBackend готовы к "
            "production, DebeziumEventsCDCBackend — scaffold (Sprint R3.4). "
            "Default-OFF до явного staging-smoke."
        ),
    )

    # ─── Sprint 7 — K3 DSL+Workflow ────────────────────────────────────────
    dsl_blueprints_migrate: bool = Field(
        default=False,
        title="K3 S7: deprecation-warning для legacy импортов src.backend.dsl.macros",
        description=(
            "K3 Sprint 7 (wave:s7/k3-dsl-blueprints-migrate). Owner: K3 DSL/Workflow. "
            "ETA: S7. Активирует DeprecationWarning при импорте через shim "
            "'from src.backend.dsl.macros import X' — реальная реализация теперь "
            "в src.backend.dsl.blueprints.macros. default-OFF (1-2 sprint grace-period). "
            "После Sprint 9 shim удаляется."
        ),
    )

    workflow_versioning_strict: bool = Field(
        default=False,
        title="K3 S7: strict workflow versioning + Temporal patched-API integration",
        description=(
            "K3 Sprint 7 (wave:s7/k3-workflow-versioning). Owner: K3 DSL/Workflow. "
            "ETA: S7. Активирует WorkflowVersionRegistry strict-mode: "
            "несовместимая мажорная версия → ValueError на register; "
            "интеграция с temporalio.workflow.patched(patch_id) для миграций между "
            "версиями. default-OFF до интеграции с Temporal cluster и staging-smoke."
        ),
    )

    # ─── Sprint 10 — DSL Blueprint Expansion + DX Wizards ─────────────────
    compression_brotli: bool = Field(
        default=False,
        title="K2 S10 W2: BrotliCompressionMiddleware (Accept-Encoding: br)",
        description=(
            "K2 Sprint 10 Wave 2 (wave:s10/k2-w2-brotli-compression). "
            "Owner: K2 Resilience+Perf. ETA: S10-W2. "
            "Активирует BrotliCompressionMiddleware (pure ASGI) — Brotli-сжатие "
            "ответов с Accept-Encoding: br. Ожидаемое улучшение ≥30% reduction для "
            "JSON ≥1KB. default-OFF до benchmark подтверждения и интеграции в main.py."
        ),
    )

    dsl_complexity_check_blocking: bool = Field(
        default=False,
        title="K3 S10 W2: dsl-complexity-check blocking gate в CI",
        description=(
            "K3 Sprint 10 Wave 2 (wave:s10/k3-w2-dsl-complexity-budget). "
            "Owner: K3 DSL+Workflow. ETA: S10-W2. "
            "Активирует blocking-режим для tools/dsl_lint.py check-complexity "
            "(cyclomatic ≤50 / nesting ≤5 / steps ≤50). "
            "При False — warn-only в CI. default-OFF до baseline-измерения "
            "existing routes и калибровки threshold'ов."
        ),
    )

    mock_llm_enabled: bool = Field(
        default=False,
        title="K4 S10 W1: Mock-LLM provider (deterministic, cost=0)",
        description=(
            "K4 Sprint 10 Wave 1 (wave:s10/k4-w1-mock-llm-provider). "
            "Owner: K4 AI+RAG. ETA: S10-W1. "
            "Активирует MockLLMProvider — deterministic responses (prompt-hash → "
            "lookup table), cost=0, latency simulation. LiteLLM-compatible "
            "(mock://gpt-4 model name). default-OFF в production; default-ON в "
            "dev_light / CI для воспроизводимости тестов."
        ),
    )

    dsl_jinja_macros: bool = Field(
        default=False,
        title="K3 S10 W7: Jinja2-over-YAML loader (macros + include)",
        description=(
            "K3 Sprint 10 Wave 7 (wave:s10/k3-w7-dsl-jinja-macros). "
            "Owner: K3 DSL+Workflow. ETA: S10-W7. "
            "Активирует Jinja2-over-YAML pre-processor в dsl/route/loader.py: "
            "поддержка {% macro %} и {% include %} через jinja2.sandbox."
            "SandboxedEnvironment + StrictUndefined для ловли опечаток. "
            "default-OFF до golden-snapshot тестов на 2 routes с macros + "
            "2 routes без. Rollback через flag flip."
        ),
    )

    dsl_step_trace: bool = Field(
        default=False,
        title="K3 S10 W8: StepTrace + OTel span attributes для processors",
        description=(
            "K3 Sprint 10 Wave 8 (wave:s10/k3-w8-dsl-step-tracing). "
            "Owner: K3 DSL+Workflow. ETA: S10-W8. "
            "Активирует StepTrace в dsl/engine/exchange.py (input_snapshot, "
            "duration_ms, error_context) + OTel span attributes в BaseProcessor "
            "(dsl.step.name, dsl.step.input_size, dsl.step.duration_ms). "
            "default-OFF до verification trace propagation через 5 reference routes."
        ),
    )

    # ─── Sprint 8 — Rule Engine persistence ───────────────────────────────
    rule_engine_hot_reload: bool = Field(
        default=False,
        title="K3 S8: hot-reload ruleset из БД через rule-engine registry",
        description=(
            "K3 Sprint 8 (wave:s8/k3-rule-engine-finale). Owner: K3 DSL/Workflow. "
            "Активирует периодическую инвалидацию кэша RuleEngineRegistry "
            "(intervalом 60 сек) и подгрузку обновлённых ruleset'ов из БД "
            "(таблица rule_engine_rulesets) без перезапуска. "
            "default-OFF: при выключенном флаге кэш живёт до явного invalidate()."
        ),
    )

    # ─── Sprint 8 — HTTP/3 + WebTransport opt-in ──────────────────────────
    http3_enabled: bool = Field(
        default=False,
        title="K3 S8: HTTP/3 + WebTransport entrypoint (aioquic)",
        description=(
            "K3 Sprint 8 (wave:s8/k3-http3-opt-in). Owner: K3 DSL/Workflow. "
            "Запускает дополнительный HTTP/3 endpoint поверх QUIC через "
            "aioquic (entrypoints/http3/server.py serve_http3). Параллельно "
            "стандартному HTTP/1.1+HTTP/2 серверу Granian. Требует TLS-сертификат "
            "(см. config.py: cert_file/key_file). default-OFF до staging-smoke "
            "и согласования сетевых правил (UDP/443)."
        ),
    )

    # ─── Sprint 9 — GAP closure feature flags ─────────────────────────────
    route_loader_hot_reload: bool = Field(
        default=False,
        title="K3 S9 W1: RouteLoader hot-reload full-cycle (GAP-DSL-1)",
        description=(
            "K3 Sprint 9 Wave 1 (wave:s9/k3-w1-route-loader-hot-reload). "
            "Owner: K3 DSL+Workflow. ETA: S9 W1. Активирует watchfiles-driven "
            "перезагрузку routes/<name>/*.dsl.yaml без рестарта процесса. "
            "DoD: `make verify-hot-reload` < 3000ms для 50 routes. "
            "default-OFF в prod; включён в dev_light profile. GAP-DSL-1."
        ),
    )

    streamlit_page_renumber: bool = Field(
        default=False,
        title="K5 S9 W2: Streamlit pages renumbering (GAP-DSL-2)",
        description=(
            "K5 Sprint 9 Wave 2 (wave:s9/k5-w2-streamlit-page-renumber). "
            "Owner: K5 Frontend. Активирует новую схему нумерации Streamlit "
            "pages: DSL 30-39 / AI 40-49 / Ops 50-59 / Admin 60-69. "
            "Включается после rollout документации routing-guide. GAP-DSL-2."
        ),
    )

    hitl_panel_enabled: bool = Field(
        default=False,
        title="K3 S9: HITL (Human-in-the-Loop) panel для workflow (GAP-WF-4.5)",
        description=(
            "K3 Sprint 9 (wave:s9/k3-hitl-panel). Owner: K3 DSL+Workflow. "
            "Активирует Streamlit-страницу для approval/reject ручных шагов "
            "workflow (Temporal signal-based). Требует AuditLog + RBAC. "
            "default-OFF до E2E проверки UX-flow. GAP-WF-4.5."
        ),
    )

    tenant_token_budget_enabled: bool = Field(
        default=False,
        title="K4 S9: Token budget per tenant для AI/LLM (GAP-3.2)",
        description=(
            "K4 Sprint 9 (wave:s9/k4-tenant-token-budget). Owner: K4 AI/Data. "
            "Активирует per-tenant квоты на токены LLM (prompt+completion) "
            "через TenantContext + BudgetEnforcer middleware. Превышение → "
            "429 + audit-event. default-OFF до staging-tuning. GAP-3.2."
        ),
    )

    saml_sp_initiated_enabled: bool = Field(
        default=False,
        title="K1 S9: SAML SP-initiated SSO (GAP-1.5)",
        description=(
            "K1 Sprint 9 (wave:s9/k1-saml-sp-initiated). Owner: K1 Security. "
            "Активирует /saml/login endpoint (SP-initiated flow) дополнительно "
            "к IdP-initiated. Требует SAMLAuth Settings (sp_entity_id, acs_url, "
            "idp_metadata_url). default-OFF до AD-coordination. GAP-1.5."
        ),
    )

    lazy_processor_loading: bool = Field(
        default=False,
        title="K3 S9: Lazy processor loading (GAP-PERF-6.3)",
        description=(
            "K3 Sprint 9 (wave:s9/k3-lazy-processor-loading). Owner: K3 DSL. "
            "Активирует lazy-import процессоров через ProcessorRegistry (только "
            "при первом invoke). Снижает cold-start dev_light на 200-400 мс. "
            "default-OFF до perf-benchmark в prod-конфигурации. GAP-PERF-6.3."
        ),
    )

    clickhouse_bulk_writer_enabled: bool = Field(
        default=False,
        title="K2 S9: ClickHouse bulk writer (GAP-INF-2.3)",
        description=(
            "K2 Sprint 9 (wave:s9/k2-clickhouse-bulk-writer). Owner: K2 Infra. "
            "Активирует batch-аккумулятор для ClickHouse INSERT (5000 rows / "
            "5 сек). Использует chdb-stream + retry. default-OFF до staging-smoke "
            "(анализ memory footprint per-batch). GAP-INF-2.3."
        ),
    )

    # ─── Sprint 11 — AI/RAG Completion ─────────────────────────────────────
    rag_pii_retrieval_mask: bool = Field(
        default=False,
        title="K1 S11 W1: PII redaction в RAG retrieval pipeline",
        description=(
            "K1 Sprint 11 Wave 1 (wave:s11/k1-w1-rag-pii-redaction). "
            "Owner: K1 Security. Активирует RagPIIRedactionProcessor — "
            "маскирует CC/SSN/email/phone в augment_result.documents[*].content. "
            "Capability: ai.rag.pii_redaction. default-OFF до staging-smoke."
        ),
    )

    guardrails_per_tenant: bool = Field(
        default=False,
        title="K1 S11 W2: per-tenant guardrails (Lakera + Rebuff)",
        description=(
            "K1 Sprint 11 Wave 2 (wave:s11/k1-w2-guardrails-per-tenant). "
            "Owner: K1 Security. Подключает Lakera Guard / Rebuff клиенты "
            "с per-tenant thresholds (TenantSettings.guardrails). "
            "Capabilities: ai.guardrails.lakera:external, ai.guardrails.rebuff:external. "
            "default-OFF до coordination с tenant-config."
        ),
    )

    distributed_rl_redis_cluster: bool = Field(
        default=False,
        title="K2 S11 W1: distributed rate-limiter поверх Redis Cluster",
        description=(
            "K2 Sprint 11 Wave 1 (wave:s11/k2-w1-distributed-rl-redis-cluster). "
            "Owner: K2 Resilience. DistributedRedisRateLimiter (Lua CL.THROTTLE "
            "token-bucket per-tenant) поверх RedisClusterAdapter. Активируется "
            "вместо in-memory RL. default-OFF до perf-smoke (10K req/s)."
        ),
    )

    multimodal_rag_full: bool = Field(
        default=False,
        title="K4 S11 W1/W2: Multimodal RAG full pipeline (BLIP2 + Whisper + cross-modal)",
        description=(
            "K4 Sprint 11 Wave 1+2 (wave:s11/k4-w1-multimodal-rag-full + "
            "wave:s11/k4-w2-multimodal-rag-pipeline). Owner: K4 AI/Data. "
            "Подключает BLIP2 captioning + Whisper STT + cross-modal retrieval. "
            "Lazy-import тяжёлых deps (transformers, openai-whisper, librosa). "
            "default-OFF до staging-smoke (heavy model weights ~8GB)."
        ),
    )

    adaptive_rag_strategy: bool = Field(
        default=False,
        title="K4 S11 W3: adaptive RAG strategy selection (LLM classifier)",
        description=(
            "K4 Sprint 11 Wave 3 (wave:s11/k4-w3-adaptive-rag-strategy). "
            "Owner: K4 AI/Data. Активирует strategy=adaptive в RagQueryProcessor: "
            "LLM-classifier выбирает dense|hybrid|hyde|multi_query по типу query. "
            "Overhead < 50ms (DoD #2). default-OFF до bench-validation."
        ),
    )

    langgraph_checkpoint_ui: bool = Field(
        default=False,
        title="K4 S11 W4: LangGraph checkpoint UI (time-travel restore)",
        description=(
            "K4 Sprint 11 Wave 4 (wave:s11/k4-w4-langgraph-checkpoint-ui). "
            "Owner: K4 AI/Data. Активирует /admin/langgraph/checkpoints REST + "
            "Streamlit-вкладку для list/inspect/restore. Требует "
            "LangGraphPostgresSaverWrapper. default-OFF до E2E проверки."
        ),
    )

    dspy_feedback_loop: bool = Field(
        default=False,
        title="K4 S11 W5: DSPy feedback nightly training loop",
        description=(
            "K4 Sprint 11 Wave 5 (wave:s11/k4-w5-ai-feedback-dspy). "
            "Owner: K4 AI/Data. Cron 0 3 * * * — собирает labeled feedback из "
            "AIFeedbackService → DSPy BootstrapFewShot → LangfusePromptStorage. "
            "Capability: ai.feedback.train. default-OFF до staging-tuning."
        ),
    )

    ai_model_registry_ui: bool = Field(
        default=False,
        title="K4 S11 W6: AI Model Registry UI (HF Hub + MLflow composite)",
        description=(
            "K4 Sprint 11 Wave 6 (wave:s11/k4-w6-ai-model-registry-ui). "
            "Owner: K4 AI/Data. Подключает HuggingFaceBackend параллельно MLflow "
            "через CompositeModelRegistry, + admin REST + Streamlit page 49. "
            "Capabilities: ai.model_registry.read/write. default-OFF."
        ),
    )

    ai_route_optimization: bool = Field(
        default=False,
        title="K4 S11 W7: AI-driven route optimization (PR-suggestion)",
        description=(
            "K4 Sprint 11 Wave 7 (wave:s11/k4-w7-ai-route-optimization). "
            "Owner: K4 AI/Data. Анализирует логи route → metrics → AI "
            "recommendations + PR markdown. CLI: manage.py ai-route-optimize. "
            "Capability: ai.route.optimize. default-OFF."
        ),
    )

    embedding_ab_migration: bool = Field(
        default=False,
        title="K4 S11 W8: embedding A/B progressive migration",
        description=(
            "K4 Sprint 11 Wave 8 (wave:s11/k4-w8-embedding-ab-migration). "
            "Owner: K4 AI/Data. Параллельная индексация двух коллекций "
            "(docs_bge_m3 + docs_bge_m3_v2), A/B retrieval split по hash(query), "
            "progressive switch через embedding_v2_traffic. default-OFF."
        ),
    )

    embedding_v2_traffic: int = Field(
        default=0,
        title="K4 S11 W8: процент трафика на v2 embedding (0..100)",
        description=(
            "K4 Sprint 11 Wave 8. Owner: K4 AI/Data. Доля трафика, направляемая "
            "на новую embedding-коллекцию при включённом embedding_ab_migration. "
            "0..100, шаг прогрессивного переключения: 0 → 25 → 50 → 100."
        ),
    )

    # ------------------------------------------------------------------ #
    #  Sprint 12 — Workflow Enhancement (18 feature-flags)               #
    # ------------------------------------------------------------------ #

    workflow_audit_extended: bool = Field(
        default=True,
        title="K1 S12 W1: расширенный workflow_audit event-set",
        description=(
            "K1 Sprint 12 Wave 1 (wave:s12/k1-w1-workflow-audit-log). "
            "Owner: K1 Security. Активирует расширенный event_type allowlist: "
            "workflow.start/signal/cancel/complete/fail/compensation_* + hitl.*. "
            "Колонки actor/duration_ms/parent_workflow_id. default-ON для prod."
        ),
    )

    workflow_mtls_enabled: bool = Field(
        default=False,
        title="K1 S12 W2: Temporal mTLS через Vault PKI engine",
        description=(
            "K1 Sprint 12 Wave 2 (wave:s12/k1-w2-temporal-mtls-finale). "
            "Owner: K1 Security. Production-ready mTLS worker → server через "
            "Vault PKI; cert rotation TaskRegistry TTL 23h. default-OFF до "
            "staging-smoke."
        ),
    )

    workflow_sla_dashboard_enabled: bool = Field(
        default=True,
        title="K2 S12 W1: Workflow SLA Grafana dashboard + 99% SLO",
        description=(
            "K2 Sprint 12 Wave 1 (wave:s12/k2-w1-workflow-sla-grafana). "
            "Owner: K2 Resilience+Perf. SLA compliance rate (last 24h) поверх "
            "workflow_audit ClickHouse; Prometheus counter "
            "workflow_sla_compliance_total. default-ON."
        ),
    )

    workflow_worker_autoscale_enabled: bool = Field(
        default=False,
        title="K2 S12 W2: TemporalWorkerPool dynamic scaling по queue depth",
        description=(
            "K2 Sprint 12 Wave 2 (wave:s12/k2-w2-temporal-worker-autoscale). "
            "Owner: K2 Resilience+Perf. TemporalWorkerScaler min=2 max=20 + "
            "K8s HPA через PrometheusAdapter. default-OFF dev / ON prod."
        ),
    )

    workflow_visual_diff_enabled: bool = Field(
        default=True,
        title="K3 S12 W1: Workflow Diff (side-by-side Graphviz) в page 31",
        description=(
            "K3 Sprint 12 Wave 1 (wave:s12/k3-w1-visual-workflow-diff). "
            "Owner: K3 DSL/Workflow. visualize.py:to_graphviz + structured "
            "step_diff + color-coded changes. default-ON."
        ),
    )

    workflow_cron_builder_enabled: bool = Field(
        default=True,
        title="K3 S12 W2: Visual cron builder + croniter preview (page 13)",
        description=(
            "K3 Sprint 12 Wave 2 (wave:s12/k3-w2-cron-builder-ui). "
            "Owner: K3 DSL/Workflow. croniter dep + timezone-aware preview + "
            "dry-run; admin_cron REST. default-ON."
        ),
    )

    workflow_cost_estimation_enabled: bool = Field(
        default=True,
        title="K3 S12 W3: pre-run cost estimation (page 15)",
        description=(
            "K3 Sprint 12 Wave 3 (wave:s12/k3-w3-workflow-cost-estimation). "
            "Owner: K3 DSL/Workflow. WorkflowCostEstimator (p50/p95 из "
            "workflow_audit) + admin_workflow_cost REST. default-ON."
        ),
    )

    workflow_reactive_triggers_enabled: bool = Field(
        default=False,
        title="K3 S12 W4: event-driven reactive workflows (EventBus subscribe)",
        description=(
            "K3 Sprint 12 Wave 4 (wave:s12/k3-w4-reactive-workflows). "
            "Owner: K3 DSL/Workflow. ReactiveWorkflowDispatcher + .reactive_on "
            "builder + debounce 5s + dedup Redis SET NX EX 60. default-OFF до "
            "staging-smoke."
        ),
    )

    workflow_template_library_enabled: bool = Field(
        default=True,
        title="K3 S12 W5: workflow template library (10 templates)",
        description=(
            "K3 Sprint 12 Wave 5 (wave:s12/k3-w5-workflow-template-library). "
            "Owner: K3 DSL/Workflow. 10 yaml в dsl/workflow/templates/ + "
            "WorkflowTemplateRegistry; admin_workflow_templates REST. default-ON."
        ),
    )

    workflow_template_semantic_search: bool = Field(
        default=False,
        title="K3 S12 W5: BGE-M3 semantic search для template registry",
        description=(
            "K3 Sprint 12 Wave 5 (wave:s12/k3-w5-workflow-template-library). "
            "Owner: K3 DSL/Workflow. Включает BGE-M3 semantic search; "
            "auto-ON если sentence_transformers установлен, иначе fallback на "
            "rapidfuzz. default-OFF."
        ),
    )

    workflow_saga_viewer_enabled: bool = Field(
        default=True,
        title="K3 S12 W6: Saga Compensation Viewer (pages 17/19)",
        description=(
            "K3 Sprint 12 Wave 6 (wave:s12/k3-w6-saga-compensation-viewer). "
            "Owner: K3 DSL/Workflow. SagaProcessor emit workflow.compensation_* "
            "events + timeline view в pages 17/19. default-ON."
        ),
    )

    workflow_cancel_dsl_enabled: bool = Field(
        default=True,
        title="K3 S12 W7: .cancel_workflow() DSL step + audit event",
        description=(
            "K3 Sprint 12 Wave 7 (wave:s12/k3-w7-cancel-workflow-dsl). "
            "Owner: K3 DSL/Workflow. .cancel_workflow(workflow_id, reason) "
            "builder method + CancelWorkflowProcessor + manage.py workflow "
            "cancel. default-ON."
        ),
    )

    workflow_versioning_ui_enabled: bool = Field(
        default=True,
        title="K3 S12 W8: UI для WorkflowVersionRegistry (page 18)",
        description=(
            "K3 Sprint 12 Wave 8 (wave:s12/k3-w8-workflow-versioning-ui). "
            "Owner: K3 DSL/Workflow. Page 18 + admin_workflow_versioning REST: "
            "pin/rollback/history/running-count. Depends on "
            "workflow_versioning_strict ON. default-ON."
        ),
    )

    ai_workflow_examples_enabled: bool = Field(
        default=False,
        title="K4 S12 W1: 3 production AI workflow examples",
        description=(
            "K4 Sprint 12 Wave 1 (wave:s12/k4-w1-ai-workflow-examples-lib). "
            "Owner: K4 AI/Data. rag_augmented_saga + multi_agent_supervisor + "
            "code_interpreter_loop в extensions/credit_pipeline/workflows/. "
            "Depends on extensions_credit_workflow ON. default-OFF."
        ),
    )

    ai_workflow_cost_estimation_enabled: bool = Field(
        default=True,
        title="K4 S12 W2: LLM cost estimation для AI workflow",
        description=(
            "K4 Sprint 12 Wave 2 (wave:s12/k4-w2-llm-workflow-cost-est). "
            "Owner: K4 AI/Data. LLMModelPricing + _estimate_llm_cost + AI "
            "breakdown tab в page 15. Depends on workflow_cost_estimation_enabled. "
            "default-ON."
        ),
    )

    workflow_template_streamlit_enabled: bool = Field(
        default=True,
        title="K5 S12 W1: workflow templates Streamlit (page 33 extension)",
        description=(
            "K5 Sprint 12 Wave 1 (wave:s12/k5-w1-workflow-template-streamlit). "
            "Owner: K5 Frontend+Ext. Page 33 extension: route/workflow templates "
            "toggle + Mermaid render + visualize.py:to_mermaid. default-ON."
        ),
    )

    hitl_history_enabled: bool = Field(
        default=True,
        title="K5 S12 W2: HITL history viewer (page 72 tab)",
        description=(
            "K5 Sprint 12 Wave 2 (wave:s12/k5-w2-hitl-history-viewer). "
            "Owner: K5 Frontend+Ext. HitlHistoryService + History tab в page 72 "
            "+ hitl/history endpoint + emit hitl.* events. Depends on "
            "hitl_panel_enabled. default-ON."
        ),
    )

    workflow_cron_dashboard_enabled: bool = Field(
        default=True,
        title="K5 S12 W3: cron schedule dashboard (page 14)",
        description=(
            "K5 Sprint 12 Wave 3 (wave:s12/k5-w3-cron-dashboard). "
            "Owner: K5 Frontend+Ext. Page 14 + CronDashboardService + run-now "
            "endpoint. Depends on workflow_cron_builder_enabled. default-ON."
        ),
    )

    # ─── Sprint 15 — DX Tooling + Innovation ──────────────────────────────
    sandbox_amortised_psutil: bool = Field(
        default=False,
        title="K1 S15 W2: amortised psutil snapshots в PluginSandboxAdapter (F-2)",
        description=(
            "K1 Sprint 15 Wave 2 (wave:s15/k1-w3-sandbox-overhead-reduction). "
            "Owner: K1 Security. Активирует ленивые psutil snapshots в "
            "_with_resource_limits — пропуск enforcement при max_memory_mb==0, "
            "кэшируемый psutil.Process(), fire-and-forget cleanup через "
            "TaskRegistry. Снимает F-2 carryover (overhead 137% → <5%). "
            "default-OFF до validation perf-bench и ADR-0063 Accepted."
        ),
    )

    arch_map_llm_search_enabled: bool = Field(
        default=False,
        title="K4 S15 W18: Arch Map semantic search через LiteLLM (page 83)",
        description=(
            "K4 Sprint 15 Wave 18 (wave:s15/k4-w2-arch-map-llm-search). "
            "Owner: K4 AI/Innovation. Активирует ArchMapLLMSearch — semantic "
            "search по графу архитектуры через LiteLLM gateway + capability "
            "ai.search.arch_map. При False — fallback на keyword grep. "
            "default-OFF до staging-smoke с LiteLLM + audit-event coverage."
        ),
    )

    ai_pr_review_enabled: bool = Field(
        default=False,
        title="K4 S15 W16: AI PR review GitHub Action (Claude API + WAF)",
        description=(
            "K4 Sprint 15 Wave 16 (wave:s15/k4-w1-ai-pr-review). "
            "Owner: K4 AI/Innovation. Активирует .github/workflows/ai-pr-review.yml "
            "Claude API review через make_http_client (WAF compliance). "
            "При False — workflow self-skip через if-condition. "
            "default-OFF до публикации ANTHROPIC_API_KEY secret и smoke."
        ),
    )

    dsl_visual_editor_drag_drop: bool = Field(
        default=False,
        title="K3 S15 W10: DSL Visual Editor drag-drop + BPMN export (page 31)",
        description=(
            "K3 Sprint 15 Wave 10 (wave:s15/k3-w2-dsl-visual-editor-finale). "
            "Owner: K3 DSL/LSP. Активирует drag-drop через streamlit-elements "
            "+ BPMN 2.0 export через lxml + undo/redo stack в session_state. "
            "При False — page 31 в read-only режиме. "
            "default-OFF до staging-smoke с reference workflow."
        ),
    )

    changelog_autogen_enabled: bool = Field(
        default=False,
        title="K5 S15 W15: changelog autogen из wave-tags (make release-notes)",
        description=(
            "K5 Sprint 15 Wave 15 (wave:s15/k5-w4-changelog-autogen). "
            "Owner: K5 DX/Docs. Активирует tools/changelog_autogen.py — "
            "парсинг [wave:sXX/...] тегов из git log + группировка по "
            "спринтам/командам + Conventional Commits. При False — "
            "make release-notes возвращает no-op. "
            "default-OFF до calibration на S0-S14 истории."
        ),
    )

    # ─── Sprint 17 — GAP P0 Closure + Centralization Hardening ────────────
    config_validator_enabled: bool = Field(
        default=False,
        title="K1 S17 W4: ConfigValidator startup-fail при production-unsafe конфиге",
        description=(
            "K1 Sprint 17 Wave W4 (D14). Owner: K1 Security. ETA: S17. "
            "Активирует core/config/validator.py::ConfigValidator в lifespan: "
            "11 правил cross-settings (WAF strict/allow_hosts/clamav, swagger/redoc, "
            "admin IPs, vault, CORS, DEBUG+PROD, JWT_SECRET ≥32, feature-flag deps). "
            "При CRITICAL в production — startup-fail с reason-chain. "
            "default-OFF до калибровки правил и staging-smoke."
        ),
    )

    metrics_registry_strict: bool = Field(
        default=False,
        title="K2 S17 W1: MetricsRegistry strict (отказ при inline Counter/Histogram/Gauge)",
        description=(
            "K2 Sprint 17 Wave W1+W2 (D11). Owner: K2 Observability. ETA: S17. "
            "Активирует strict-режим infrastructure/observability/metrics_registry.py — "
            "Counter/Histogram/Gauge регистрируются ТОЛЬКО через MetricsRegistry "
            "с обязательными labels {tenant_id, route_id, component, env}. "
            "default-OFF до миграции 52 inline callsites."
        ),
    )

    task_registry_strict: bool = Field(
        default=False,
        title="K2 S17 W3: TaskRegistry obligatory (CI gate fail-on-orphans)",
        description=(
            "K2 Sprint 17 Wave W3 (D13a). Owner: K2 Observability. ETA: S17. "
            "Активирует strict-режим TaskRegistry: все asyncio.create_task через "
            "registry + copy_context() propagation. CI gate "
            "tools/checks/check_task_registry.py --fail-on-orphans. "
            "default-OFF до миграции 34 orphan callsites."
        ),
    )

    apscheduler_metrics: bool = Field(
        default=False,
        title="K2 S17 W4: APScheduler Prometheus exporter + Grafana alert",
        description=(
            "K2 Sprint 17 Wave W4 (D13b). Owner: K2 Observability. ETA: S17. "
            "Активирует APSchedulerMetricsExporter — job_executions_total / "
            "job_misfires_total / job_duration_seconds. Grafana alert на "
            "missing-jobs > 0 в окне 5m. default-OFF до развёртывания Grafana dashboard."
        ),
    )

    authz_gateway_enabled: bool = Field(
        default=False,
        title="K1 S17 W2: AuthorizationGateway единый фасад (Casbin+OPA+CapabilityGate)",
        description=(
            "K1 Sprint 17 Wave W2 (ADR-NEW-1+ADR-NEW-4, K-ARCH-1+K-ARCH-2). "
            "Owner: K1 Security. ETA: S17. "
            "Активирует core/security/authorization_gateway.py::AuthorizationGateway "
            "+ core/interfaces/capability_gateway.py::CapabilityGatewayProtocol. "
            "Цепочка: CapabilityGate → CapabilityPolicy → Casbin → OPA с единым "
            "correlation_id. Audit-event authorization.decision на каждое решение. "
            "default-OFF до миграции всех non-public endpoint-guard'ов."
        ),
    )

    audit_correlation_required: bool = Field(
        default=False,
        title="K3 S17 W3: correlation_id обязателен в 100% audit events (D12)",
        description=(
            "K3 Sprint 17 Wave W3 (D12). Owner: K3 Routes. ETA: S17. "
            "Активирует strict-валидацию: audit emit БЕЗ correlation_id поднимает "
            "AuditCorrelationError. Propagation через contextvars в MW → "
            "audit → outbound_http → DSL processors. End-to-end test: "
            "3+ источников в SELECT * FROM audit WHERE correlation_id = X. "
            "default-OFF до миграции всех audit callsites."
        ),
    )

    tenant_feature_flag_ui: bool = Field(
        default=False,
        title="K5 S17 W1: per-tenant feature-flag toggle REST + Streamlit UI (D9)",
        description=(
            "K5 Sprint 17 Wave W1 (D9). Owner: K5 Frontend. ETA: S17. "
            "Активирует endpoint POST /admin/feature-flags/<flag>/tenant/<id> + "
            "Redis pub/sub broadcast (<100ms) + audit + Streamlit page. "
            "default-OFF до интеграции с TenantFeatureFlagService и smoke."
        ),
    )

    resilience_coordinator_enabled: bool = Field(
        default=False,
        title="K2 S17 W5: ResilienceCoordinator class (12 fallback chains в lifespan)",
        description=(
            "K2 Sprint 17 Wave W5. Owner: K2 Resilience. ETA: S17. "
            "Активирует core/resilience/coordinator.py::ResilienceCoordinator — "
            "регистрация 12 fallback chains (Graylog/GenAI/Redis/ClickHouse/...) "
            "в lifespan startup. default-OFF до chaos-теста coordinator-isolation."
        ),
    )

    routes_capability_gate_strict: bool = Field(
        default=False,
        title="K3 S17 W0: routes capability-gate strict (K-ARCH-3)",
        description=(
            "K3 Sprint 17 Wave W0 (K-ARCH-3). Owner: K3 Routes. ETA: S17. "
            "Активирует strict-режим в services/routes/loader.py:70 — "
            "capability_gate.declare(route.capabilities) ДО pipeline_registrar. "
            "Route без declared capabilities → RouteRegistrationError. "
            "Audit-event route.capabilities.allocated. "
            "default-OFF до миграции existing routes на declared-capabilities."
        ),
    )

    routes_tenant_aware_strict: bool = Field(
        default=False,
        title="K3 S17 W0: RouteManifestV11.tenant_aware строгий (K-ARCH-4)",
        description=(
            "K3 Sprint 17 Wave W0 (K-ARCH-4). Owner: K3 Routes. ETA: S17. "
            "Активирует пробрасывание RouteManifestV11.tenant_aware в "
            "TenantContext.current_tenant() через RouteLoader. DSL шаги "
            "crud_* / proxy / dispatch_action получают tenant-фильтр. "
            "End-to-end test: tenant A не видит данные tenant B. "
            "default-OFF до миграции existing routes на tenant_aware=true."
        ),
    )

    call_function_whitelist_strict: bool = Field(
        default=False,
        title="K1 S17 W3: call_function whitelist обязателен в production (K-ARCH-5)",
        description=(
            "K1 Sprint 17 Wave W3 (K-ARCH-5). Owner: K1 Security. ETA: S17. "
            "При True dsl/engine/processors/function_call.py убирает dev fallback: "
            "if ENVIRONMENT == 'production' and not whitelist → PermissionError. "
            "CapabilityGate.check(`function.call.<module>`) обязательно. "
            "default-OFF до аудита всех plugin.toml::call_function_modules."
        ),
    )

    saga_state_persistence_enabled: bool = Field(
        default=False,
        title="K3 S17 W4: Saga state persistence в PostgreSQL (K-OPS-1)",
        description=(
            "K3 Sprint 17 Wave W4 (K-OPS-1). Owner: K3 Routes. ETA: S17. "
            "Активирует infrastructure/workflow/saga_state.py::SagaStateModel "
            "(PostgreSQL table) — checkpoints / compensations / rollback-events. "
            "CRUD repository + интеграция с Temporal Workflow signal_event. "
            "default-OFF до alembic migration + integration test compensation."
        ),
    )

    # ─── Sprint 21 — Resilience & Multi-tenancy ───────────────────────────
    rls_postgres_enforce: bool = Field(
        default=False,
        title="K1 S21 W1: PostgreSQL Row-Level Security + SET LOCAL tenant_id",
        description=(
            "K1 Sprint 21 Wave 1 (B-03/G-08, ADR-NEW-12). Owner: K1 Security. "
            "Активирует Alembic-policy ENABLE ROW LEVEL SECURITY на tenant-aware "
            "таблицах (начало: workflow_instance) + SQLAlchemy event listener "
            "SET LOCAL app.tenant_id из current_tenant() ContextVar на каждом "
            "begin-tx. При False — RLS-политики не накладываются (legacy WHERE filter). "
            "default-OFF до полного аудита tenant_id колонок и staging-smoke. "
            "Источник: gap-analysis/DEEP-RESEARCH-gd_integration_tools-2026-05-20.md."
        ),
    )

    tenant_cache_prefix_enabled: bool = Field(
        default=False,
        title="K1 S21 W2: TenantCacheBackend wrapper с auto-prefix tenant:{id}:",
        description=(
            "K1 Sprint 21 Wave 2 (B-03 closure). Owner: K1 Security. "
            "Активирует infrastructure/cache/tenant_wrapper.py::TenantCacheBackend — "
            "auto-prefix всех cache-keys через tenant ContextVar. "
            "При False — wrapping no-op (прямая делегация в underlying backend). "
            "default-OFF до миграции callsites get/set на wrapped backend и smoke."
        ),
    )

    rpa_resilience_wrapper_enabled: bool = Field(
        default=False,
        title="K2 S21 W3: RPACallPolicy единый resilience-фасад для RPA/CDC/FileWatcher",
        description=(
            "K2 Sprint 21 Wave 3 (B-02 closure, ADR-NEW-13). Owner: K2 Resilience. "
            "Активирует core/resilience/rpa_policy.py::RPACallPolicy — композиция "
            "tenacity retry + pybreaker + DLQ для browser_pool/cdc/file_watcher/"
            "webhook_scheduler/desktop_rpa_client. При False — call-сайты используют "
            "legacy ad-hoc try/except (события теряются без DLQ). "
            "default-OFF до миграции 5 callsites и toxiproxy-теста."
        ),
    )

    scheduler_dlq_enabled: bool = Field(
        default=False,
        title="K2 S21 W4: APScheduler EVENT_JOB_ERROR → DLQ writer (G-09)",
        description=(
            "K2 Sprint 21 Wave 4 (G-09 closure). Owner: K2 Resilience. "
            "Активирует infrastructure/scheduler/dlq.py — listener для "
            "EVENT_JOB_ERROR пишет failed job в DLQWriter с kind='scheduler_job'. "
            "Admin endpoint /admin/scheduler/dlq (list/retry/delete) — RBAC OPERATOR/SUPER_ADMIN. "
            "default-OFF до интеграции с UnifiedDLQ Postgres backend и audit."
        ),
    )

    webhook_resilience_policy_enabled: bool = Field(
        default=False,
        title="K2 S21 W5: WebhookSink + webhook_scheduler через RPACallPolicy (G-07)",
        description=(
            "K2 Sprint 21 Wave 5 (G-07 closure). Owner: K2 Resilience. "
            "Активирует обёртку send()/execute_webhook() через RPACallPolicy — "
            "tenacity retry + pybreaker per-host + DLQ при исчерпании budget. "
            "При False — webhook вызовы используют legacy try/except (события теряются). "
            "default-OFF до интеграции с RPACallPolicy (W3) и chaos-теста 5xx burst."
        ),
    )

    desktop_rpa_session_pool_enabled: bool = Field(
        default=False,
        title="K3 S21 W6: DesktopRPASessionPool persistent httpx-AsyncClient (F-12/B-09)",
        description=(
            "K3 Sprint 21 Wave 6 (F-12 + B-09 closure). Owner: K3 RPA. "
            "Активирует services/rpa/desktop_session_pool.py — pool persistent "
            "httpx-clients с session affinity по app_name, auto-reconnect на stale "
            "handle, TTL 30 min через TaskRegistry. При False — DesktopRpaClient "
            "создаёт новый httpx-instance на каждый вызов (B-09). "
            "default-OFF до warm 5 sessions smoke + reconnect-теста."
        ),
    )

    browser_cookies_redis_persist: bool = Field(
        default=False,
        title="K3 S21 W7: Browser session cookies persistence через Redis hash (G-06)",
        description=(
            "K3 Sprint 21 Wave 7 (G-06 closure). Owner: K3 RPA. "
            "Активирует services/rpa/browser_pool.py::save_cookies/restore_cookies "
            "через Redis hash 'browser:session:{tenant}:{user}:{domain}' c TTL 24h. "
            "При False — каждый acquire() = новый login (S-L5-2). "
            "default-OFF до integration-теста на browser restart preservation."
        ),
    )

    workflow_state_sqlite_persist: bool = Field(
        default=False,
        title="K3 S21 W8: WorkflowState SQLAlchemy + saga compensating persistence (ADR-NEW-14)",
        description=(
            "K3 Sprint 21 Wave 8 (B-05 closure, ADR-NEW-14, carryover S17 K-OPS-1). "
            "Owner: K3 Workflow. "
            "Активирует infrastructure/workflow/saga_state.py::WorkflowState SQLAlchemy "
            "model + WorkflowStateRepository (save/load/list_compensating) + alembic "
            "migration. PGRunnerBackend checkpoint после step + restore compensating "
            "actions при retry. При False — checkpoints в памяти (теряются на restart, B-05). "
            "default-OFF до integration test 4 crash-recover сценариев."
        ),
    )

    # ─── K4 — Sprint 24 AI Safety Hardening (ADR-NEW-16/17/18) ─────────────
    presidio_pii_enabled: bool = Field(
        default=False,
        title="K4 S24 W1: Presidio + ru NER PII layer (ADR-NEW-16)",
        description=(
            "K4 Sprint 24 Wave 1 (gap-2026-05-22 P0-1, ADR-NEW-16). Owner: K4 AI/Data. "
            "Активирует services/ai/pii/presidio_analyzer.py — Presidio AnalyzerEngine "
            "+ AnonymizerEngine + spaCy ru_core_news_lg + 4 custom recognizers (INN, "
            "СНИЛС, паспорт РФ, номер кредитного дела). При True get_ai_sanitizer_provider() "
            "возвращает PresidioSanitizerAdapter; при False — legacy AIDataSanitizer "
            "(regex-based). default-OFF до `make pii-audit` precision/recall >= 0.9 "
            "на ru hybrid gold-set (1000 docs) + production-config rollout."
        ),
    )

    nemo_guardrails_enabled: bool = Field(
        default=False,
        title="K4 S24 W2: NeMo Guardrails + Llama Guard 3 defense-in-depth (ADR-NEW-17)",
        description=(
            "K4 Sprint 24 Wave 2 (gap-2026-05-22 P0-2, ADR-NEW-17). Owner: K4 AI/Data. "
            "Активирует self-hosted defense-in-depth pipeline: NeMo Guardrails (Colang "
            "input rails, jailbreak detection, banking topic filter) + Llama Guard 3 "
            "output classifier (vLLM/TGI). Per-tenant policy через tenant_config.py. "
            "При False — только Rebuff/Lakera SaaS-вызовы по существующим capabilities. "
            "default-OFF до 100/100 jailbreak gold-set (block rate >= 95%) + p95 <= 80ms."
        ),
    )

    langgraph_checkpointer_enabled: bool = Field(
        default=False,
        title="K4 S24 W3: LangGraph PostgresCheckpointer + Mem0 unified memory (ADR-NEW-18)",
        description=(
            "K4 Sprint 24 Wave 3 (gap-2026-05-22 P0-3, ADR-NEW-18). Owner: K4 AI/Data. "
            "Активирует langgraph-checkpoint-postgres для durable graph-state "
            "MultiAgentSupervisor + Mem0 OSS на pgvector как unified long-term memory "
            "(поверх legacy LangMemService). При False — graph state in-memory, "
            "LangMemService default-OFF. default-OFF до chaos-test resume-after-crash "
            "4/4 + LangMem consolidate() рефакторинга через Mem0."
        ),
    )

    # ─── K4 — Sprint 25 AI Gateway + Policy DSL (ADR-NEW-19/20/21) ────────
    ai_gateway_enforce: bool = Field(
        default=False,
        title="K4 S25 W1: AIGateway единая точка входа в AI (ADR-NEW-19)",
        description=(
            "K4 Sprint 25 Wave 1 (ADR-NEW-19, PLAN.md V22.4 §S25). Owner: K4 AI/Data + К1 Security. "
            "При True все LLM-вызовы проходят через AIGateway.invoke() pipeline "
            "(policy_resolve → sanitize → guards → render → invoke_llm → "
            "output_guards → output_sanitize → audit → cost). При False — "
            "scaffold-pass-through через _legacy_invoke (3 кодопути сохраняют интерфейс). "
            "default-OFF до S27 closure: 100% callsites обёрнуты, "
            "`make ai-gateway-coverage` strict zero violations."
        ),
    )

    ai_policy_enforce: bool = Field(
        default=False,
        title="K2 S25 W2: AIPolicySpec + PolicyResolver обязательная резолюция (ADR-NEW-20)",
        description=(
            "K2 Sprint 25 Wave 2 (ADR-NEW-20). Owner: K2 DSL + К4 AI. "
            "При True AIGateway.invoke() требует resolved AIPolicySpec из "
            "ai_policies/*.policy.yaml (PolicyResolver lookup workflow_id + tenant_id). "
            "Без подходящей политики (`required=true`) — поднимает PolicyNotResolvedError. "
            "При False — fallback `AIPolicySpec(name='default', required=False)`. "
            "default-OFF до миграции 100% workflow → policy + JSON-Schema валидация."
        ),
    )

    ai_pii_tokenizer_enabled: bool = Field(
        default=False,
        title="K1 S25 W4: PIITokenizer reversible mask/unmask round-trip (ADR-NEW-21)",
        description=(
            "K1 Sprint 25 Wave 4 (ADR-NEW-21). Owner: K1 Security. "
            "Активирует core/security/pii_tokenizer.py — reversible маскировка "
            "PII через Presidio (S24 W1) + UUIDv7-токены + AES-GCM шифрованный "
            "TokenRegistry в Redis (TTL = policy.ttl_s). Обязателен для банковских "
            "use-case'ов (LLM генерирует ответ клиенту по договору → unmask перед "
            "отправкой). При False — DSL pii_mask/pii_unmask отключены, доступен "
            "только legacy PIIMasker (irreversible). default-OFF до roundtrip-теста "
            "500/500 exact-match + AES-GCM encryption verified at-rest."
        ),
    )

    # ─── Sprint 26 — Prompts Pipeline + Skills Registry (ADR-NEW-22) ──────
    ai_prompt_sweep_strict: bool = Field(
        default=False,
        title="K4 S26 W1: AST-checker блокирует hardcoded `system_prompt=` (sweep)",
        description=(
            "K4 Sprint 26 Wave 1 (PLAN.md V22.4 §S26). Owner: K4 AI/Data. "
            "При True `tools/checks/check_hardcoded_prompts.py` валит CI при наличии "
            'литералов `system_prompt=`, `system_message=`, `system="..."` длиннее '
            "50 символов в src/backend/ (вне allowlist). При False — warn-only. "
            "default-OFF первый месяц после S26 W1 sweep → ON в S27 closure."
        ),
    )

    ai_prompt_eval_blocking: bool = Field(
        default=False,
        title="K4 S26 W4: RAGAS CI-gate blocking mode (faithfulness/answer_relevancy)",
        description=(
            "K4 Sprint 26 Wave 4 (PLAN.md V22.4 §S26). Owner: K4 AI/Data + К3 CI. "
            "При True `make ai-prompt-eval` валит PR при `faithfulness < 0.8` "
            "или `answer_relevancy < 0.75` на 500 gold-set. При False — warn-only "
            "(nightly cron). default-OFF первый месяц после S26 W4 → ON в S27 closure."
        ),
    )

    ai_skill_toml_enabled: bool = Field(
        default=False,
        title="K2 S26 W5: SkillRegistry V11.2 TOML-manifest loader (ADR-NEW-22)",
        description=(
            "K2 Sprint 26 Wave 5 (ADR-NEW-22). Owner: K2 DSL. "
            "При True SkillRegistry.from_toml_manifest() загружает skills из "
            "plugin.toml [[skill]] секции (id, version, handler, capabilities, "
            "policy_ref, protocols, timeout_s). Auto-export в MCP + LangGraph + "
            "OpenAI tools. Hot-reload через watchfiles ≤2s. При False — только "
            "legacy @agent_tool Python-декоратор путь. default-OFF до JSON-Schema "
            "валидации `make skill-schema` 100% extension манифестов."
        ),
    )

    # ─── Sprint 27 — Agent DSL + MCP Gateway + Audit Unified ──────────────
    ai_agent_dsl_enabled: bool = Field(
        default=False,
        title="K2 S27 W1: Agent DSL processors (agent_run/branch/loop/parallel)",
        description=(
            "K2 Sprint 27 Wave 1 (PLAN.md V22.4 §S27). Owner: K2 DSL + К4 AI. "
            "При True регистрирует 9 новых DSL processors: agent_run, agent_branch, "
            "agent_loop, agent_parallel, guardrails_apply, pii_mask, pii_unmask, "
            "skill_invoke, memory_recall/store. Все через AIGateway. Builder fluent "
            ".agent_run()/.ai_invoke()/.guardrails_apply()/.pii_mask()/.ai_memory_*(). "
            "default-OFF до ≥90% coverage unit-тестами + PoC route credit_check_demo."
        ),
    )

    mcp_gateway_namespaces_enabled: bool = Field(
        default=False,
        title="K3 S27 W4: MCP Gateway domain namespaces + trusted external (ADR-NEW-23)",
        description=(
            "K3 Sprint 27 Wave 4 (ADR-NEW-23). Owner: K3 Frontend/Ops + К1 Security. "
            "При True split монолита mcp_server.py на 3 namespace (credit/analytics/"
            "system) через MCPGateway aggregator (backward-compat). MCPClientRegistry "
            "для trusted external — все запросы через OutboundHttpClient + WAF "
            "capability net.outbound.<host>:external. FastMCP 3.2.4+ JWTAuthProvider "
            "через SSO. default-OFF до integration-теста `mcp.tools.count() == "
            "pre_split_count` + 1 external MCP smoke."
        ),
    )

    ai_audit_unified_enabled: bool = Field(
        default=False,
        title="K3 S27 W5: AI Audit Unified Schema `ai.invocation.*` (ADR-NEW-24)",
        description=(
            "K3 Sprint 27 Wave 5 (ADR-NEW-24). Owner: K3 Frontend/Ops + К1 Security. "
            "При True 9 типов событий ai.invocation.{requested|policy_resolved|"
            "sanitized|guarded|completed|denied|failed|pii.mask|pii.unmask} эмитятся "
            "через единый AuditService (S17/K3). LangfuseOTelAuditSink экспортирует в "
            "Langfuse v3 OTel. Legacy audit_clickhouse.py deleted (миграция в S26 "
            "dual-write). PII в audit-payload маскируется через mask_irreversible. "
            "default-OFF до ClickHouse query coverage 100% AIGateway путей."
        ),
    )

    workflow_invoke_agent_enabled: bool = Field(
        default=False,
        title="K2 S27 W6: WorkflowBuilder.invoke_agent() — LangGraph через Temporal activity",
        description=(
            "K2 Sprint 27 Wave 6 (R-V15-9 «AI-функции через Workflow DSL»). "
            "Owner: K2 DSL + К4 AI. "
            "При True WorkflowBuilder.invoke_agent(agent_name, durable=True) "
            "оборачивает LangGraph multi-agent supervisor в Temporal activity "
            "с LangGraph Checkpointer integration (S24 W3). При False — invoke_agent "
            "поднимает FeatureDisabledError. default-OFF до chaos-теста "
            "kill-worker-mid-conversation → resume successful ≥ 2 turn."
        ),
    )

    # ─── Sprint 18 — Operational + Security GAP Carryover (backbone) ──────
    waf_strict_zero_allowlist: bool = Field(
        default=False,
        title="K1 S18 W1: WAF strict — нулевой allowlist (все :external через make_http_client)",
        description=(
            "K1 Sprint 18 Wave 1 (PLAN.md V22 §S18). Owner: K1 Security. "
            "При True tools/check_waf_coverage.py требует пустой allowlist; "
            "23 callsites из tools/check_waf_coverage_allowlist.txt должны быть "
            "мигрированы на OutboundHttpClient через core.net.make_http_client(). "
            "default-OFF до завершения миграции (express_bot / telegram_bot / opa / "
            "clickhouse / vault_cipher / ml_inference / proxy / imports / webhooks / "
            "search_providers / Vault×2 / bots×2) и make check-waf-coverage exit 0."
        ),
    )

    failing_tests_quarantined_off: bool = Field(
        default=False,
        title="K2 S18 W2: failing tests quarantine off (~91 pre-existing tests triage)",
        description=(
            "K2 Sprint 18 Wave 2 (PLAN.md V22 §S18). Owner: K2 Resilience+Quality. "
            "При True CI требует zero quarantined pre-existing failing tests; "
            "каждый тест должен быть либо fix / либо xfail-с-ADR / либо skip-под-FF. "
            "default-OFF до завершения triage ~91 теста (coverage ratchet 50→70%)."
        ),
    )

    sandbox_amortised_final: bool = Field(
        default=False,
        title="K1 S18 W5: plugin trust 2-tier (Tier-A signed / Tier-B sandboxed) — ADR-NEW-6",
        description=(
            "K1 Sprint 18 Wave 5 (ADR-NEW-6 / B-4, PLAN.md V22 §S18). Owner: K1 Security. "
            "При True plugin.toml::trust_tier = 'A' | 'B' обязателен. Tier-A (signed by "
            "org-CA cosign) — runtime sandbox disabled; isolation через capability-gate "
            "+ code-review CI + supply-chain. Tier-B (untrusted/external) — strict e2b/"
            "pyodide. F-2 closure через model change, не sandbox-tuning. "
            "default-OFF до cosign-signing pipeline integration в make security."
        ),
    )

    core_entities_legacy_off: bool = Field(
        default=False,
        title="K3 S18 W3: core_entities legacy removal (users/orders/orderkinds final cleanup)",
        description=(
            "K3 Sprint 18 Wave 3 (PLAN.md V22 §S18). Owner: K3 Routes. "
            "При True services/core/{users.py,orders.py,orderkinds.py} удаляются; "
            "все импортёры переключены на extensions/core_entities/ (S17 W3 carryover). "
            "default-OFF до 0 импортов legacy путей в src/backend/."
        ),
    )

    eventbus_dsl_enabled: bool = Field(
        default=False,
        title="K3 S18 W4: RouteBuilder .to_eventbus()/.from_eventbus() DSL",
        description=(
            "K3 Sprint 18 Wave 4 (V22 NEW, PLAN.md §S18). Owner: K3 DSL. "
            "При True активирует RouteBuilder.to_eventbus(topic, payload_ref) + "
            ".from_eventbus(topic_pattern, ack_mode) + 2 step-type (eventbus_publish / "
            "eventbus_subscribe). EventBus production backend — S19 W12 (R1.8). "
            "default-OFF до integration теста через EventBusBackend facade."
        ),
    )

    langfuse_production_wired: bool = Field(
        default=False,
        title="K4 S18 W1: LangFuse production wiring + cost dashboard",
        description=(
            "K4 Sprint 18 Wave 1 (PLAN.md V22 §S18). Owner: K4 AI/Data. "
            "При True LangFuse callbacks v3 подключены в production (ai_workflow_handlers "
            "rag_query/multi_agent_supervisor/e2b_execute); AI cost dashboard собирает "
            "tokens × cost_usd per tenant/workflow. default-OFF до staging-smoke "
            "с LangFuse instance и cost-dashboard валидации."
        ),
    )

    opa_runtime_query_enabled: bool = Field(
        default=False,
        title="K1 S18 W3: OPA runtime-query + Casbin tenant-scoped enforcer (S-L8-1/S-L8-2)",
        description=(
            "K1 Sprint 18 Wave 3 (PLAN.md V22 §S18, S-L8-1, S-L8-2). Owner: K1 Security. "
            "При True CapabilityPolicy интегрирован с Casbin tenant-scoped enforcer; "
            "AuthorizationGateway.opa_step() выполняет runtime-query к OPA-серверу; "
            "политики живут в infrastructure/policy/opa/policies/*.rego. "
            "default-OFF до smoke-test allow/deny decision + OPA-server в staging."
        ),
    )

    multi_tenant_rate_limit_enabled: bool = Field(
        default=False,
        title="K5 S18 W1: global rate-limit middleware (fastapi-limiter + per-tenant)",
        description=(
            "K5 Sprint 18 Wave 1 (PLAN.md V22 §S18, P0 Gateway-centralization). "
            "Owner: K5 Frontend/Ops. При True entrypoints/middlewares/global_rate_limit.py "
            "RateLimitMiddleware активна: global default + per-route override + per-tenant "
            "namespace через Casbin/OPA. Базируется на fastapi-limiter (Redis backend). "
            "default-OFF до интеграции с TenantContext + staging-smoke."
        ),
    )

    pii_response_middleware_enabled: bool = Field(
        default=False,
        title="K3 S18 W1: PIIMaskingResponseMiddleware (S-L8-4) — глобальная маскировка JSON-ответов",
        description=(
            "K3 Sprint 18 Wave 1 (PLAN.md V22 §S18 W5, S-L8-4). Owner: K3 DSL/Routes. "
            "При True entrypoints/middlewares/pii_masking_response.py применяет "
            "core.security.pii_masker.default_masker к JSON-телам ответов на "
            "configurable path patterns (8 типов PII: jwt/iban/snils/card/passport/"
            "email/inn/phone). Унифицирует с DSL processor mask_pii и audit PII "
            "masking (foundation для S22 W1 A-07 PII Masker Unification). "
            "default-OFF до интеграции с RequestContext + smoke-test на realistic "
            "API path matrix."
        ),
    )

    per_route_timeout_enabled: bool = Field(
        default=False,
        title="K3 S18 W2: per-route timeout (route.toml [timeout] + DSL .policy.timeout)",
        description=(
            "K3 Sprint 18 Wave 2 (PLAN.md V22 §S18 W6, P0 Gateway-centralization gap). "
            "Owner: K3 DSL/Routes. При True TimeoutMiddleware читает per-route "
            "registry (path-prefix → total seconds) и применяет route-specific cap "
            "вместо global settings.secure.request_timeout. Fallback на global "
            "default при отсутствии match. Source-of-truth: "
            "RouteManifestV11.timeout (RouteTimeoutSpec dataclass) либо DSL "
            ".policy.timeout(total=...). default-OFF до wiring RouteLoader → "
            "TimeoutMiddleware registry в lifespan + smoke-test на realistic "
            "route matrix."
        ),
    )

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
