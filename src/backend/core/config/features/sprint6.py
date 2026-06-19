"""Sprint 6 security+resilience+DSL+AI+frontend feature-flags (T1.3.14 split from core.config.features.__init__).

Извлечено 21 flags (S38 P1.1 W1 T1.3.14):
- Sprint 6 K1 Security (6):
  - saml_ad_login_enabled (Sprint 6 K1 W1)
  - outbound_metering_strict (Sprint 6 K1 W2)
  - supply_chain_strict_mode (Sprint 6 K1 W3)
  - owasp_zap_gate_enabled (Sprint 6 K1 W4)
  - custom_code_audit_enabled (Sprint 6 K1 W5)
  - codeclone_fail_on_new (Sprint 6 K1 W6)
- Sprint 6 K2 Resilience+Perf (7):
  - perf_gate_strict (Sprint 6 K2 W1)
  - granian_rsgi_mode_enabled (Sprint 6 K2 W2)
  - structlog_batching_enabled (Sprint 6 K2 W4)
  - processor_health_checks_strict (Sprint 6 K2 W5)
  - backpressure_streaming_enabled (Sprint 6 K2 W6)
  - schemathesis_gate_enabled (Sprint 6 K2 W7)
  - service_doc_gate_enabled (Sprint 6 K2 W8)
- Sprint 6 K3 DSL+Workflow (2):
  - com_sidecar_enabled (Sprint 6 K3 W5)
  - dsl_linter_strict (Sprint 6 K3 W4)
- Sprint 6 K4 AI+Quality (3):
  - inspect_ai_eval_enabled (Sprint 6 K4 W1)
  - dspy_eval_pipeline_enabled (Sprint 6 K4 W2)
  - ai_cost_dashboard_strict (Sprint 6 K4 W3)
- Sprint 6 K5 Frontend+Chaos (3):
  - chaos_tests_blocking (Sprint 6 K5 W1)
  - resilience_dashboard_enabled (Sprint 6 K5 W3)
  - pool_monitor_enabled (Sprint 6 K5 W4)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprint6Flags(BaseSettings):
    """Sprint 6 K1 Security + K2 Resilience+Perf + K3 DSL+Workflow +
    K4 AI+Quality + K5 Frontend+Chaos. Owner: K1/K2/K3/K4/K5 teams.

    Per S38 T1.3.14, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprint6 import Sprint6Flags
        class FeatureFlags(..., Sprint6Flags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    # ─── Sprint 6 — К1 Security ───────────────────────────────────────────
    saml_ad_login_enabled: bool = Field(
        default=True,
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
        default=True,
        title="K1 S6: PerHostMeter strict mode + quota threshold + alerts",
        description=(
            "K1 Sprint 6 Wave 2. Owner: K1 Security. ETA: S6-W2. "
            "Переключает PerHostMeter (scaffold s3/k2-w1-per-host-metering) "
            "из warning-only в enforce mode — quota threshold + alerts на "
            "превышение per-host rate-limit. default-OFF до staging smoke."
        ),
    )

    supply_chain_strict_mode: bool = Field(
        default=True,
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
        default=True,
        title="K1 S6: OWASP ZAP baseline scan в CI",
        description=(
            "K1 Sprint 6 Wave 4. Owner: K1 Security. ETA: S6-W4. "
            "Активирует .github/workflows/security.yml OWASP ZAP baseline scan "
            "против main-endpoints (5-10 reference targets из tests/security/zap_targets.yml). "
            "Warn-only по решению пользователя — blocking откладывается до Sprint 9."
        ),
    )

    custom_code_audit_enabled: bool = Field(
        default=True,
        title="K1 S6: vulture min-confidence 80 + manual review wrapper",
        description=(
            "K1 Sprint 6 Wave 5. Owner: K1 Security. ETA: S6-W5. "
            "Активирует make custom-code-audit — tools/checks/check_custom_code.py "
            "запускает vulture --min-confidence 80 + сопоставляет с allowlist. "
            "default-OFF до калибровки allowlist (baseline FP ≤5)."
        ),
    )

    codeclone_fail_on_new: bool = Field(
        default=True,
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
        default=True,
        title="K2 S6: perf-gate strict (p95<200ms / RPS>1000 blocking)",
        description=(
            "K2 Sprint 6 Wave 1. Owner: K2 Perf. ETA: S6-W1. "
            "Переключает perf-gate в blocking режим: p95<200ms / RPS>1000 для "
            "reference endpoints через k6+locust в docker-compose.perf.yml. "
            "Warn-only по решению пользователя — blocking откладывается до Sprint 9."
        ),
    )

    structlog_batching_enabled: bool = Field(
        default=True,
        title="K2 S6: structlog batching wrapper (50-event / 100ms)",
        description=(
            "K2 Sprint 6 Wave 4. Owner: K2 Perf. ETA: S6-W4. "
            "Активирует BatchingStructlogProcessor — 50-event batch / 100ms timeout "
            "wrapper над structlog pipeline. Ожидаемое улучшение -1..3ms per log. "
            "default-OFF до benchmark подтверждения."
        ),
    )

    processor_health_checks_strict: bool = Field(
        default=True,
        title="K2 S6: /health/processors агрегированный матричный endpoint",
        description=(
            "K2 Sprint 6 Wave 5. Owner: K2 Ops. ETA: S6-W5. "
            "Активирует /health/processors endpoint — матрица health-checks "
            "(Kafka schema-registry, Temporal server, Vault sealed, ClickHouse, "
            "Redis cluster, NATS, Graylog). Каждый возвращает {ok, reason, latency_ms}."
        ),
    )

    backpressure_streaming_enabled: bool = Field(
        default=True,
        title="K2 S6: backpressure model для streaming consumers",
        description=(
            "K2 Sprint 6 Wave 6. Owner: K2 Perf. ETA: S6-W6. "
            "Активирует backpressure: FastStream Kafka consumer.pause/resume на HW, "
            "Redis Streams XREAD count adaptive, AdaptiveBulkhead в DSL-pipeline. "
            "Защита от OOM при 10× spike. default-OFF до chaos-теста."
        ),
    )

    granian_rsgi_mode_enabled: bool = Field(
        default=True,
        title="K2 S6: Granian RSGI production mode + uvloop tuning",
        description=(
            "K2 Sprint 6 Wave 2. Owner: K2 Perf. ETA: S6-W2. "
            "Активирует Granian RSGI как production HTTP server (вместо ASGI) "
            "с uvloop event-loop. ADR-0059. default-OFF до benchmark подтверждения "
            "-10..30% latency improvement."
        ),
    )

    schemathesis_gate_enabled: bool = Field(
        default=True,
        title="K2 S6: API fuzz через schemathesis + asyncapi-diff",
        description=(
            "K2 Sprint 6 Wave 7. Owner: K2 Quality. ETA: S6-W7. "
            "Активирует make api-fuzz — schemathesis run на OpenAPI spec + "
            "asyncapi-diff stage. Warn-only по решению пользователя."
        ),
    )

    service_doc_gate_enabled: bool = Field(
        default=True,
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
        default=True,
        title="K3 S6: Windows COM sidecar (pywin32 + comtypes + FastAPI)",
        description=(
            "K3 Sprint 6 Wave 5. Owner: K3 DSL. ETA: S6-W5. "
            "Активирует .call_com(worker, method, params) DSL-шаг → REST к "
            "windows_worker/main.py через services/rpa/com_sidecar_client.py. "
            "default-OFF на Linux (mock); ON на Windows-worker docker."
        ),
    )

    dsl_linter_strict: bool = Field(
        default=True,
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
        default=True,
        title="K4 S6: Inspect AI nightly eval framework",
        description=(
            "K4 Sprint 6 Wave 1. Owner: K4 AI. ETA: S6-W1. "
            "Активирует manage.py ai-eval nightly + 5-7 reference suites "
            "(knowledge_qa/instruction_following/hallucination/safety/context_recall). "
            ".github/workflows/ai-eval-nightly.yml cron-job."
        ),
    )

    dspy_eval_pipeline_enabled: bool = Field(
        default=True,
        title="K4 S6: DSPy optimizer для critical pipelines",
        description=(
            "K4 Sprint 6 Wave 2. Owner: K4 AI. ETA: S6-W2. "
            "Активирует DSPy optimization для credit.scoring / document.parser / "
            "rag.query_reranker. Bootstrap from few-shot + DSPyOptimizer.compile(). "
            "default-OFF до validation lift ≥10% на reference dataset."
        ),
    )

    ai_cost_dashboard_strict: bool = Field(
        default=True,
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
        default=True,
        title="K5 S6: 33 chaos-теста blocking в CI",
        description=(
            "K5 Sprint 6 Wave 1. Owner: K5 Chaos. ETA: S6-W1. "
            "Переключает 33 chaos-теста (testcontainers[toxiproxy], 11 chains × 3 сценария) "
            "в blocking режим. Warn-only по решению пользователя — blocking откладывается "
            "до Sprint 9 pre-prod gate."
        ),
    )

    resilience_dashboard_enabled: bool = Field(
        default=True,
        title="K5 S6: Streamlit Resilience Dashboard (CB+RL+Bulkhead+Degradation)",
        description=(
            "K5 Sprint 6 Wave 3. Owner: K5 Frontend. ETA: S6-W3. "
            "Активирует страницу 13_Resilience_Dashboard.py — матрица CB/RL/Bulkhead/"
            "Degradation статусов через ResilienceCoordinator.snapshot() API + "
            "live updates каждые 5 сек."
        ),
    )

    pool_monitor_enabled: bool = Field(
        default=True,
        title="K5 S6: Streamlit Pool Monitor (worker + connection pools)",
        description=(
            "K5 Sprint 6 Wave 4. Owner: K5 Frontend. ETA: S6-W4. "
            "Активирует страницу 15_Pool_Monitor.py — worker pool + connection pool "
            "monitor для PG/Redis/HTTP/Kafka через PoolHealthMonitor API + live metrics."
        ),
    )


__all__ = ("Sprint6Flags",)
