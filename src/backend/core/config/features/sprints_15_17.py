"""Sprint 15 DX Tooling + Innovation + Sprint 17 GAP P0 Closure feature-flags
(T1.3.19 split from core.config.features.__init__).

Извлечено 17 flags (S38 P1.1 W1 T1.3.19):
- Sprint 15 — DX Tooling + Innovation (5):
  - sandbox_amortised_psutil (Sprint 15 K1 W2, F-2 closure)
  - arch_map_llm_search_enabled (Sprint 15 K4 W18, page 83)
  - ai_pr_review_enabled (Sprint 15 K4 W16)
  - dsl_visual_editor_drag_drop (Sprint 15 K3 W10, page 31)
  - changelog_autogen_enabled (Sprint 15 K5 W15, make release-notes)
- Sprint 17 — GAP P0 Closure + Centralization Hardening (12):
  - config_validator_enabled (Sprint 17 K1 W4, D14)
  - metrics_registry_strict (Sprint 17 K2 W1+W2, D11)
  - task_registry_strict (Sprint 17 K2 W3, D13a)
  - apscheduler_metrics (Sprint 17 K2 W4, D13b)
  - authz_gateway_enabled (Sprint 17 K1 W2, ADR-NEW-1+ADR-NEW-4, K-ARCH-1+K-ARCH-2)
  - audit_correlation_required (Sprint 17 K3 W3, D12)
  - tenant_feature_flag_ui (Sprint 17 K5 W1, D9)
  - resilience_coordinator_enabled (Sprint 17 K2 W5)
  - routes_capability_gate_strict (Sprint 17 K3 W0, K-ARCH-3)
  - routes_tenant_aware_strict (Sprint 17 K3 W0, K-ARCH-4)
  - call_function_whitelist_strict (Sprint 17 K1 W3, K-ARCH-5)
  - saga_state_persistence_enabled (Sprint 17 K3 W4, K-OPS-1)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprints1517Flags(BaseSettings):
    """Sprint 15 DX Tooling + Innovation + Sprint 17 GAP P0 Closure +
    Centralization Hardening. Owner: K1/K2/K3/K4/K5 teams.

    Per S38 T1.3.19, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprints_15_17 import Sprints1517Flags
        class FeatureFlags(..., Sprints1517Flags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

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


__all__ = ("Sprints1517Flags",)
