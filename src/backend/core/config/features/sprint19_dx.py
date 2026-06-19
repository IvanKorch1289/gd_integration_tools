"""Sprint 19 DSL+DX (T1.3.23 split) — first 12 of 23 fields.

Извлечено 12 flags (S38 P1.1 W1 T1.3.23, part 1 of 2):
- Sprint 19 K3 DSL/Workflow (3):
  - workflow_versioning_routes (Sprint 19 W1)
  - route_composition_include (Sprint 19 W2)
  - route_authz_requires_permission (Sprint 19 W3)
- Sprint 19 K4 AI/RAG (5):
  - rag_multipart_ingest (Sprint 19 W4)
  - reranking_pipeline_enabled (Sprint 19 W5)
  - banking_ai_processors_impl (Sprint 19 W8, S-L4-1 closure)
  - banking_ai_processors_enabled (Sprint 19 W8, S-L4-1 closure)
  - langmem_consolidation_impl (Sprint 19 W9, S-L4-3 closure)
- Sprint 19 K5 RPA/DX (4):
  - rpa_session_persistence (Sprint 19 W6, S-L5-2 closure)
  - vscode_extension_published (Sprint 19 W10)
  - lsp_server_strict (Sprint 19 W11)
  - testkit_public_api (Sprint 19 W14, S-L10-1)

Remaining 11 fields (Sprint 19 K1/K2/K3/K4/K5) stay в
``core.config.features.__init__.py`` до T1.3.24+ follow-up split.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprint19DXFlags(BaseSettings):
    """Sprint 19 first half: DSL routes + AI/RAG + LSP/IDE/DX.

    Per S38 T1.3.23, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprint19_dx import Sprint19DXFlags
        class FeatureFlags(..., Sprint19DXFlags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

    workflow_versioning_routes: bool = Field(
        default=True,
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
        default=True,
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
        default=True,
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
        default=True,
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
        default=True,
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
        default=True,
        title="K5 S19 W1: RPA browser session persistence via Redis (S-L5-2 closure)",
        description=(
            "K5 Sprint 19 Wave 1 (PLAN.md V22 §S19 W6, Func-rec #6, S-L5-2 closure). Owner: K5 RPA. "
            "При True BrowserCookieStore (S21 W7) интегрируется в BrowserLaunchProcessor "
            "с lazy-restore. Redis-backed session-store key = tenant_id:session_id с cookies/auth/local-storage. "
            "TTL configurable. RPA-route routes/banking_legacy_session_demo/ как reference. "
            "default-OFF до smoke-test session persistence after browser restart."
        ),
    )

    banking_ai_processors_enabled: bool = Field(
        default=True,
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

    banking_ai_processors_impl: bool = Field(
        default=True,
        title="K4 S19 W3: Banking AI processors - implementation layer (impl vs interface)",
        description=(
            "K4 Sprint 19 Wave 3 (S-L4-1 closure, sibling to banking_ai_processors_enabled). "
            "Owner: K4 AI. "
            "При True указывает, что implementation-слой (LLM calls, structured output, "
            "instructor/litellm binding) активирован, в отличие от interface-флага "
            "(banking_ai_processors_enabled) который контролирует registration в DSL. "
            "Используется для staged rollout: interface first (mock), then impl (real LLM). "
            "default-OFF до 100% integration tests на credit_check_demo route."
        ),
    )

    langmem_consolidation_impl: bool = Field(
        default=True,
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
        default=True,
        title="K5 S19 W2: VSCode extension .vsix published (ADR R1.14)",
        description=(
            "K5 Sprint 19 Wave 2 (PLAN.md V22 §S19 W10). Owner: K5 Frontend/DX. "
            "При True tools/vscode-extension/ содержит готовый .vsix: syntax highlighting + "
            "hover docs + 'Run step' CodeLens + LSP client. Private marketplace publish. "
            "default-OFF до VSCode team validation."
        ),
    )

    lsp_server_strict: bool = Field(
        default=True,
        title="K3 S19 W4: DSL LSP server YAML schema completion + diagnostics",
        description=(
            "K3 Sprint 19 Wave 4 (PLAN.md V22 §S19 W11). Owner: K3 DSL/LSP. "
            "При True tools/dsl_lsp/server.py расширяется: YAML schema completion + "
            "diagnostics через DSL Linter. Integration test pygls test-client. "
            "default-OFF до LSP smoke-test."
        ),
    )

    testkit_public_api: bool = Field(
        default=True,
        title="K5 S19 W3: src/testkit/ public API для extensions/plugin authors (S-L10-1)",
        description=(
            "K5 Sprint 19 Wave 3 (PLAN.md V22 §S19 W14, S-L10-1). Owner: K5 DX. "
            "При True src/testkit/ (NEW) предоставляет public API: RouteRunner, WorkflowRunner, "
            "MockCapabilityGateway, FakeWorkflowBackend, recorder/replay fixtures, "
            "assert_audit_event, assert_metric_recorded. Документация в docs/testkit/. "
            "default-OFF до testkit API review."
        ),
    )


__all__ = ("Sprint19DXFlags",)
