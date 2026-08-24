# ADR Index

> Автоматически сгенерирован из ``docs/adr/*.md``.
> Последнее обновление: see git log.

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-0050](0050-net-waf-strict-single-entry.md) | WAF strict + Single Entry для исходящего HTTP | Accepted |
| [ADR-0051](0051-cache-decorators-facade.md) | Cache-декораторы как фасад поверх CachingDecorator | Accepted |
| [ADR-0052](0052-policy-decorator-order.md) | Каноничный порядок композиции в `@policy` | Accepted |
| [ADR-0053](0053-waf-phase2-migration.md) | WAF Phase-2: flip `outbound_via_facade=True` по умолчанию | Accepted |
| [ADR-0054](0054-sso-federation.md) | SSO Federation (SAML 2.0 + per-tenant IdP) | Accepted |
| [ADR-0055](0055-chaos-engineering.md) | Chaos Engineering + Performance Gate | Accepted |
| [ADR-0056](0056-routes-v11.md) | Routes V11.1a (DSL-routes как лёгкие плагины) | Accepted |
| [ADR-0057](0057-asgi-pure-chain.md) | Pure ASGI Middleware Chain | Accepted |
| [ADR-0058](0058-jsonschema-export.md) | JSON-Schema Export для DSL Processors | Accepted |
| [ADR-0059](0059-granian-rsgi-production.md) | Granian RSGI production tuning | Accepted |
| [ADR-0060](0060-blue-green-deploy.md) | Blue/Green deployment topology | Accepted |
| [ADR-0061](0061-waf-allowlist-tightening.md) | WAF allowlist tightening для Sprint 9 | Accepted |
| [ADR-0062](0062-middleware-layers-distinction.md) | Distinction между ASGI и Action-dispatch middleware | Accepted |
| [ADR-0063](0063-presidio-ru-ner-pii.md) | Presidio + ru NER как обязательный AI Safety layer (PII) | **Accepted** |
| [ADR-0064](0064-nemo-guardrails-llama-guard.md) | NeMo Guardrails + Llama Guard 3 defense-in-depth | **Accepted** |
| [ADR-0065](0065-langgraph-checkpointer-mem0.md) | LangGraph PostgresCheckpointer + Mem0 как единый long-term memory layer | **Accepted** |
| [ADR-0066](0066-ai-gateway-facade.md) | AIGateway — единая точка входа в AI | **Accepted** |
| [ADR-0067](0067-ai-policy-spec-dsl.md) | AIPolicySpec — декларативная политика AI per-workflow | **Draft** |
| [ADR-0068](0068-pii-tokenizer-reversible.md) | PIITokenizer — reversible PII tokenization layer | **Accepted** |
| [ADR-0069](0069-skill-registry-v11-2-toml.md) | SkillRegistry V11.2 — TOML-манифест для AI-tools | **Draft** |
| [ADR-0070](0070-mcp-gateway-namespaces.md) | MCP Gateway — domain namespaces + trusted external registry | **Draft** |
| [ADR-0071](0071-ai-audit-unified-schema.md) | AI Audit Unified Schema — `ai.invocation.*` события | **Draft** |
| [ADR-0072](0072-pii-production-enforcement.md) | PII production enforcement (Presidio + Langfuse + RAG ingest + MCP authz + Policy gate) | **Accepted** |
| [ADR-0073](0073-ragas-evaluation-gate.md) | RAGAS evaluation gate | **Accepted** |
| [ADR-0074](0074-rag-hybrid-retrieval-and-eval-gate.md) | RAG hybrid retrieval, embedding provenance, source attribution & eval gate | **Accepted** |
| [ADR-0075](0075-unified-agent-memory-gateway.md) | UnifiedAgentMemoryGateway (Protocol + dispatch) | **Accepted** |
| [ADR-0078](0078-plugin-toml-capability-syntax.md) | plugin.toml Capability Syntax: Array Format (`[[capabilities]]`) | Unknown |
| [ADR-0079](0079-slo-format-route-toml-slo.md) | SLO Format: Inline `route.toml::slo` (not separate sloth YAML) | Unknown |
| [ADR-0080](0080-single-entry-policy-naming.md) | Single Entry Policy Naming Convention | Unknown |
| [ADR-0081](0081-eventbus-production-backend-faststream-redis.md) | Event Bus Production Backend: FastStream + Redis | Unknown |
| [ADR-0082](0082-markitdown-network-isolation.md) | Network isolation для markitdown через monkey-patch urllib.request | Accepted |
| [ADR-0083](0083-versioning-dsl-continuum-wrapper.md) | Row-Level Versioning: thin DSL wrapper над `sqlalchemy-continuum` | Unknown |
| [ADR-0084](0084-library-adoption-migration-plan.md) | Library Adoption Migration Plan (structlog, typer, rich, aiocache) | Unknown |
| [ADR-0085](0085-user-auth-ldap-integration.md) | User Auth: LDAP as Primary, Password Deprecated | Unknown |
| [ADR-0086](0086-aiocache-migration-plan.md) | aiocache Migration Plan (S60+) | Unknown |
| [ADR-0087](0087-claimcheck-dedup.md) | ClaimCheckProcessor Dedup (S63 W2.1) | Unknown |
| [ADR-0088](0088-eip-10of10-coverage.md) | EIP 10/10 Coverage: TransactionalClient + ProcessManager (S63 W3.0) | Unknown |
| [ADR-0108](0108-di-dsl-for-routes.md) | DI DSL для RouteBuilder / call_function / process_fn | Accepted |
| [ADR-0109](0109-feature-flag-dependency-check-fix.md) | Feature Flag Dependency Check: package-aware + Sprint 41 audit | Accepted |
| [ADR-0110](0110-waf-coverage-100pct-formalize.md) | WAF Coverage 100% (formalize Sprint 41 #4 met) | Accepted |
| [ADR-0111](0111-chaos-multitenant-formalize.md) | Chaos Tests + Multi-Tenant Isolation status (Sprint 41 #1, #6) | Accepted |
| [ADR-0112](0112-security-audit-status.md) | Security Audit status (Sprint 41 #3) | Accepted |
| [ADR-0113](0113-perf-bg-dr-formalize.md) | Perf + Blue/Green + Disaster Recovery status (S41 #2, #7, #10) | Accepted |
| [ADR-0114](0114-dsl-lsp-server-formalize.md) | DSL LSP server status + Makefile integration (Sprint 42 #1) | Accepted |
| [ADR-0115](0115-sprint-42-dx-closure.md) | Sprint 42 closure: Developer Experience Polish (5/5 DoD) | Accepted |
| [ADR-0116](0116-sprint-43-closure.md) | Sprint 43 closure: Streamlit Filters + Vite Cleanup (2/5 DoD) | Accepted |
| [ADR-0117](0117-sprint-44-closure.md) | Sprint 44 closure: Backend Wiring + Admin Build Fix (4/5 DoD) | Accepted |
| [ADR-0118](0118-sprint-45-closure.md) | Sprint 45 closure: TD-006 + TD-018 + filter migration + docstrings (5/5 DoD) | Accepted |
| [ADR-0119](0119-sprint-46-closure.md) | Sprint 46 closure: TraceStorage abstraction + docstring tool + toxiproxy runbook (5/5 DoD) | Accepted |
| [ADR-0120](0120-sprint-47-closure.md) | Sprint 47 closure: ExecutionTracer storage wiring (1/5 substantive) | Accepted |
| [ADR-0121](0121-sprint-48-partial-closure.md) | Sprint 48 partial closure: TD-015 ruff F401 + mypy clean + stub regen verified | Accepted |
| [ADR-0122](0122-sprint-48-closure.md) | Sprint 48 closure: audit + re-scope + 5/5 waves (W1-W4 substantive, W5 closure) | Accepted |
| [ADR-0123](0123-sprint-49-closure.md) | Sprint 49 closure: TD-009 + actions.py decomp + trunk hygiene (4 commits, 5/5 substantive) | Accepted |
| [ADR-0124](0124-sprint-50-closure.md) | Sprint 50 closure: TD backlog + transport.py B3-B5 + ai_banking/rpa god-file decomp (5 commits, 5/5 substantive) | Accepted |
| [ADR-0125](0125-sprint-51-closure.md) | Sprint 51 closure: ai_rpa.py (2-wave) + agent_dsl.py + TD-003 (5 working + 1 fixup commits, 5/5 substantive) | Accepted |
| [ADR-0126](0126-sprint-52-closure.md) | Sprint 52 closure: ai_rpa.py W3 + validator.py + loader_v11.py god-file decomp + TD-010 closure (5+1 commits, 5/5 substantive) | Accepted |
| [ADR-0127](0127-sprint-53-closure.md) | Sprint 53 closure: format_convert + streaming + setup god-file decomp + TD-002 closure (5 commits, 5/5 substantive) | Accepted |
| [ADR-0128](0128-sprint-54-closure.md) | Sprint 54 closure: 4 god-file decomps (mcp_server, ai_agent, invoker, capability_gate) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0129](0129-sprint-55-closure.md) | Sprint 55 closure: 4 god-file decomp (cert_store, control_flow, pg_runner_internals, data_quality) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0130](0130-sprint-56-closure.md) | Sprint 56 closure: 4 god-file decomp (spec, gateway_pipeline_mixin, s3_pool, admin_workflows) (5+1 commits, 5/5 substantive) | Accepted |
| [ADR-0131](0131-sprint-57-closure.md) | Sprint 57 closure: 4 god-file decomp (base RouteBuilder, sources_mixin, collection EIP, sink_publish) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0132](0132-sprint-58-closure.md) | Sprint 58 closure: 4 god-file decomp (crud, saga_lra_processor, format_converters, workflow_builder) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0133](0133-sprint-59-closure.md) | Sprint 59 closure: 4 god-file decomp (banking_processors, lifecycle [sibling W82], redis, 31_DSL_Visual_Editor) (3+1 commits, 5/5 substantive) | Accepted |
| [ADR-0134](0134-sprint-60-closure.md) | Sprint 60 closure: 4 god-file decomp (jupyter, cdc, setup_infra, authorization_gateway) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0135](0135-sprint-61-closure.md) | Sprint 61 closure: 4 god-file decomp (base_service, enrichment, executor, http) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0136](0136-sprint-62-closure.md) | Sprint 62 closure: 4 god-file decomp (admin_plugins, vocabulary, integration_core, yaml_loader) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0137](0137-sprint-63-closure.md) | Sprint 63 closure: 4 god-file decomp (loading, routing, marshal, external_database) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0138](0138-sprint-64-closure.md) | Sprint 64 closure: 4 god-file decomp (graphql, repositories, database, rag_service) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0139](0139-sprint-65-closure.md) | Sprint 65 closure: 4 god-file decomp (components, rpa_operations, grpc_server, idp_pipeline) + 2 W3 sibling WIP fixups (4+1+2 commits, 7/7 substantive) | Accepted |
| [ADR-0140](0140-sprint-66-closure.md) | Sprint 66 closure: 3 god-file decomp (event_store, setup, lifecycle) + 1 sibling WIP fixup (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0141](0141-sprint-67-closure.md) | Sprint 67 closure: 4 god-file decomp (backpressure, ai_enforcer, semantic_cache, ad_directory_client) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0142](0142-sprint-68-closure.md) | Sprint 68 closure: 4 god-file decomp (macros, clickhouse_audit, invoker, ai_providers) (4+1 commits, 5/5 substantive) | Accepted |
| [ADR-0143](0143-sprint-83-w3-closure.md) | Sprint 83 W3: Vault DSL wrapper + PIL leak fix | Accepted |
| [ADR-0144](0144-multi-instance-safety.md) | Multi-instance safety: outbox claim_pending + scheduler leader election + RedisDedupeStore (4 commits, 3/5 substantive) | Accepted |
| [ADR-0145](0145-sprint-65-p0-cleanup-closure.md) | Sprint 65 closure: P0 cleanup (lazy imports, dead enforcement, dsl/workflows LAYERS) (3 commits, 3/3 substantive) | Accepted |
| [ADR-0146](0146-sprint-66-quick-wins-closure.md) | Sprint 66 closure: fact-checked quick wins (4 commits, 4/4 substantive) | Accepted |
| [ADR-0147](0147-sprint-67-torch-namespace-jwt-fix-closure.md) | Sprint 67 closure: torch CVE, namespace markers, JWT consolidation, pre-existing fix (4 commits, 4/4 substantive) | Accepted |
| [ADR-0148](0148-sprint-68-swarm-closure.md) | Sprint 68 closure: 3 parallel teams (swarm), 4 violations closed, 2 ADR docs (3 commits, 3/3 substantive) | Accepted |
| [ADR-0149](0149-core-violations-audit.md) | TD-S65-W2 audit: 34 core→other violations classified + 1 sample refactor (RetryPolicy) | Accepted |
| [ADR-0150](0150-dsl-violations-audit.md) | TD-S65-W4 audit: 124 dsl/workflows violations classified + 1 sample refactor (audit JSON codec) | Accepted |
| [ADR-0151](0151-sprint-69-swarm-2nd-closure.md) | Sprint 69 closure: 2nd SWARM (3 teams) — 1 violation closed + 2 style cleanups (3 commits, 3/3 substantive, scope discipline) | Accepted |
| [ADR-0152](0152-sprint-70-swarm-3rd-closure.md) | Sprint 70 closure: 3rd SWARM (3 teams) — 3 style cleanups (3 commits, 3/3 substantive, 2/3 subagent clean) | Accepted |
| [ADR-0153](0153-sprint-71-pre-existing-bugs-and-multi-instance-safety-closure.md) | Sprint 71 closure: 4 pre-existing import bugs + 3 file+dir merges + 2 P1 multi-instance safety fixes (4 commits, 7+3 NEW tests) | Accepted |
| [ADR-0154](0154-sprint-72-outbox-per-row-claim-closure.md) | Sprint 72 closure: TD-S64-W1 per-row outbox claim (3 files, 5+1 NEW tests, per-row lease + sweeper) | Accepted |
| [ADR-0155](0155-sprint-73-p0-a-except-bug-batch-fix-closure.md) | Sprint 73 closure: P0-A batch fix (106 files, 136 except-A-B fixes, 2 NEW regression tests, pre-push CI gate) (5 commits) | Accepted |
| [ADR-0156](0156-sprint-74-jupyter-execution-ecosystem-closure.md) | Sprint 74 closure: Jupiter Hub + Notebook Execution ecosystem (Papermill + Factory + WebSocket heartbeat, 13 NEW tests) (5 commits) | Accepted |
| [ADR-0157](0157-sprint-75-jupyter-execution-final-closure.md) | Sprint 75 closure: направление #1 final closure (e2b ExecutionBackend + KernelSpecDiscovery, 15 NEW tests) (5 commits) | Accepted |
| [ADR-0158](0158-sprint-76-tools-whitelist-closure.md) | Sprint 76 closure: P0-B tools whitelist в AIPolicySpec (ToolsSpec + enforcement + 21 NEW tests) (5 commits) | Accepted |
| [ADR-0159](0159-sprint-77-ai-policy-dsl-closure.md) | Sprint 77 closure: P0-C AI Policy Spec DSL (hot-reload + JSON-Schema + specificity, 20 NEW tests) (5 commits) | Accepted |
| [ADR-0160](0160-sprint-78-streamlit-cors-xsrf-closure.md) | Sprint 78 closure: P0-D CORS/XSRF в Streamlit (config security + nginx + validator + 17 NEW tests) (5 commits) | Accepted |
| [ADR-0161](0161-sprint-79-capability-gate-tools-integration-closure.md) | Sprint 79 closure: CapabilityGate ↔ AIPolicySpec.tools two-layer integration (FINAL_REPORT_V2 направление #4 closure, 16 NEW tests) (6 commits) | Accepted |
| [ADR-0162](0162-sprint-80-litellm-pool-registration-closure.md) | Sprint 80 closure: P1 #6 LiteLLM Gateway pool registration (PoolHealthMonitor integration, 8 NEW tests) (6 commits) | Accepted |
| [ADR-0163](0163-sprint-81-circuit-breaker-middleware-closure.md) | Sprint 81 closure: P1 #8 CircuitBreakerMiddleware restoration (per-route state, sliding window, 13 NEW tests) (4 commits) | Accepted |
| [ADR-0248](0248-s43-deep-audit-quick-wins.md) | Sprint 43: Deep-Audit Quick Wins (Layer linter P0 + P7 logger + schemas shims) | Unknown |
| [ADR-0249](0249-s44-audit-followup-facades.md) | Sprint 44: Audit Follow-up — Facades + Migrations | Unknown |
| [ADR-0250](0250-s45-audit-backlog-closure.md) | Sprint 45: Audit Backlog QW10 + S1 Closure | Unknown |
| [ADR-0251](0251-s13-circuit-breaker-shared-state.md) | S13: Circuit Breaker Middleware → Shared State | Unknown |

**Total:** 97 ADRs.

