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

    # ─── K6 — AI ───────────────────────────────────────────────────────────
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


feature_flags = FeatureFlags()
