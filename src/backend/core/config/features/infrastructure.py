"""Mixed-domain feature-flags (T1.3.17 split from core.config.features.__init__).

Извлечено 26 flags (S38 P1.1 W1 T1.3.17):
- Sprint 5 K4 AI+RAG (9):
  - rag_cache_l3_retrieval_invalidation (Sprint 5 K4 W1)
  - multipart_rag_ingest (Sprint 5 K4 W1)
  - multimodal_rag_docling (Sprint 5 K4 W3)
  - langgraph_postgres_checkpoint (Sprint 5 K4 W2)
  - dsl_expose_mcp (Sprint 5 K4 W8)
  - rlm_hierarchical_memory (Sprint 5 K4 W4)
  - unmask_pii_enabled (Sprint 5 K4 W6)
  - mem0ai_enabled (Sprint 5 K4 W5)
  - langfuse_mcp_prompt (Sprint 5 K4 W8)
- Sprint 5 K5 Frontend (3):
  - frontend_workflow_logs_page (Sprint 5 K5 W1)
- Sprint 8 Rule Engine persistence (1):
  - rule_engine_hot_reload (Sprint 8 K3 Rule Engine finale)
- Sprint 8 HTTP/3 + WebTransport (1):
  - http3_enabled (Sprint 8 K3 HTTP/3 opt-in)
- Sprint 9 GAP closure (7):
  - route_loader_hot_reload (S9 K3 W1, GAP-DSL-1)
  - streamlit_page_renumber (S9 K5 W2, GAP-DSL-2)
  - hitl_panel_enabled (S9 K3, GAP-WF-4.5)
  - tenant_token_budget_enabled (S9 K4, GAP-3.2)
  - saml_sp_initiated_enabled (S9 K1, GAP-1.5)
  - lazy_processor_loading (S9 K3, GAP-PERF-6.3)
  - clickhouse_bulk_writer_enabled (S9 K2, GAP-INF-2.3)
- Sprint 10 DSL Blueprint + DX Wizards (5):
  - compression_brotli (S10 K2 W2)
  - dsl_complexity_check_blocking (S10 K3 W2)
  - mock_llm_enabled (S10 K4 W1)
  - dsl_jinja_macros (S10 K3 W7)
  - dsl_step_trace (S10 K3 W8)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InfrastructureFlags(BaseSettings):
    """Mixed-domain feature-flags: Sprint 5 K4 AI+RAG + K5 Frontend +
    Sprint 8 Rule Engine + HTTP/3 + Sprint 9 GAP closure +
    Sprint 10 DSL Blueprint + DX Wizards. Owner: K3 DSL/Workflow,
    K4 AI/RAG, K5 Frontend, K1 Security, K2 Infra.

    Per S38 T1.3.17, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.infrastructure import InfrastructureFlags
        class FeatureFlags(..., InfrastructureFlags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

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


__all__ = ("InfrastructureFlags",)
