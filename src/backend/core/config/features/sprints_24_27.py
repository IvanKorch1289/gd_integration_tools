"""Sprints 24-27 AI Safety/Gateway/Prompts/Agent feature-flags (T1.3.21 split from core.config.features.__init__).

Извлечено 13 flags (S38 T1.3.21, K4 focus + K2/K3 cross-cutting):
- K4 — Sprint 24 AI Safety Hardening (3):
  - presidio_pii_enabled (S24 W1, ADR-NEW-16)
  - nemo_guardrails_enabled (S24 W2, ADR-NEW-17)
  - langgraph_checkpointer_enabled (S24 W3, ADR-NEW-18)
- K4 — Sprint 25 AI Gateway + Policy DSL (3):
  - ai_gateway_enforce (S25 W1, ADR-NEW-19)
  - ai_policy_enforce (S25 W2, ADR-NEW-20)
  - ai_pii_tokenizer_enabled (S25 W4, ADR-NEW-21)
- Sprint 26 — Prompts Pipeline + Skills Registry (3):
  - ai_prompt_sweep_strict (S26 W1)
  - ai_prompt_eval_blocking (S26 W4)
  - ai_skill_toml_enabled (S26 W5, ADR-NEW-22)
- Sprint 27 — Agent DSL + MCP Gateway + Audit Unified (4):
  - ai_agent_dsl_enabled (S27 W1)
  - mcp_gateway_namespaces_enabled (S27 W4, ADR-NEW-23)
  - ai_audit_unified_enabled (S27 W5, ADR-NEW-24)
  - workflow_invoke_agent_enabled (S27 W6, R-V15-9)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Sprints2427Flags(BaseSettings):
    """Sprint 24-27 AI Safety + Gateway + Prompts + Agent DSL flags.

    Per S38 T1.3.21, извлечено из monolithic ``core.config.features.FeatureFlags``.

    Re-export в ``__init__.py``:
        from src.backend.core.config.features.sprints_24_27 import Sprints2427Flags
        class FeatureFlags(..., Sprints2427Flags, ...):
            ...

    Env-var prefix: ``FEATURE_``.
    """

    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

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
        default=True,
        title="K4 S25 W1: AIGateway единая точка входа в AI (ADR-NEW-19)",
        description=(
            "K4 Sprint 25 Wave 1 (ADR-NEW-19, PLAN.md V22.4 §S25). Owner: K4 AI/Data + К1 Security. "
            "При True все LLM-вызовы проходят через AIGateway.invoke() pipeline "
            "(policy_resolve → sanitize → guards → render → invoke_llm → "
            "output_guards → output_sanitize → audit → cost). При False — "
            "legacy fallback для экстренных отключений. "
            "default-ON начиная с S27 closure: все callsites обёрнуты."
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


__all__ = ("Sprints2427Flags",)
