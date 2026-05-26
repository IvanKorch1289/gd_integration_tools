# Changelog

All notable changes to **GD Integration Tools** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

### Total: 26 commits across 29 waves

## [0.1.0] — 2025 — Initial release

- Initial release of GD Integration Tools
