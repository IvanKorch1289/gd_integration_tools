# Architecture Decision Records (ADR) — индекс

Всего ADR-файлов: **147**; уникальных слотов: **146**.

⚠️ Collision-слоты (1): ADR-0109. Каждая пара — два ADR на один номер; ренейм отложен из-за внешних ссылок (см. R3.0).

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
| 0107 | ADR-0107: transport.py god-object decomposition (990 LOC → 6 modules) | — | [0107-transport-py-decomposition.md](0107-transport-py-decomposition.md) |
| 0108 | ADR-0108 — DI DSL для RouteBuilder / call_function / process_fn | Accepted (Sprint 40 W1–W5, 2026-06-09) | [0108-di-dsl-for-routes.md](0108-di-dsl-for-routes.md) |
| 0109 *(collision)* | ADR-0109 — Feature Flag Dependency Check: package-aware + Sprint 41 audit | Accepted (Sprint 41 W2, 2026-06-09) | [0109-feature-flag-dependency-check-fix.md](0109-feature-flag-dependency-check-fix.md) |
| 0109 *(collision)* | ADR-0109: Script Runner DSL для inline Python/Node/Ruby/Shell | — | [0109-script-runner-dsl.md](0109-script-runner-dsl.md) |
| 0110 | ADR-0110 — WAF Coverage 100% (formalize Sprint 41 #4 met) | Accepted (Sprint 41 W4, 2026-06-09) | [0110-waf-coverage-100pct-formalize.md](0110-waf-coverage-100pct-formalize.md) |
| 0111 | ADR-0111 — Chaos Tests + Multi-Tenant Isolation status (Sprint 41 #1, #6) | Accepted (Sprint 41 W6, 2026-06-09) | [0111-chaos-multitenant-formalize.md](0111-chaos-multitenant-formalize.md) |
| 0112 | ADR-0112 — Security Audit status (Sprint 41 #3) | Accepted (Sprint 41 W7, 2026-06-09) | [0112-security-audit-status.md](0112-security-audit-status.md) |
| 0113 | ADR-0113 — Perf + Blue/Green + Disaster Recovery status (S41 #2, #7, #10) | Accepted (Sprint 41 W8, 2026-06-09) | [0113-perf-bg-dr-formalize.md](0113-perf-bg-dr-formalize.md) |
| 0114 | ADR-0114 — DSL LSP server status + Makefile integration (Sprint 42 #1) | Accepted (Sprint 42 W1, 2026-06-09) | [0114-dsl-lsp-server-formalize.md](0114-dsl-lsp-server-formalize.md) |
| 0115 | ADR-0115 — Sprint 42 closure: Developer Experience Polish (5/5 DoD) | Accepted (Sprint 42 W5, 2026-06-09) | [0115-sprint-42-dx-closure.md](0115-sprint-42-dx-closure.md) |
| 0116 | ADR-0116 — Sprint 43 closure: Streamlit Filters + Vite Cleanup (2/5 DoD) | Accepted (Sprint 43 W5, 2026-06-09) | [0116-sprint-43-closure.md](0116-sprint-43-closure.md) |
| 0117 | ADR-0117 — Sprint 44 closure: Backend Wiring + Admin Build Fix (4/5 DoD) | Accepted (Sprint 44 W5, 2026-06-09) | [0117-sprint-44-closure.md](0117-sprint-44-closure.md) |
| 0118 | ADR-0118 — Sprint 45 closure: TD-006 + TD-018 + filter migration + docstrings (5/5 DoD) | Accepted (Sprint 45 W5, 2026-06-09) | [0118-sprint-45-closure.md](0118-sprint-45-closure.md) |
| 0119 | ADR-0119 — Sprint 46 closure: TraceStorage abstraction + docstring tool + toxiproxy runbook (5/5 DoD) | Accepted (Sprint 46 W5, 2026-06-09) | [0119-sprint-46-closure.md](0119-sprint-46-closure.md) |
| 0120 | ADR-0120 — Sprint 47 closure: ExecutionTracer storage wiring (1/5 substantive) | Accepted (Sprint 47 W5, 2026-06-09) | [0120-sprint-47-closure.md](0120-sprint-47-closure.md) |
| 0121 | ADR-0121 — Sprint 48 partial closure: TD-015 ruff F401 + mypy clean + stub regen verified | Accepted (Sprint 48 W2, 2026-06-10) | [0121-sprint-48-partial-closure.md](0121-sprint-48-partial-closure.md) |
| 0122 | ADR-0122 — Sprint 48 closure: audit + re-scope + 5/5 waves (W1-W4 substantive, W5 closure) | Accepted (Sprint 48 W5, 2026-06-10) | [0122-sprint-48-closure.md](0122-sprint-48-closure.md) |
| 0123 | ADR-0123 — Sprint 49 closure: TD-009 + actions.py decomp + trunk hygiene (4 commits, 5/5 substantive) | Accepted (Sprint 49 W5, 2026-06-10) | [0123-sprint-49-closure.md](0123-sprint-49-closure.md) |
| 0124 | ADR-0124 — Sprint 50 closure: TD backlog + transport.py B3-B5 + ai_banking/rpa god-file decomp (5 commits, 5/5 substantive) | Accepted (Sprint 50 W5, 2026-06-10) | [0124-sprint-50-closure.md](0124-sprint-50-closure.md) |
| 0125 | ADR-0125 — Sprint 51 closure: ai_rpa.py (2-wave) + agent_dsl.py + TD-003 (5 working + 1 fixup commits, 5/5 substantive) | Accepted (Sprint 51 W5, 2026-06-10) | [0125-sprint-51-closure.md](0125-sprint-51-closure.md) |
| 0126 | ADR-0126 — Sprint 52 closure: ai_rpa.py W3 + validator.py + loader_v11.py god-file decomp + TD-010 closure (5+1 commits, 5/5 substantive) | Accepted (Sprint 52 W5, 2026-06-10) | [0126-sprint-52-closure.md](0126-sprint-52-closure.md) |
| 0127 | ADR-0127 — Sprint 53 closure: format_convert + streaming + setup god-file decomp + TD-002 closure (5 commits, 5/5 substantive) | Accepted (Sprint 53 W5, 2026-06-10) | [0127-sprint-53-closure.md](0127-sprint-53-closure.md) |
| 0128 | ADR-0128 — Sprint 54 closure: 4 god-file decomps (mcp_server, ai_agent, invoker, capability_gate) (4+1 commits, 5/5 substantive) | Accepted (Sprint 54 W5, 2026-06-10) | [0128-sprint-54-closure.md](0128-sprint-54-closure.md) |
| 0129 | ADR-0129 — Sprint 55 closure: 4 god-file decomp (cert_store, control_flow, pg_runner_internals, data_quality) (4+1 commits, 5/5 substantive) | Accepted (Sprint 55 W5, 2026-06-10) | [0129-sprint-55-closure.md](0129-sprint-55-closure.md) |
| 0130 | ADR-0130 — Sprint 56 closure: 4 god-file decomp (spec, gateway_pipeline_mixin, s3_pool, admin_workflows) (5+1 commits, 5/5 substantive) | Accepted (Sprint 56 W5, 2026-06-10) | [0130-sprint-56-closure.md](0130-sprint-56-closure.md) |
| 0131 | ADR-0131 — Sprint 57 closure: 4 god-file decomp (base RouteBuilder, sources_mixin, collection EIP, sink_publish) (4+1 commits, 5/5 substantive) | Accepted (Sprint 57 W5, 2026-06-10) | [0131-sprint-57-closure.md](0131-sprint-57-closure.md) |
| 0132 | ADR-0132 — Sprint 58 closure: 4 god-file decomp (crud, saga_lra_processor, format_converters, workflow_builder) (4+1 commits, 5/5 substantive) | Accepted (Sprint 58 W5, 2026-06-10) | [0132-sprint-58-closure.md](0132-sprint-58-closure.md) |
| 0133 | ADR-0133 — Sprint 59 closure: 4 god-file decomp (banking_processors, lifecycle [sibling W82], redis, 31_DSL_Visual_Editor) (3+1 commits, 5/5 substantive) | Accepted (Sprint 59 W5, 2026-06-10) | [0133-sprint-59-closure.md](0133-sprint-59-closure.md) |
| 0134 | ADR-0134 — Sprint 60 closure: 4 god-file decomp (jupyter, cdc, setup_infra, authorization_gateway) (4+1 commits, 5/5 substantive) | Accepted (Sprint 60 W5, 2026-06-10) | [0134-sprint-60-closure.md](0134-sprint-60-closure.md) |
| 0135 | ADR-0135 — Sprint 61 closure: 4 god-file decomp (base_service, enrichment, executor, http) (4+1 commits, 5/5 substantive) | Accepted (Sprint 61 W5, 2026-06-10) | [0135-sprint-61-closure.md](0135-sprint-61-closure.md) |
| 0136 | ADR-0136 — Sprint 62 closure: 4 god-file decomp (admin_plugins, vocabulary, integration_core, yaml_loader) (4+1 commits, 5/5 substantive) | Accepted (Sprint 62 W5, 2026-06-10) | [0136-sprint-62-closure.md](0136-sprint-62-closure.md) |
| 0137 | ADR-0137 — Sprint 63 closure: 4 god-file decomp (loading, routing, marshal, external_database) (4+1 commits, 5/5 substantive) | Accepted (Sprint 63 W5, 2026-06-10) | [0137-sprint-63-closure.md](0137-sprint-63-closure.md) |
| 0138 | ADR-0138 — Sprint 64 closure: 4 god-file decomp (graphql, repositories, database, rag_service) (4+1 commits, 5/5 substantive) | Accepted (Sprint 64 W5, 2026-06-10) | [0138-sprint-64-closure.md](0138-sprint-64-closure.md) |
| 0139 | ADR-0139 — Sprint 65 closure: 4 god-file decomp (components, rpa_operations, grpc_server, idp_pipeline) + 2 W3 sibling WIP fixups (4+1+2 commits, 7/7 substantive) | Accepted (Sprint 65 W5, 2026-06-10) | [0139-sprint-65-closure.md](0139-sprint-65-closure.md) |
| 0140 | ADR-0140 — Sprint 66 closure: 3 god-file decomp (event_store, setup, lifecycle) + 1 sibling WIP fixup (4+1 commits, 5/5 substantive) | Accepted (Sprint 66 W5, 2026-06-10) | [0140-sprint-66-closure.md](0140-sprint-66-closure.md) |
| 0141 | ADR-0141 — Sprint 67 closure: 4 god-file decomp (backpressure, ai_enforcer, semantic_cache, ad_directory_client) (4+1 commits, 5/5 substantive) | Accepted (Sprint 67 W5, 2026-06-10) | [0141-sprint-67-closure.md](0141-sprint-67-closure.md) |
| 0142 | ADR-0142 — Sprint 68 closure: 4 god-file decomp (macros, clickhouse_audit, invoker, ai_providers) (4+1 commits, 5/5 substantive) | Accepted (Sprint 68 W5, 2026-06-10) | [0142-sprint-68-closure.md](0142-sprint-68-closure.md) |
| 0143 | ADR-0143 — Sprint 83 W3: Vault DSL wrapper + PIL leak fix | Accepted (Sprint 83 W3, 2026-08-31) | [0143-sprint-83-w3-closure.md](0143-sprint-83-w3-closure.md) |
| 0144 | ADR-0144 — Multi-instance safety: outbox claim_pending + scheduler leader election + RedisDedupeStore (4 commits, 3/5 substantive) | Accepted (Autonomous work cycle, 2026-06-12) | [0144-multi-instance-safety.md](0144-multi-instance-safety.md) |
| 0145 | ADR-0145 — Sprint 65 closure: P0 cleanup (lazy imports, dead enforcement, dsl/workflows LAYERS) (3 commits, 3/3 substantive) | Accepted (Autonomous work cycle S65, 2026-06-12) | [0145-sprint-65-p0-cleanup-closure.md](0145-sprint-65-p0-cleanup-closure.md) |
| 0146 | ADR-0146 — Sprint 66 closure: fact-checked quick wins (4 commits, 4/4 substantive) | Accepted (Autonomous work cycle S66, 2026-06-12) | [0146-sprint-66-quick-wins-closure.md](0146-sprint-66-quick-wins-closure.md) |
| 0147 | ADR-0147 — Sprint 67 closure: torch CVE, namespace markers, JWT consolidation, pre-existing fix (4 commits, 4/4 substantive) | Accepted (Autonomous work cycle S67, 2026-06-12) | [0147-sprint-67-torch-namespace-jwt-fix-closure.md](0147-sprint-67-torch-namespace-jwt-fix-closure.md) |
| 0148 | ADR-0148 — Sprint 68 closure: 3 parallel teams (swarm), 4 violations closed, 2 ADR docs (3 commits, 3/3 substantive) | Accepted (Autonomous work cycle S68, 2026-06-12) | [0148-sprint-68-swarm-closure.md](0148-sprint-68-swarm-closure.md) |
| 0149 | ADR-0149 — TD-S65-W2 audit: 34 core→other violations classified + 1 sample refactor (RetryPolicy) | Accepted (Autonomous work cycle S68 W2, 2026-06-12) | [0149-core-violations-audit.md](0149-core-violations-audit.md) |
| 0150 | ADR-0150 — TD-S65-W4 audit: 124 dsl/workflows violations classified + 1 sample refactor (audit JSON codec) | Accepted (Autonomous work cycle S68 W3, 2026-06-12) | [0150-dsl-violations-audit.md](0150-dsl-violations-audit.md) |
| 0151 | ADR-0151 — Sprint 69 closure: 2nd SWARM (3 teams) — 1 violation closed + 2 style cleanups (3 commits, 3/3 substantive, scope discipline) | Accepted (Autonomous work cycle S69, 2026-06-12) | [0151-sprint-69-swarm-2nd-closure.md](0151-sprint-69-swarm-2nd-closure.md) |
| 0152 | ADR-0152 — Sprint 70 closure: 3rd SWARM (3 teams) — 3 style cleanups (3 commits, 3/3 substantive, 2/3 subagent clean) | Accepted (Autonomous work cycle S70, 2026-06-12) | [0152-sprint-70-swarm-3rd-closure.md](0152-sprint-70-swarm-3rd-closure.md) |
| 0153 | ADR-0153 — Sprint 71 closure: 4 pre-existing import bugs + 3 file+dir merges + 2 P1 multi-instance safety fixes (4 commits, 7+3 NEW tests) | Accepted (Autonomous work cycle S71, 2026-06-12) | [0153-sprint-71-pre-existing-bugs-and-multi-instance-safety-closure.md](0153-sprint-71-pre-existing-bugs-and-multi-instance-safety-closure.md) |
| 0154 | ADR-0154 — Sprint 72 closure: TD-S64-W1 per-row outbox claim (3 files, 5+1 NEW tests, per-row lease + sweeper) | Accepted (Autonomous work cycle S72, 2026-06-12) | [0154-sprint-72-outbox-per-row-claim-closure.md](0154-sprint-72-outbox-per-row-claim-closure.md) |
| 0155 | ADR-0155 — Sprint 73 closure: P0-A batch fix (106 files, 136 except-A-B fixes, 2 NEW regression tests, pre-push CI gate) (5 commits) | Accepted (Autonomous work cycle S73, 2026-06-12) | [0155-sprint-73-p0-a-except-bug-batch-fix-closure.md](0155-sprint-73-p0-a-except-bug-batch-fix-closure.md) |
| 0156 | ADR-0156 — Sprint 74 closure: Jupiter Hub + Notebook Execution ecosystem (Papermill + Factory + WebSocket heartbeat, 13 NEW tests) (5 commits) | Accepted (Autonomous work cycle S74, 2026-06-12) | [0156-sprint-74-jupyter-execution-ecosystem-closure.md](0156-sprint-74-jupyter-execution-ecosystem-closure.md) |
| 0157 | ADR-0157 — Sprint 75 closure: направление #1 final closure (e2b ExecutionBackend + KernelSpecDiscovery, 15 NEW tests) (5 commits) | Accepted (Autonomous work cycle S75, 2026-06-12) | [0157-sprint-75-jupyter-execution-final-closure.md](0157-sprint-75-jupyter-execution-final-closure.md) |
| 0158 | ADR-0158 — Sprint 76 closure: P0-B tools whitelist в AIPolicySpec (ToolsSpec + enforcement + 21 NEW tests) (5 commits) | Accepted (Autonomous work cycle S76, 2026-06-12) | [0158-sprint-76-tools-whitelist-closure.md](0158-sprint-76-tools-whitelist-closure.md) |
| 0159 | ADR-0159 — Sprint 77 closure: P0-C AI Policy Spec DSL (hot-reload + JSON-Schema + specificity, 20 NEW tests) (5 commits) | Accepted (Autonomous work cycle S77, 2026-06-12) | [0159-sprint-77-ai-policy-dsl-closure.md](0159-sprint-77-ai-policy-dsl-closure.md) |
| 0160 | ADR-0160 — Sprint 78 closure: P0-D CORS/XSRF в Streamlit (config security + nginx + validator + 17 NEW tests) (5 commits) | Accepted (Autonomous work cycle S78, 2026-06-12) | [0160-sprint-78-streamlit-cors-xsrf-closure.md](0160-sprint-78-streamlit-cors-xsrf-closure.md) |
| 0161 | ADR-0161 — Sprint 79 closure: CapabilityGate ↔ AIPolicySpec.tools two-layer integration (FINAL_REPORT_V2 направление #4 closure, 16 NEW tests) (6 commits) | Accepted (Autonomous work cycle S79, 2026-06-12) | [0161-sprint-79-capability-gate-tools-integration-closure.md](0161-sprint-79-capability-gate-tools-integration-closure.md) |
| 0162 | ADR-0162 — Sprint 80 closure: P1 #6 LiteLLM Gateway pool registration (PoolHealthMonitor integration, 8 NEW tests) (6 commits) | Accepted (Autonomous work cycle S80, 2026-06-12) | [0162-sprint-80-litellm-pool-registration-closure.md](0162-sprint-80-litellm-pool-registration-closure.md) |
| 0163 | ADR-0163 — Sprint 81 closure: P1 #8 CircuitBreakerMiddleware restoration (per-route state, sliding window, 13 NEW tests) (4 commits) | Accepted (Autonomous work cycle S81, 2026-06-12) | [0163-sprint-81-circuit-breaker-middleware-closure.md](0163-sprint-81-circuit-breaker-middleware-closure.md) |
| 0164 | ADR-0164: Sprint 82 — Documentation Cookbooks Closure | Accepted | [0164-sprint-82-cookbooks-closure.md](0164-sprint-82-cookbooks-closure.md) |
| 0165 | ADR-0165: Sprint 83 — DetachedInstanceError Closure (V2 P0 N1) | Accepted | [0165-sprint-83-detached-instance-error-closure.md](0165-sprint-83-detached-instance-error-closure.md) |
| 0166 | ADR-0166: Sprint 84 — logging.factory Layer Violations Closure (V2 P0 #3) | Accepted | [0166-sprint-84-logging-facade-closure.md](0166-sprint-84-logging-facade-closure.md) |
| 0167 | ADR-0167: Sprint 85 — AIGateway Pass-Through Closure (V2 P0 #1) | Accepted | [0167-sprint-85-ai-gateway-enforcement-closure.md](0167-sprint-85-ai-gateway-enforcement-closure.md) |
| 0168 | ADR-0168: Sprint 86 — Temporal Sandbox Closure + Defense-in-Depth (V2 P0 #2) | Accepted | [0168-sprint-86-temporal-sandbox-closure.md](0168-sprint-86-temporal-sandbox-closure.md) |
| 0169 | ADR-0169: Sprint 87 — V2 P0 Re-Verification (Fact-Check, NO Code Changes) | Accepted (investigation-only) | [0169-sprint-87-v2-p0-reverification.md](0169-sprint-87-v2-p0-reverification.md) |
| 0170 | ADR-0170: Sprint 88 — V2 P0 #5 + #6 Closure (HIGH severity) | Accepted | [0170-sprint-88-rate-limit-and-tenant-isolation.md](0170-sprint-88-rate-limit-and-tenant-isolation.md) |
| 0171 | ADR-0171: Sprint 89 — V2 P0 #6 Pilot Migration (Order → TenantMixin) | Accepted | [0171-sprint-89-order-tenant-mixin-pilot.md](0171-sprint-89-order-tenant-mixin-pilot.md) |
| 0172 | ADR-0172: Sprint 90 — Pool Registration Completion (V3 #5) | — | [0172-sprint-90-pool-registration-completion.md](0172-sprint-90-pool-registration-completion.md) |
| 0173 | ADR-0173: Sprint 91 — V2 P0 #6 continue (User) + V2 P0 #7 fix (processors) | — | [0173-sprint-91-v2-p0-6-continue-and-v2-p0-7-fix.md](0173-sprint-91-v2-p0-6-continue-and-v2-p0-7-fix.md) |
| 0174 | ADR-0174: Sprint 92 — V2 P0 #6 continue (File + OrderKind) | — | [0174-sprint-92-v2-p0-6-file-orderkind.md](0174-sprint-92-v2-p0-6-file-orderkind.md) |
| 0175 | ADR-0175: Sprint 93 Wave 1 — Cleanup + Critical Fixes | — | [0175-sprint-93-w1-cleanup-and-critical-fixes.md](0175-sprint-93-w1-cleanup-and-critical-fixes.md) |
| 0176 | ADR-0176: Sprint 93 Wave 2 — Frontend PATH + Docstring Ratchet + Resilience Fact-Check | — | [0176-sprint-93-w2-frontend-and-resilience-factcheck.md](0176-sprint-93-w2-frontend-and-resilience-factcheck.md) |
| 0177 | ADR-0177: S93 closure — auth, CDC, logging, DSL | — | [0177-sprint-93-w5-closure-auth-cdc-logging-dsl.md](0177-sprint-93-w5-closure-auth-cdc-logging-dsl.md) |
| 0178 | ADR-0178: S94 closure — stdlib logging codemod + docstring ratchet + DSL SSE | — | [0178-sprint-94-w5-closure-logging-ratchet-sse.md](0178-sprint-94-w5-closure-logging-ratchet-sse.md) |
| 0179 | ADR-0179: S95 closure — DSL CRUD + docstring ratchet + stdlib audit + AuthGateway | — | [0179-sprint-95-w5-closure-dsl-crud-ratchet-authgateway.md](0179-sprint-95-w5-closure-dsl-crud-ratchet-authgateway.md) |
| 0180 | ADR-0180: S96 Closure | — | [0180-sprint-96-closure.md](0180-sprint-96-closure.md) |
| 0181 | ADR-0181: S97 Closure | — | [0181-sprint-97-closure.md](0181-sprint-97-closure.md) |
| 0182 | ADR-0182: S98 Closure | — | [0182-sprint-98-closure.md](0182-sprint-98-closure.md) |
| 0183 | ADR-0183: S99 Closure — Final Score 9.0/10 | — | [0183-sprint-99-closure.md](0183-sprint-99-closure.md) |
| 0184 | ADR-0184: S100 Closure — TODO backlog = 0 | — | [0184-sprint-100-closure.md](0184-sprint-100-closure.md) |
| 0185 | 0185-sprint-101-deep-research-followup | — | [0185-sprint-101-deep-research-followup.md](0185-sprint-101-deep-research-followup.md) |
| 0186 | 0186-sprint-102-backlog-closure | — | [0186-sprint-102-backlog-closure.md](0186-sprint-102-backlog-closure.md) |
| 0187 | 0187-sprint-103-cross-cutting | — | [0187-sprint-103-cross-cutting.md](0187-sprint-103-cross-cutting.md) |
| 0188 | ADR-0188: D5 model move plan (analysis-only, multi-sprint execution) | — | [0188-d5-models-move-plan.md](0188-d5-models-move-plan.md) |
| 0189 | ADR-0189: Sprint 104 closure — DSN tests + RPA DSL + Rate limit + MSSQL/MySQL/DB2 | — | [0189-sprint-104-closure.md](0189-sprint-104-closure.md) |
| 0190 | ADR-0190: Sprint 105 Closure | — | [0190-sprint-105-closure.md](0190-sprint-105-closure.md) |
| 0191 | ADR-0191: Sprint 106 Closure — D5 split-brain B1+B2+B3 complete | — | [0191-sprint-106-closure.md](0191-sprint-106-closure.md) |
| 0192 | ADR-0192: Sprint 106 Sprint B closure — sub_workflow + ai_tool_dispatch + from_nats/from_mongo + test baseline | — | [0192-sprint-106-sprint-b-closure.md](0192-sprint-106-sprint-b-closure.md) |
| 0193 | ADR-0193: Sprint 107 closure — TD-residual cleanup + real LLM-wiring + real runtime for nats/mongo | — | [0193-sprint-107-closure.md](0193-sprint-107-closure.md) |
| 0194 | ADR-0194: Sprint 108 closure — Dependabot security audit + TD-008 verify + TD-004 AI migration + AI tool registry e2e tests | — | [0194-sprint-108-closure.md](0194-sprint-108-closure.md) |
| 0195 | ADR-0195: Sprint 109 closure — TD-004 audit migration wave 2 (4 domains) | — | [0195-sprint-109-closure.md](0195-sprint-109-closure.md) |
| 0196 | ADR-0196: Sprint 110 closure — Layer policy enforcement + linter tooling hardening | — | [0196-sprint-110-closure.md](0196-sprint-110-closure.md) |
| 0197 | ADR-0197: Sprint 111 closure — DSL Completion + DX (TD-017 / TD-004 / TD-012 closure + lifespan.py god-file decomposition) | — | [0197-sprint-111-closure.md](0197-sprint-111-closure.md) |

_Сгенерировано `tools/build_adr_index.py`. Не редактировать вручную — запустите скрипт повторно._
