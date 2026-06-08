# Changelog

All notable changes to **GD Integration Tools** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — Sprint 63 (2026-06-08)

### Fixed

#### s63/w1-mypy-regressions
- LoggerProtocol.critical() добавлен в оба протокола (ABC + typing.Protocol)
  — закрыто 7 mypy attr-defined errors (S60 W2 structlog migration leftover)
- audit_versioning.py:57-58 type attrs (Transaction.id/issued_at) — `type` → `type[Any]`
- workflows/worker.py:312 NameError UTC — `from datetime import UTC, datetime`
- admin_parallelism.py:25 import-not-found — `# type: ignore[import-not-found]`
- generator/actions.py:675 spec.schema_in — local var workaround
- test_factory.py::test_get_object_storage_non_local_fallback_and_warns (S61 W1 bug)
  — monkeypatch `builtins.__import__` форсирует ImportError → fallback path
- **mypy 37 → 26 errors (-30%)** measured на чистом .mypy_cache

#### s63/w1-streamlit-td008
- 12 страниц с `# noqa: E402` на `get_api_client` импорте — noqa удалён (не нужен)
- 32_DSL_Builder и 83_Tenant_Inspection — `st.set_page_config` → `setup_page()` (S43 W1 helper)
- 43_Realtime_Logs — I001 (unsorted imports) auto-fixed
- **TD-008 PARTIAL CLOSURE**: groups 1+2+6 done (3/3 P1+P3); groups 3-5 (P2) deferred

### Changed

#### s63/w2-claim-check-dedup
- `src.backend.dsl.processors.claim_check_processor` (S38 W1, SLIM S3-only) удалён
- `src.backend.dsl.engine.processors.eip.transformation.ClaimCheckProcessor`
  (Redis + S3 composite, mode-based) — каноническая реализация
- `dsl/processors/__init__.py` — убран ClaimCheckProcessor из __all__,
  добавлен deprecation note в docstring
- -337 LOC (1 source + 1 test удалены)

#### s63/w2-ruff-autofix
- ruff --fix (637 auto-fixes: 602 I001 + 35 F401)
- 645 → 5 errors (-99.2%)
- F401 removals: 35 unused `get_logger` imports (S60 W2 structlog migration leftover)
- Net: -364 LOC across 600 files

#### s63/w3-perf-gate-typer
- `tools/perf_gate.py` — argparse → typer @app.callback (preserve 12 flag names)
- print() → rich.Console (out_console / err_console)
- main() entry: typer.Exit(code=...) вместо return code
- Helpers UNCHANGED (loose duck-typed .attr contract → SimpleNamespace bridge)
- Test backward compat: test_perf_gate_strict_mode_env принимает argparse.Namespace
  без изменений (helper не зависит от конкретного Namespace type)
- Pre-existing ruff: S108 (/tmp/) и S603 (subprocess) silenced с rationale

## [0.20.0] — 2026-05-26 — Sprint 28

### Added

#### s28/k4-w4-langgraph-integration
- AgentGraphProcessor (LangGraph as DSL step): supervisor + ReAct modes
- AgentDSLMixin.agent_graph() Builder method
- ADR-0076: LangGraph integration decision (keep + wrap, not core engine)

#### s28/k4-w2-skill-registry-impl
- SkillRegistry.from_toml_manifest(): load [[skill]] tables from plugin.toml V11.2
- SkillRegistry.invoke(): dynamic import_module + capability check

#### s28/k4-w3-aigateway-enforcement
- AIPolicyEnforcer.sanitize_input(): uses PIITokenizer
- AIPolicyEnforcer.sanitize_output(): uses PIITokenizer
- ai_gateway_enforce default: False → True

#### s28/k1-w5-pii-ru-expansion
- AddressRuRecognizer (ADDRESS_RU): Russian address patterns + context boost
- BankAccountRuRecognizer (BANK_ACCOUNT_RU): 20-digit settlement accounts + БИК
- DriverLicenseRuRecognizer (DRIVER_LICENSE_RU): old + new format, Cyrillic + Latin

#### s28/k4-w6-rag-memory-hardening
- HuggingFace role formatting fix: system: prefix for system messages
- LLM Judge JSON extraction: strip markdown code fences (```json ... ```)
- HybridRetriever: corpus_loader + reload() for Redis-backed multi-instance corpus

#### s28/k4-w7-sandbox-decision
- ADR-0077: E2B for production, NoOp for dev, Pyodide deferred

#### s28/k4-w8-observability
- GuardrailsMetricsService: ClickHouse bulk writer integration
- New record() fields: model_used, cost_usd, latency_ms
- SQL schema documented: guardrail_events table

### Changed

#### s28/k4-w1-dep-cleanup
- Removed dead AI deps from pyproject.toml: langchain-core, langchain-community, langmem, mem0ai
- Kept: langgraph (3 real consumers), pydantic-ai (lazy import), chromadb (HttpClient dev)

### Fixed

- AIGateway._apply_input/output_guards: return list[GuardResult]
- AI policy enforcer: guardrails_verdict type fix (dict not None)

## [0.19.0] — 2026-05-26 — Sprint 19

### Added

#### s19/backbone
- 21 default-OFF feature flags + team_s19.k1..k5 ownership

#### s19/k1-w1-vault-zero-downtime-rotation
- Zero-downtime Vault secret rotation with drift-tolerance and validation-before-activation
- VaultSecretRotator with graceful_reconnect

#### s19/k1-w5-ai-safety-capability-unify
- fs.create_new deprecated → fs.write.<scope> unified capability model

#### s19/k2-w1-multi-replica-failover
- SmartSessionManager pg_stat_replication lag monitoring + lag-budget routing

#### s19/k3-w1-workflow-versioning-routes
- WorkflowLauncher with SemVer range support
- requires_workflows in route.toml with SemVer check and audit event

#### s19/k3-w2-route-composition-include
- include:/extends: support in DSL YAML files with cycle detection

#### s19/k3-w3-route-authz-requires-permission
- AuthorizationGateway route-level permissions validation
- route.toml [security] requires_permission validation

#### s19/k3-w4-lsp-server-finale
- YAML schema completion for DSL LSP server

#### s19/k3-w5-dsl-visual-editor-finale
- Streamlit drag-drop route builder with step reordering

#### s19/k3-w6-dsl-usage-audit
- tools/audit/dsl_usage_audit.py for usage auditing

#### s19/k4-w1-multipart-rag-ingest
- Bulk RAG ingest endpoint + UI

#### s19/k4-w2-reranking-pipeline
- RerankerProcessor with cross-encoder reranking pipeline

#### s19/k4-w3-banking-ai-processors-impl
- 5 Banking AI processors: KYC/AML, AntiFraud, CreditScoring, DocumentClassifier, Francotyping

#### s19/k4-w5-ai-pr-review-action
- AI PR review workflow with Claude Code API, prompt caching, cost ≤$0.10/PR
- GitHub Action: layer-policy + security + perf-regression + coverage delta checks

#### s19/k4-w6-adaptive-rag-strategy-finale
- RAGStrategySelector with dense/hybrid/hyde/multi_query retrieval strategies

#### s19/k5-w1-rpa-browser-session-persistence
- BrowserLaunchProcessor lazy-restore cookies via BrowserCookieStore
- NavigateProcessor session save/restore

#### s19/k5-w2-vscode-extension
- VSIX extension scaffold with LSP client

#### s19/k5-w3-testkit-public-api
- src/testkit/ public API for extensions/plugin authors

#### s19/k5-w4-quick-wins-pack
- make new-adr + manage.py completions + make release-notes

#### s19/k5-w5-admin-react-mvp
- React-based admin UI (frontend/admin-react/) with dashboard and route management

#### s19/k1-w2-current-frames-fallback
- sys._current_frames() graceful fallback for PyPy/Jython in check_deadlock.py

#### s19/k1-w6-prod-hot-reload-disable
- Disable hot-reload when APP_PROFILE=prod

#### s19/k2-w4-coverage-ratchet-75
- Coverage gate threshold ratchet 70%→75%
- _DEFAULT_THRESHOLD=75 in check_coverage_gate.py
- CI --threshold updated to 75 in test.yml

#### s19/adr-w1-r1-1-r1-5-r1-7
- R1.1→ADR-0078: plugin.toml [[capabilities]] array format with name+scope
- R1.5→ADR-0079: route.toml::slo inline TOML (p95_ms/p99_ms/timeout_ms/rps_target)
- R1.7→ADR-0080: Single Entry policy naming — Coordinator/with_/Spec/Policy suffixes

#### s19/adr-w2-r1-8-r1-9-r1-20
- R1.8→ADR-0081 FastStream Redis (EventBus, confirmed by adr-w1)
- R1.9→ADR-0059 Granian RSGI (Accepted S6)
- R1.20→ADR-0077 E2B sandbox (Accepted S28)

### Total: 28 commits across 29 documented waves

## [0.1.0] — 2025 — Initial release

- Initial release of GD Integration Tools
