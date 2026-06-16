"""Sprint 18 + Sprint 21 feature-flags (T1.3.20 split from core.config.features.__init__).

Извлечено 18 flags (S38 P1.1 W1 T1.3.20):
- Sprint 18 — Operational + Security GAP Carryover (10):
  - waf_strict_zero_allowlist (Sprint 18 K1 W1)
  - failing_tests_quarantined_off (Sprint 18 K2 W2)
  - sandbox_amortised_final (Sprint 18 K1 W5, ADR-NEW-6 / B-4)
  - core_entities_legacy_off (Sprint 18 K3 W3)
  - eventbus_dsl_enabled (Sprint 18 K3 W4, V22 NEW)
  - langfuse_production_wired (Sprint 18 K4 W1)
  - opa_runtime_query_enabled (Sprint 18 K1 W3, S-L8-1/S-L8-2)
  - multi_tenant_rate_limit_enabled (Sprint 18 K5 W1, P0 Gateway-centralization)
  - pii_response_middleware_enabled (Sprint 18 K3 W1, S-L8-4)
  - per_route_timeout_enabled (Sprint 18 K3 W2, P0 Gateway-centralization gap)
- Sprint 21 — Resilience & Multi-tenancy (8):
  - rls_postgres_enforce (Sprint 21 K1 W1, B-03/G-08, ADR-NEW-12)
  - tenant_cache_prefix_enabled (Sprint 21 K1 W2, B-03 closure)
  - rpa_resilience_wrapper_enabled (Sprint 21 K2 W3, B-02 closure, ADR-NEW-13)
  - scheduler_dlq_enabled (Sprint 21 K2 W4, G-09 closure)
  - webhook_resilience_policy_enabled (Sprint 21 K2 W5, G-07 closure)
  - desktop_rpa_session_pool_enabled (Sprint 21 K3 W6, F-12/B-09 closure)
  - browser_cookies_redis_persist (Sprint 21 K3 W7, G-06 closure)
  - workflow_state_sqlite_persist (Sprint 21 K3 W8, B-05 closure, ADR-NEW-14)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprints1821Flags(BaseSettings):
    """Sprint 18 Operational+Security GAP Carryover + Sprint 21 Resilience & Multi-tenancy.

    Owner: K1 Security, K2 Resilience+Quality, K3 DSL/Routes/RPA/Workflow,
    K4 AI/Data, K5 Frontend/Ops.

    Per S38 T1.3.20, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprints_18_21 import Sprints1821Flags
        class FeatureFlags(..., Sprints1821Flags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    @staticmethod
    def _env_aware_default(env_var_name: str, prod_value: bool) -> bool:
        """S88 W1 (V2 P0 #5): env-aware default для security flags.

        Якщо env var не встановлена явно — повертає ``prod_value`` в production,
        ``not prod_value`` в development/staging. Дозволяє secure-by-default в prod
        без зламування dev/staging workflow.
        """
        import os

        from src.backend.core.config.base.app_base import AppBaseSettings

        # Read raw env var BEFORE pydantic-settings processing.
        explicit = os.environ.get(env_var_name)
        if explicit is not None:
            return explicit.lower() in ("1", "true", "yes", "on")

        # Try to read app environment from AppBaseSettings singleton.
        try:
            app_env = AppBaseSettings().environment  # type: ignore[attr-defined]
        except Exception:
            # AppBaseSettings not yet initialized (e.g. unit tests without env).
            # Default to NOT-prod для safety (rate limit OFF як default).
            return not prod_value
        return prod_value if app_env == "production" else not prod_value

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
        default_factory=lambda: Sprints1821Flags._env_aware_default(
            env_var_name="FEATURE_MULTI_TENANT_RATE_LIMIT_ENABLED", prod_value=True
        ),
        title="K5 S18 W1: global rate-limit middleware (fastapi-limiter + per-tenant)",
        description=(
            "K5 Sprint 18 Wave 1 (PLAN.md V22 §S18, P0 Gateway-centralization). "
            "Owner: K5 Frontend/Ops. При True entrypoints/middlewares/global_rate_limit.py "
            "RateLimitMiddleware активна: global default + per-route override + per-tenant "
            "namespace через Casbin/OPA. Базируется на fastapi-limiter (Redis backend). "
            "S88 W1 (V2 P0 #5 HIGH): env-aware default — production → True, "
            "development/staging → False. Override через "
            "FEATURE_MULTI_TENANT_RATE_LIMIT_ENABLED env var."
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


__all__ = ("Sprints1821Flags",)
