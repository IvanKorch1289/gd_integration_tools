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
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = (
    "FeatureFlags",
    "feature_flags",
)


class FeatureFlags(BaseSettingsWithLoader):
    """Реестр runtime feature-flag.

    Все flag — default-OFF. Имя поля → переменная окружения с префиксом FEATURE_,
    верхним регистром (waf_outbound_via_facade → FEATURE_WAF_OUTBOUND_VIA_FACADE).

    После закрытия Wave и подтверждения staging-smoke owner-команда переводит
    flag в default-ON в отдельном PR с обновлением audit-комментария.
    """

    yaml_group: ClassVar[str] = "features"
    model_config = SettingsConfigDict(
        env_prefix="FEATURE_",
        extra="forbid",
        validate_default=True,
    )

    # ─── K2 — Net & WAF ────────────────────────────────────────────────────
    metering_per_host: bool = Field(
        default=False,
        title="K2: per-host outbound metering (request_count, error_rate, p50/p95)",
        description=(
            "K2 Wave 1. Owner: K2 Net&WAF. ETA: S3-W1. "
            "Активирует PerHostMeter — rolling-window (1000 obs) метрики "
            "по каждому host: request_count, error_count, p50/p95 latency_ms. "
            "default-OFF до staging-smoke и интеграции с OutboundHttpClient."
        ),
    )

    connection_reuse_manager: bool = Field(
        default=False,
        title="K2: ConnectionReuseManager (idle ping + auto-recycle по lifetime)",
        description=(
            "K2 Wave 2. Owner: K2 Resilience. ETA: S3-W2. "
            "Активирует ConnectionReuseManager: проверку lifetime и idle-ping "
            "перед возвратом connection из pool. При False acquire() возвращает "
            "pool-объект без дополнительных проверок (нулевой overhead). "
            "default-OFF до интеграции в reference pools и staging-smoke."
        ),
    )

    waf_outbound_via_facade: bool = Field(
        default=False,
        title="WAF: внешние HTTP через OutboundHttpClient",
        description=(
            "K2 Wave 3. Owner: K2 Net&WAF. ETA: S2-W2. "
            "Маршрутизация всех :external HTTP-callsites через WAF-фасад. "
            "default-OFF до завершения миграции 38 callsites и staging-smoke. "
            "Переключение default-ON — отдельный PR после ADR-0053 Accepted."
        ),
    )

    # ─── K4 — Workflow ─────────────────────────────────────────────────────
    workflow_legacy_disabled: bool = Field(
        default=False,
        title="Workflow: отключить legacy infrastructure/workflow/state*",
        description=(
            "K4 Wave 1. Owner: K4 Workflow. ETA: S2-W1. "
            "При True блокирует все импорты из legacy 4 файлов "
            "(state.py/state_store.py/event_store.py/state_projector.py). "
            "default-OFF до миграции 19 импортёров на TemporalFacade."
        ),
    )

    workflow_yaml_round_trip: bool = Field(
        default=False,
        title="Workflow: YAML round-trip API (to_yaml/from_yaml/diff)",
        description=(
            "K4 Wave 2. Owner: K4 Workflow. ETA: S2-W2. "
            "Активирует to_yaml()/from_yaml()/diff() API на WorkflowBuilder. "
            "default-OFF до golden-snapshot тестов на 5 эталонных workflow."
        ),
    )

    workflow_bpmn_import: bool = Field(
        default=False,
        title="Workflow: BPMN 2.0 import через SpiffWorkflow 3.0",
        description=(
            "K4 Wave 3. Owner: K4 Workflow. ETA: S2-W3. "
            "Активирует SpiffWorkflow 3.0 → WorkflowSpec → Temporal compiler. "
            "default-OFF до research-spike ADR + sample-теста."
        ),
    )

    workflow_gateways_enabled: bool = Field(
        default=False,
        title="Workflow: XOR/AND/OR gateways (.gateway_xor/.gateway_and/.gateway_or)",
        description=(
            "K3 Wave 4. Owner: K3 Workflow DSL. ETA: S3-W4. "
            "Активирует gateway-примитивы BPMN-стиля в WorkflowBuilder: "
            "XOR (exclusive branching), AND (parallel wait_all), OR (inclusive wait_any). "
            "GatewaySpec + BranchSpec → GatewayCompiler → Temporal-IR dict. "
            "default-OFF до интеграции GatewayCompiler с emitter.py и staging-smoke."
        ),
    )

    # ─── K5 — DSL ──────────────────────────────────────────────────────────
    frontend_schema_registry_ui: bool = Field(
        default=False,
        title="Frontend: Schema Registry UI (6-tab viewer)",
        description=(
            "K5 Wave 1. Owner: K5 DSL. ETA: S3-W1. "
            "Активирует страницу 40_Schema_Registry.py — 6-tab viewer "
            "(OpenAPI / WSDL / XSD / Protobuf / AsyncAPI / GraphQL SDL) "
            "с Download / Validate / Diff. "
            "default-OFF до staging-smoke + интеграции с Schema-registry RAM (R1)."
        ),
    )

    frontend_action_bus_ui: bool = Field(
        default=False,
        title="K5: Action Bus Streamlit UI (список actions + invoke с JSON-payload)",
        description=(
            "K5 Wave 2. Owner: K5 DSL. ETA: S3-W2. "
            "Активирует страницу 50_Action_Bus.py с invoke registered actions, "
            "JSON-payload editor, 3 invoke modes (sync/async-fire-and-forget/async-api). "
            "default-OFF до staging-smoke action-bus-client."
        ),
    )

    dsl_processor_registry_strict: bool = Field(
        default=False,
        title="DSL: ProcessorRegistry strict mode (отказ при missing schema)",
        description=(
            "K5 Wave 3. Owner: K5 DSL. ETA: S2-W3. "
            "Активирует строгий режим ProcessorRegistry: процессоры без "
            "reflection-schema не регистрируются. default-OFF до 100% "
            "покрытия 77 процессоров."
        ),
    )

    dsl_route_hot_reload: bool = Field(
        default=False,
        title="DSL: hot-reload для routes/<name>/ (<3s)",
        description=(
            "K5 Wave 5. Owner: K5 DSL. ETA: S2-W5. "
            "Активирует watchfiles-based reload routes/<name>/route.toml. "
            "default-OFF в production; default-ON в dev профиле."
        ),
    )

    admin_marketplace_endpoints: bool = Field(
        default=False,
        title="Admin: Action-Bus + Plugin-Marketplace REST endpoints",
        description=(
            "K5 Wave 4. Owner: K5 DSL. ETA: S3-W4. "
            "Активирует /api/v1/admin/actions/* и /api/v1/admin/plugins/* — "
            "backend endpoints для Streamlit 50_Action_Bus.py + 60_Plugin_Marketplace.py. "
            "default-OFF до staging-smoke и интеграции с ActionHandlerRegistry + PluginLoader."
        ),
    )

    # ─── K6 — AI ───────────────────────────────────────────────────────────
    search_provider_searxng: bool = Field(
        default=False,
        title="Search: SearXNGProvider в WebSearchService fallback chain",
        description=(
            "K4 Wave 4 (PLAN #5). Owner: K4 AI/Data. ETA: S3-W3. "
            "Активирует SearXNGProvider в fallback chain WebSearchService — "
            "self-hosted privacy-first meta-search. Требует SEARXNG_BASE_URL env. "
            "default-OFF до развёртывания SearXNG instance в staging."
        ),
    )

    langmem_enabled: bool = Field(
        default=False,
        title="AI: LangMem long-term memory (episodic/semantic/procedural)",
        description=(
            "K6 Wave 1 (K4 LangMem baseline). Owner: K4 AI/Data. ETA: S3-W1. "
            "Активирует LangMemService в src/backend/services/ai/memory/. "
            "При False все вызовы remember_*/recall возвращают пустые результаты "
            "без записи. default-OFF до staging-smoke с Postgres + Qdrant."
        ),
    )

    mcp_tools_input_schema_strict: bool = Field(
        default=False,
        title="MCP: строгая валидация input_schema для FastMCP tools",
        description=(
            "K6 Wave 2. Owner: K6 AI/RAG. ETA: S3-W2. "
            "При True — validate_input_schema() поднимает ValidationError "
            "вместо возврата (False, msg) при несоответствии JSON-Schema. "
            "default-OFF до полного покрытия Tier 1+2 actions параметрами."
        ),
    )

    langfuse_v3: bool = Field(
        default=False,
        title="AI: LangFuse 3.x callbacks",
        description=(
            "K6 Wave 1. Owner: K6 AI/RAG. ETA: S2-W1. "
            "Переключение на LangFuse 3.x SDK. default-OFF до полной "
            "миграции callbacks и smoke на 1 trace + generation."
        ),
    )

    rag_cache_l2_semantic: bool = Field(
        default=False,
        title="AI: RAG cache L2 (semantic match через embeddings)",
        description=(
            "K6 Wave 3. Owner: K6 AI/RAG. ETA: S2-W3. "
            "Активирует L2 semantic cache layer (L1 LRU уже работает). "
            "default-OFF до измерения hit-rate ≥30% в staging."
        ),
    )

    rag_cache_l3_retrieval: bool = Field(
        default=False,
        title="AI: RAG cache L3 (retrieval-graph cache)",
        description=(
            "K6 Wave 3. Owner: K6 AI/RAG. ETA: S2-W3. "
            "Активирует L3 retrieval-graph cache. default-OFF до завершения "
            "L2 stabilization."
        ),
    )

    ai_workspace_ttl_cleanup: bool = Field(
        default=False,
        title="AI: TTL cleanup для ${AI_WORKSPACE}/<tenant>/<session>/",
        description=(
            "K6 Wave 4. Owner: K6 AI/RAG. ETA: S2-W4. "
            "Активирует scheduled job (7 days TTL + size quota per tenant) "
            "для AI workspace в lifespan. default-OFF до audit-event-тестов."
        ),
    )

    prompt_registry_langfuse: bool = Field(
        default=False,
        title="AI: LangfusePromptStorage как backend для prompt-registry",
        description=(
            "K4 Sprint 3 Wave 3. Owner: K4 AI/Data. ETA: S3-W3. "
            "Активирует LangfusePromptStorage — хранение и версионирование "
            "промптов через Langfuse SDK (get/save/list). "
            "При False — используется in-memory fallback (PromptEntry store). "
            "default-OFF до staging-smoke с Langfuse instance и smoke-теста "
            "на 1 prompt round-trip."
        ),
    )

    multimodal_rag_enabled: bool = Field(
        default=False,
        title="AI: MultimodalRAG (text + image + audio embeddings и retrieval)",
        description=(
            "K6 Wave 4 (K4 W4 early scaffold). Owner: K4 AI/Data. ETA: S3-W4. "
            "Активирует MultimodalRAGService: ingestion трёх модальностей "
            "(text/image/audio) и семантический retrieval с modality filter. "
            "В scaffold-версии: dummy 384-dim embeddings + in-memory store. "
            "Production: CLIP (image) + Whisper→text (audio) + BGE-M3 (text). "
            "default-OFF до ML-deps stabilization и staging-smoke."
        ),
    )

    taskiq_removed: bool = Field(
        default=False,
        title="AI/Infrastructure: TaskIQ полностью удалён (R-V15-7)",
        description=(
            "K6 Wave 2 (cross-team blocker). Owner: K6 AI/RAG. ETA: S2-W3. "
            "При True блокирует все импорты taskiq и Invoker.ASYNC_QUEUE. "
            "13 callsites должны быть мигрированы на Temporal cron/APScheduler. "
            "default-OFF до завершения migration shim."
        ),
    )

    # ─── K3 — Builder source-сахар ────────────────────────────────────────
    builder_source_sugar: bool = Field(
        default=False,
        title="K3: Builder source-сахар (.from_kafka/.from_rabbit/.from_mqtt/...)",
        description=(
            "K3 Wave 5. Owner: K3 DSL. ETA: S3-W5. "
            "Активирует 8 classmethod'ов-фабрик SourcesMixin: "
            "from_cdc / from_kafka / from_rabbit / from_mqtt / "
            "from_redis_streams / from_filewatcher / from_webhook / from_schedule. "
            "При False методы работают в режиме совместимости (строковый source DSN). "
            "default-OFF до интеграции с SourceRegistry и staging-smoke."
        ),
    )

    service_toml_loader: bool = Field(
        default=False,
        title="K3: service.toml loader + ServiceDSLRegistry",
        description=(
            "K3 Wave 5. Owner: K3 DSL. ETA: S3-W5. "
            "Активирует загрузку manifest'ов *.service.toml из extensions/ "
            "и регистрацию ServiceSpec в ServiceDSLRegistry singleton. "
            "При False register() — no-op. "
            "default-OFF до интеграции с auto-registration в plugin-loader."
        ),
    )

    # ─── K3 — GraphQL Subscription Source ─────────────────────────────────
    graphql_subscription_source: bool = Field(
        default=False,
        title="K3: GraphQL subscription source (@strawberry.subscription via WebSocket)",
        description=(
            "K3 Wave 5. Owner: K3 DSL. ETA: S3-W5. "
            "Активирует GraphQLSubscriptionSource — async-генератор событий "
            "из GraphQL WebSocket-подписок (протокол graphql-ws, библиотека gql). "
            "default-OFF до установки 'gql[websockets]' и staging-smoke."
        ),
    )

    # ─── K3 — Email IMAP Source ────────────────────────────────────────────
    email_imap_source: bool = Field(
        default=False,
        title="K3: EmailIMAPSource через aioimaplib (IMAP IDLE, stream())",
        description=(
            "K3 Wave 5. Owner: K3 Email/IMAP. ETA: S3-W5. "
            "Активирует EmailIMAPSource — AsyncIterator[EmailMessage] поверх "
            "IMAP IDLE (aioimaplib). Используется .from_imap() в RouteBuilder. "
            "default-OFF до установки 'aioimaplib' в S3 cutover и staging-smoke."
        ),
    )

    # ─── K3 — Notification DSL ─────────────────────────────────────────────
    notification_dsl_enabled: bool = Field(
        default=False,
        title="K3: Notification DSL через Apprise (.notify / .notify_multi)",
        description=(
            "K3 Wave 1. Owner: K3 Notification. ETA: S3-W1. "
            "Активирует AppriseNotificationService и DSL-процессор notify_apprise. "
            "100+ backends: Slack/Telegram/Discord/Email/SMS и др. "
            "default-OFF до установки 'apprise>=1.9.0' в S3 cutover и staging-smoke."
        ),
    )

    # ─── K3 — Resilience & Scaling ─────────────────────────────────────────
    auto_scaler_process_level: bool = Field(
        default=False,
        title="Resilience: Granian dynamic workers (SIGUSR1 → fork)",
        description=(
            "K3 Wave 3. Owner: K3 Resilience. ETA: S2-W3. "
            "Активирует уровень 1 auto-scaler (process-level). "
            "default-OFF до проверки SIGUSR1 поведения на staging."
        ),
    )

    auto_scaler_task_level: bool = Field(
        default=False,
        title="Resilience: asyncio Bulkhead HighWatermark/LowWatermark",
        description=(
            "K3 Wave 3. Owner: K3 Resilience. ETA: S2-W3. "
            "Активирует уровень 2 auto-scaler (task-level). "
            "default-OFF до chaos-теста с back-pressure."
        ),
    )

    k8s_hpa_exporter: bool = Field(
        default=False,
        title="K2: Prometheus k8s HPA exporter (container-level auto-scaler)",
        description=(
            "K2 Wave 4. Owner: K2 Net&WAF. ETA: S3-W4. "
            "Активирует K8sHPAMetricsExporter — уровень 3 auto-scaler (R-V15-10). "
            "Экспортирует метрики в Prometheus-text формате через GET /metrics/hpa. "
            "default-OFF до интеграции с k8s HPA и staging-smoke."
        ),
    )

    otel_asyncpg: bool = Field(
        default=False,
        title="Resilience: OTel auto-instrumentation для asyncpg",
        description=(
            "K3 Wave 1. Owner: K3 Resilience. ETA: S2-W1. "
            "Активирует opentelemetry-instrumentation-asyncpg. "
            "default-OFF до перформанс-baseline diff <5%."
        ),
    )

    task_watchdog_deadline: bool = Field(
        default=False,
        title="Resilience: TaskWatchdog deadline-эскалация для asyncio-задач",
        description=(
            "K3 Wave 2. Owner: K3 Resilience. ETA: S2-W2. "
            "Активирует TaskWatchdog: регистрация задач с deadline_seconds + "
            "auto-cancel при превышении. default-OFF до chaos-теста с leak-detection."
        ),
    )

    pool_health_monitor: bool = Field(
        default=False,
        title="Storage: ConnectionPoolHealthMonitor (idle ping + reuse-on-demand)",
        description=(
            "K8 Wave 5. Owner: K8 Storage. ETA: S2-W5. "
            "Активирует фоновый health-monitor для DB/Redis/HTTP/ClickHouse pools. "
            "default-OFF до интеграции в 4 reference pools."
        ),
    )

    # ─── K7 — EventBus ─────────────────────────────────────────────────────
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

    # ─── Sprint 4 — Workflow DSL + Capability Gate + LLM activity ─────────
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

    # ─── K1 — Secrets & Vault ──────────────────────────────────────────────
    vault_rotation_enabled: bool = Field(
        default=False,
        title="Secrets: scheduled Vault secret rotation hook (без рестарта)",
        description=(
            "K1 Wave 1. Owner: K1 Auth/Secrets. ETA: S3-W1. "
            "Активирует VaultSecretRotator — фоновую задачу, периодически "
            "перечитывающую Vault paths и обновляющую in-memory cache. "
            "default-OFF до integration-test с реальным Vault в staging."
        ),
    )

    # ─── K1 — Tracing & Observability ─────────────────────────────────────
    tracing_baggage_strict: bool = Field(
        default=False,
        title="Tracing: strict-режим проверки OTel baggage (все 4 поля обязательны)",
        description=(
            "K1 Wave 2. Owner: K1 Auth/Tracing. ETA: S3-W2. "
            "При True вызов ensure_required_baggage() возбуждает MissingBaggageError, "
            "если хотя бы одно из 4 полей (route_name/tenant_id/business_op/correlation_id) "
            "отсутствует в OTel baggage context. "
            "default-OFF до покрытия всех entrypoints propagation middleware и staging-smoke."
        ),
    )

    # ─── Sprint 7 T5 — External feature-flag provider ─────────────────────
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

    # ─── K1 — Plugin semver ────────────────────────────────────────────────
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

    # ─── K1 — Auth ─────────────────────────────────────────────────────────
    auth_joserfc: bool = Field(
        default=False,
        title="Auth: joserfc вместо python-jose (deprecated)",
        description=(
            "K1 Wave 1. Owner: K1 Auth. ETA: S2-W1. "
            "Миграция с python-jose (deprecated) на joserfc. "
            "default-OFF до полной замены и unit-test coverage."
        ),
    )

    auth_mtls_client: bool = Field(
        default=False,
        title="Auth: mTLS HttpxClient в infrastructure/clients/",
        description=(
            "K1 Wave 3. Owner: K1 Auth. ETA: S2-W3. "
            "Перенос mTLS handshake из fixture в production HttpxClient. "
            "default-OFF до integration-test."
        ),
    )

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

    # ─── K8 — Audit & ClickHouse ───────────────────────────────────────────
    audit_clickhouse_enabled: bool = Field(
        default=False,
        title="Audit: ClickHouse audit_events trail",
        description=(
            "K8 Wave 4. Owner: K8 Audit. ETA: S2-W4. "
            "Активирует отправку audit-событий в ClickHouse (таблица audit_events). "
            "При False — ClickHouseAuditService пропускает emit/emit_batch без ошибок. "
            "default-OFF до запуска ClickHouse instance и smoke-теста в staging."
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
        title="K3 S5 W1: JqProcessor (pyjq query)",
        description=(
            "K3 Sprint 5 Wave 1. Owner: K3 DSL. ETA: S5-W1. "
            "Активирует JqProcessor для трансформации JSON через jq DSL."
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
        title="K3 S5 W3: LdapQueryProcessor (aioldap3 search)",
        description=(
            "K3 Sprint 5 Wave 3. Owner: K3 DSL. ETA: S5-W3. "
            "Активирует LdapQueryProcessor — async LDAP search через aioldap3."
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
            "windows-sidecar/app.py через services/rpa/com_sidecar_client.py. "
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


feature_flags = FeatureFlags()
