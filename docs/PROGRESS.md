# Production Readiness — Progress Ledger

Единый чек-лист всех 38 под-фаз плана `production-readiness-review`. Обновляется
pre-commit hook `tools/update_progress.py` на основании commit-message формата
`[phase:<ID>] <summary>`. MR в `master` заблокирован job-ом `progress-gate`,
пока хоть одна строка не в статусе `done`.

Формат строки:
`- [ ] <ID> <Название> — статус: <planned|in-progress|done> — commit: <sha|—> — ADR: <ADR-NNN|—>`

## Phase A — Foundation (P0)

- [x] A1 Baseline inventory + pre-commit + guardrails — статус: done — commit: HEAD — ADR: —
- [x] A2 Security hardening — статус: done — commit: HEAD — ADR: ADR-003,ADR-004
- [x] A3 DI consolidation (svcs only) — статус: done — commit: HEAD — ADR: ADR-002
- [x] A4 Resilience consolidation + aiohttp→httpx — статус: done — commit: HEAD — ADR: ADR-005,ADR-009
- [x] A5 GitLab CI (merge-gates без test-stage) — статус: done — commit: HEAD — ADR: —

## Phase B — Structure (P1)

- [x] B1 Refactor builder.py → 11 миксинов — статус: done — commit: HEAD — ADR: ADR-001
- [x] B2 Split files > 500 LOC — статус: done — commit: HEAD — ADR: —

## Phase C — Framework Ports (P1)

- [x] C1 Camel EIP (полный набор) — статус: done — commit: HEAD — ADR: —
- [x] C2 Spring Integration (Gateway+Interceptors+Versioning) — статус: done — commit: HEAD — ADR: —
- [x] C3 Orchestration (Sensor+Backfill+DryRun+HITL) — статус: done — commit: HEAD — ADR: —
- [x] C4 CloudEvents + Schema Registry + AsyncAPI — статус: done — commit: HEAD — ADR: ADR-010
- [x] C5 Outbox+Inbox + FastStream унификация — статус: done — commit: HEAD — ADR: ADR-011,ADR-013
- [x] C6 OPA + Casbin (двухуровневая авторизация) — статус: done — commit: HEAD — ADR: ADR-012
- [x] C7 Data contracts / expectations — статус: done — commit: HEAD — ADR: —
- [x] C8 Transformations max (фасад 7 engines) — статус: done — commit: HEAD — ADR: —
- [x] C9 Codecs max (все форматы + банковские) — статус: done — commit: HEAD — ADR: —
- [x] C10 Connectors max (IoT+Web3+Legacy) — статус: done — commit: HEAD — ADR: —
- [x] C11 SOAP + IMAP async-миграция — статус: done — commit: HEAD — ADR: —

## Phase D — AI / ML / RPA (P1)

- [x] D1 AI agents DSL max (ReAct+PlanExec+LangGraph+eval) — статус: done — commit: HEAD — ADR: —
- [ ] D2 RPA max (self-healing+visual+activities+ComputerUse) — статус: planned — commit: — — ADR: —
- [ ] D3 RAG stack upgrade (qdrant+fastembed) — статус: planned — commit: — — ADR: ADR-014

## Phase E — DevEx (P1)

- [ ] E1 DSL utils max (banking+fluent+shortcuts+macros) — статус: planned — commit: — — ADR: —
- [ ] E2 Dev tools (hot-reload+dev-panel+linter+REPL+diff) — статус: planned — commit: — — ADR: —

## Phase F — Performance (P1)

- [ ] F1 Performance stack max (uvloop+msgspec+granian+HTTP/2+3.14FT) — статус: planned — commit: — — ADR: ADR-006,ADR-007
- [ ] F2 pandas → polars полная миграция — статус: planned — commit: — — ADR: ADR-008

## Phase G — API/Tenant/Observability (P2)

- [ ] G1 Multi-tenancy max (RLS+RedisPrefix+RL+Quotas+Billing) — статус: planned — commit: — — ADR: —
- [ ] G2 API Management + Developer Portal max — статус: planned — commit: — — ADR: ADR-015
- [ ] G3 Hardening + observability final — статус: planned — commit: — — ADR: —

## Phase H — Docs / Cleanup / Release (P2)

- [ ] H1 Документация (RU) + 15 ADR — статус: planned — commit: — — ADR: —
- [ ] H2 Scaffolding + DSL visualization — статус: planned — commit: — — ADR: —
- [ ] H3 Cleanup (deprecated deps + dead code) — статус: planned — commit: — — ADR: —
- [ ] H4 Final verification + release — статус: planned — commit: — — ADR: —

## Phase I — Extended Integrations (P2)

- [ ] I1 Enterprise коннекторы (AS2+EDI X12+SAP+IBM MQ+JMS+NATS+SFTP) — статус: planned — commit: — — ADR: —
- [ ] I2 Data lake + CDC max (MySQL/Mongo/Oracle+Iceberg+Delta+Temporal+Beam+GraphQL subs) — статус: planned — commit: — — ADR: ADR-016

## Phase J — Extended Performance (P2)

- [ ] J1 Performance+ max (Rust/Cython + HTTP/3 + shared-mem + NUMA + jemalloc) — статус: planned — commit: — — ADR: ADR-017,ADR-018,ADR-019

## Phase K — Extended DSL (P2)

- [ ] K1 DSL+ max (Tooling + Authoring + Interop) — статус: planned — commit: — — ADR: ADR-020,ADR-021

## Phase L — Onboarding Portal (P2)

- [ ] L1 Onboarding portal max (Sandbox + AI-ассистент + Learning) — статус: planned — commit: — — ADR: —

## Phase M — Extended Resilience (P2)

- [ ] M1 Resilience+ max (Chaos + LS + Hedging + ES/CQRS + Backup) — статус: planned — commit: — — ADR: —

## Phase N — Business Logic Core (P2)

- [ ] N1 Business Logic max (BPMN + Rules + Forms + ЭЦП + KYC + Temporal tables) — статус: planned — commit: — — ADR: —

## Phase O — External Env Max (P2)

- [ ] O1 External env max (Vault Transit/DB + K8s + S3/Email/SMS/Push/Payments + Observability SaaS) — статус: planned — commit: — — ADR: —

---

**Всего фаз:** 38. **Закрыто:** 18. **В работе:** 0.

MR в `master` не будет пропущен, пока счётчик «закрыто» не равен 38.
