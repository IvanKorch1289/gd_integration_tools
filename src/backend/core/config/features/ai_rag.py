"""Sprint 11 — AI/RAG Completion + Sprint 12 — Workflow Enhancement feature-flags
(T1.3.18 split from core.config.features.__init__).

Извлечено 29 flags (S38 P1.1 W1 T1.3.18) из строк 798-1114
монолитного ``core.config.features.__init__.py``:

- Sprint 11 — AI/RAG Completion (11):
  - rag_pii_retrieval_mask (Sprint 11 K1 W1)
  - guardrails_per_tenant (Sprint 11 K1 W2)
  - distributed_rl_redis_cluster (Sprint 11 K2 W1)
  - multimodal_rag_full (Sprint 11 K4 W1/W2)
  - adaptive_rag_strategy (Sprint 11 K4 W3)
  - langgraph_checkpoint_ui (Sprint 11 K4 W4)
  - dspy_feedback_loop (Sprint 11 K4 W5)
  - ai_model_registry_ui (Sprint 11 K4 W6)
  - ai_route_optimization (Sprint 11 K4 W7)
  - embedding_ab_migration (Sprint 11 K4 W8)
  - embedding_v2_traffic (Sprint 11 K4 W8, int 0..100)
- Sprint 12 — Workflow Enhancement (18):
  - workflow_audit_extended (Sprint 12 K1 W1, default-ON)
  - workflow_mtls_enabled (Sprint 12 K1 W2)
  - workflow_sla_dashboard_enabled (Sprint 12 K2 W1, default-ON)
  - workflow_worker_autoscale_enabled (Sprint 12 K2 W2)
  - workflow_visual_diff_enabled (Sprint 12 K3 W1, default-ON)
  - workflow_cron_builder_enabled (Sprint 12 K3 W2, default-ON)
  - workflow_cost_estimation_enabled (Sprint 12 K3 W3, default-ON)
  - workflow_reactive_triggers_enabled (Sprint 12 K3 W4)
  - workflow_template_library_enabled (Sprint 12 K3 W5, default-ON)
  - workflow_template_semantic_search (Sprint 12 K3 W5)
  - workflow_saga_viewer_enabled (Sprint 12 K3 W6, default-ON)
  - workflow_cancel_dsl_enabled (Sprint 12 K3 W7, default-ON)
  - workflow_versioning_ui_enabled (Sprint 12 K3 W8, default-ON)
  - ai_workflow_examples_enabled (Sprint 12 K4 W1)
  - ai_workflow_cost_estimation_enabled (Sprint 12 K4 W2, default-ON)
  - workflow_template_streamlit_enabled (Sprint 12 K5 W1, default-ON)
  - hitl_history_enabled (Sprint 12 K5 W2, default-ON)
  - workflow_cron_dashboard_enabled (Sprint 12 K5 W3, default-ON)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIRAGFlags(BaseSettings):
    """Sprint 11 — AI/RAG Completion + Sprint 12 — Workflow Enhancement.

    Owner: K1 Security, K2 Resilience, K3 DSL/Workflow, K4 AI/Data,
    K5 Frontend+Ext.

    Per S38 T1.3.18, извлечено из monolithic ``core.config.features.FeatureFlags``
    (исходный range: строки 798-1114).

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.ai_rag import AIRAGFlags
        class FeatureFlags(..., AIRAGFlags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    # ─── Sprint 11 — AI/RAG Completion ────────────────────────────────────
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


__all__ = ("AIRAGFlags",)
