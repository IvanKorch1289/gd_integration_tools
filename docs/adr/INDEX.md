# Architecture Decision Records (ADR) — индекс

Всего ADR-файлов: **55**; уникальных слотов: **55**.

| № | Заголовок | Статус | Файл |
|---|-----------|--------|------|
| 0050 | ADR-0050 — WAF strict + Single Entry для исходящего HTTP | Accepted (Wave 1, S1+S2+S3, 2026-05-08) | [0050-net-waf-strict-single-entry.md](0050-net-waf-strict-single-entry.md) |
| 0051 | ADR-0051 — Cache-декораторы как фасад поверх CachingDecorator | Accepted (Wave [s1/k2-1-cache-decorator], 2026-05-12) | [0051-cache-decorators-facade.md](0051-cache-decorators-facade.md) |
| 0052 | ADR-0052 — Каноничный порядок композиции в `@policy` | Accepted (Wave [s1/k2-2-policy-decorator], 2026-05-12) | [0052-policy-decorator-order.md](0052-policy-decorator-order.md) |
| 0053 | ADR-0053 — WAF Phase-2: flip `outbound_via_facade=True` по умолчанию | Accepted (Wave [s1/k1-waf-phase2], 2026-05-12) | [0053-waf-phase2-migration.md](0053-waf-phase2-migration.md) |
| 0054 | ADR-0054 — SSO Federation (SAML 2.0 + per-tenant IdP) | Accepted (Sprint 3, К1 W3, 2026-05-13) | [0054-sso-federation.md](0054-sso-federation.md) |
| 0055 | ADR-0055 — Chaos Engineering + Performance Gate | Accepted (Sprint 3, К2 W3, 2026-05-13) | [0055-chaos-engineering.md](0055-chaos-engineering.md) |
| 0056 | ADR-0056 — Routes V11.1a (DSL-routes как лёгкие плагины) | Accepted (Sprint 3, К3 W3, 2026-05-13) | [0056-routes-v11.md](0056-routes-v11.md) |
| 0057 | ADR-0057 — Pure ASGI Middleware Chain | Accepted (Sprint 3, К5 W3, 2026-05-13) | [0057-asgi-pure-chain.md](0057-asgi-pure-chain.md) |
| 0058 | ADR-0058 — JSON-Schema Export для DSL Processors | Accepted (Sprint 3, К3 W3, 2026-05-13) | [0058-jsonschema-export.md](0058-jsonschema-export.md) |
| 0059 | ADR-0059 — Granian RSGI production tuning | Accepted (Sprint 6 K2, 2026-05-14) | [0059-granian-rsgi-production.md](0059-granian-rsgi-production.md) |
| 0060 | ADR-0060 — Blue/Green deployment topology | Accepted (Sprint 7 K2, 2026-05-14) | [0060-blue-green-deploy.md](0060-blue-green-deploy.md) |
| 0061 | ADR-0061 — WAF allowlist tightening для Sprint 9 | Accepted (Wave [s9/k1-w3-waf-allowlist-tightening], 2026-05- | [0061-waf-allowlist-tightening.md](0061-waf-allowlist-tightening.md) |
| 0062 | ADR-0062 — Distinction между ASGI и Action-dispatch middleware | Accepted (Wave [s9/k5-w7-execution-middleware-dedup], 2026-0 | [0062-middleware-layers-distinction.md](0062-middleware-layers-distinction.md) |
| 0063 | ADR-0063 — Presidio + ru NER как обязательный AI Safety layer (PII) | Accepted (2026-05-22, после S24 W1 closure — landed коммитам | [0063-presidio-ru-ner-pii.md](0063-presidio-ru-ner-pii.md) |
| 0064 | ADR-0064 — NeMo Guardrails + Llama Guard 3 defense-in-depth | Accepted (S29 T11, 2026-05-26 — GPU-check scaffolding + nemo | [0064-nemo-guardrails-llama-guard.md](0064-nemo-guardrails-llama-guard.md) |
| 0065 | ADR-0065 — LangGraph PostgresCheckpointer + Mem0 как единый long-term memory layer | Accepted (S29 T12, 2026-05-26 — durable flag + PostgresCheck | [0065-langgraph-checkpointer-mem0.md](0065-langgraph-checkpointer-mem0.md) |
| 0066 | ADR-0066 — AIGateway — единая точка входа в AI | Accepted (S29 T9, 2026-05-26 — ModelRouter LiteLLM fallback  | [0066-ai-gateway-facade.md](0066-ai-gateway-facade.md) |
| 0067 | ADR-0067 — AIPolicySpec — декларативная политика AI per-workflow | Draft (Sprint 25 candidate, [wave:s25/w2-policy-resolver]) | [0067-ai-policy-spec-dsl.md](0067-ai-policy-spec-dsl.md) |
| 0068 | ADR-0068 — PIITokenizer — reversible PII tokenization layer | Accepted (Sprint 25 W4, 2026-05-25) | [0068-pii-tokenizer-reversible.md](0068-pii-tokenizer-reversible.md) |
| 0069 | ADR-0069 — SkillRegistry V11.2 — TOML-манифест для AI-tools | Draft (Sprint 26 candidate, [wave:s26/w5-skill-registry]) | [0069-skill-registry-v11-2-toml.md](0069-skill-registry-v11-2-toml.md) |
| 0070 | ADR-0070 — MCP Gateway — domain namespaces + trusted external registry | Draft (Sprint 27 candidate, [wave:s27/w4-mcp-gateway]) | [0070-mcp-gateway-namespaces.md](0070-mcp-gateway-namespaces.md) |
| 0071 | ADR-0071 — AI Audit Unified Schema — `ai.invocation.*` события | Draft (Sprint 27 candidate, [wave:s27/w5-audit-unified]) | [0071-ai-audit-unified-schema.md](0071-ai-audit-unified-schema.md) |
| 0072 | ADR-0072 — PII production enforcement (Presidio + Langfuse + RAG ingest + MCP authz + Policy gate) | Accepted (2026-05-22, Phase A Block 1 closure). | [0072-pii-production-enforcement.md](0072-pii-production-enforcement.md) |
| 0073 | ADR-0073 — RAGAS evaluation gate | Accepted (S29 W3, 2026-05-26, gap-ai-6 closure). | [0073-ragas-evaluation-gate.md](0073-ragas-evaluation-gate.md) |
| 0074 | ADR-0074 — RAG hybrid retrieval, embedding provenance, source attribution & eval gate | Accepted (2026-05-25, Phase B Block 3 closure). | [0074-rag-hybrid-retrieval-and-eval-gate.md](0074-rag-hybrid-retrieval-and-eval-gate.md) |
| 0075 | ADR-0075 — UnifiedAgentMemoryGateway (Protocol + dispatch) | Accepted (2026-05-25, Phase B Block 4.1 closure). | [0075-unified-agent-memory-gateway.md](0075-unified-agent-memory-gateway.md) |
| 0076 | ADR-NEW-25: LangGraph Integration Decision | — | [0076-langgraph-integration-decision.md](0076-langgraph-integration-decision.md) |
| 0077 | ADR-0077: Sandbox Decision — E2B for Production, NoOp for Dev | — | [0077-sandbox-decision-e2b-vs-pyodide.md](0077-sandbox-decision-e2b-vs-pyodide.md) |
| 0078 | ADR-0078 — plugin.toml Capability Syntax: Array Format (`[[capabilities]]`) | — | [0078-plugin-toml-capability-syntax.md](0078-plugin-toml-capability-syntax.md) |
| 0079 | ADR-0079 — SLO Format: Inline `route.toml::slo` (not separate sloth YAML) | — | [0079-slo-format-route-toml-slo.md](0079-slo-format-route-toml-slo.md) |
| 0080 | ADR-0080 — Single Entry Policy Naming Convention | — | [0080-single-entry-policy-naming.md](0080-single-entry-policy-naming.md) |
| 0081 | ADR-0081 — Event Bus Production Backend: FastStream + Redis | — | [0081-eventbus-production-backend-faststream-redis.md](0081-eventbus-production-backend-faststream-redis.md) |
| 0082 | ADR-0082 — Network isolation для markitdown через monkey-patch urllib.request | Accepted (Sprint 57 W5, 2026-06-07) | [0082-markitdown-network-isolation.md](0082-markitdown-network-isolation.md) |
| 0083 | ADR-0083 — Row-Level Versioning: thin DSL wrapper над `sqlalchemy-continuum` | — | [0083-versioning-dsl-continuum-wrapper.md](0083-versioning-dsl-continuum-wrapper.md) |
| 0084 | ADR-0084 — Library Adoption Migration Plan (structlog, typer, rich, aiocache) | — | [0084-library-adoption-migration-plan.md](0084-library-adoption-migration-plan.md) |
| 0085 | ADR-0085 — User Auth: LDAP as Primary, Password Deprecated | — | [0085-user-auth-ldap-integration.md](0085-user-auth-ldap-integration.md) |
| 0086 | ADR-0086 — aiocache Migration Plan (S60+) | CLOSED — DEFERRED to per-feature ad-hoc (no global migration | [0086-aiocache-migration-plan.md](0086-aiocache-migration-plan.md) |
| 0087 | ADR-0087 — ClaimCheckProcessor Dedup (S63 W2.1) | — | [0087-claimcheck-dedup.md](0087-claimcheck-dedup.md) |
| 0088 | ADR-0088 — EIP 10/10 Coverage: TransactionalClient + ProcessManager (S63 W3.0) | — | [0088-eip-10of10-coverage.md](0088-eip-10of10-coverage.md) |
| 0089 | ADR-0089: Multi-agent supervisor — LangGraph-based architecture | — | [0089-multi-agent-supervisor-architecture.md](0089-multi-agent-supervisor-architecture.md) |
| 0090 | ADR-0090: aiocache hot-path strategy (audit + defer) | — | [0090-aiocache-hotpath-strategy.md](0090-aiocache-hotpath-strategy.md) |
| 0091 | ADR-0091: DLQ retention strategy (formalize existing unified implementation) | — | [0091-dlq-retention-strategy.md](0091-dlq-retention-strategy.md) |
| 0092 | ADR-0092: Vault zero-downtime rotation (formalize K1 S19 W1) | — | [0092-vault-zero-downtime-rotation.md](0092-vault-zero-downtime-rotation.md) |
| 0093 | ADR-0093: Global rate-limit (formalize existing production-ready implementation) | — | [0093-global-rate-limit.md](0093-global-rate-limit.md) |
| 0094 | ADR-0094: Global PII response middleware (formalize S18 W3 + S-L8-4) | — | [0094-global-pii-response-middleware.md](0094-global-pii-response-middleware.md) |
| 0096 | ADR-0096: Correlation→OTel trace_id binding (formalize S18 W7 + S-L7-2/6) | — | [0096-correlation-otel-traceid-binding.md](0096-correlation-otel-traceid-binding.md) |
| 0097 | ADR-0097: Fallback logging sink (formalize existing production-ready implementation) | — | [0097-fallback-logging-sink.md](0097-fallback-logging-sink.md) |
| 0098 | ADR-0098: Outbox per-transport stuck breakdown (defer implementation) | — | [0098-outbox-per-transport-stuck-breakdown.md](0098-outbox-per-transport-stuck-breakdown.md) |
| 0099 | ADR-0099: v28 ro-analysis reconciliation — fabricated claims + Sprint 0 closeout | — | [0099-v28-reconciliation-fabricated-claims.md](0099-v28-reconciliation-fabricated-claims.md) |
| 0100 | ADR-0100: Remove dead `dsl/builders/eip.py` (1354 LOC) — S60 W4 split superseded | — | [0100-remove-dead-eip-py.md](0100-remove-dead-eip-py.md) |
| 0101 | ADR-0101: Lazy-import pattern для streamlit-dependent helpers (testability boundary) | — | [0101-lazy-streamlit-import-pattern.md](0101-lazy-streamlit-import-pattern.md) |
| 0102 | ADR-0102: ai_processors.py god-object decomposition (1164 LOC → 6 modules) | design + plan, NOT impl (deferred to S81 W1). | [0102-ai-processors-decomposition.md](0102-ai-processors-decomposition.md) |
| 0103 | ADR-0103: Per-transport cardinality protection (ND-001 step 8) | — | [0103-per-transport-cardinality-protection.md](0103-per-transport-cardinality-protection.md) |
| 0105 | ADR-0105: lifecycle.py god-object decomposition (1142→5 files, ~200 LOC avg) | — | [0105-lifecycle-py-decomposition.md](0105-lifecycle-py-decomposition.md) |
| 0106 | ADR-0106: S27 closure — AIGateway enforce + WorkflowBuilder.invoke_agent() as Temporal activity | — | [0106-s27-closure.md](0106-s27-closure.md) |

_Сгенерировано `tools/build_adr_index.py`. Не редактировать вручную — запустите скрипт повторно._
