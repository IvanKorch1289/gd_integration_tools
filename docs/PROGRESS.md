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
- [x] D2 RPA max (self-healing+visual+activities+ComputerUse) — статус: done — commit: HEAD — ADR: —
- [x] D3 RAG stack upgrade (qdrant+fastembed) — статус: done — commit: HEAD — ADR: ADR-014

## Phase E — DevEx (P1)

- [x] E1 DSL utils max (banking+fluent+shortcuts+macros) — статус: done — commit: HEAD — ADR: —
- [x] E2 Dev tools (hot-reload+dev-panel+linter+REPL+diff) — статус: done — commit: HEAD — ADR: —

## Phase F — Performance (P1)

- [x] F1 Performance stack max (uvloop+msgspec+granian+HTTP/2+3.14FT) — статус: done — commit: HEAD — ADR: ADR-006,ADR-007
- [x] F2 pandas → polars полная миграция — статус: done — commit: HEAD — ADR: ADR-008

## Phase G — API/Tenant/Observability (P2)

- [x] G1 Multi-tenancy max (RLS+RedisPrefix+RL+Quotas+Billing) — статус: done — commit: HEAD — ADR: —
- [x] G2 API Management + Developer Portal max — статус: done — commit: HEAD — ADR: ADR-015
- [x] G3 Hardening + observability final — статус: done — commit: HEAD — ADR: —

## Phase H — Docs / Cleanup / Release (P2)

- [x] H1 Документация (RU) + 15 ADR — статус: done — commit: HEAD — ADR: —
- [x] H2 Scaffolding + DSL visualization — статус: done — commit: HEAD — ADR: —
- [x] H3 Cleanup (deprecated deps + dead code) — статус: done — commit: HEAD — ADR: —
- [x] H4 Final verification + release — статус: done — commit: HEAD — ADR: —

## Phase I — Extended Integrations (P2)

- [x] I1 Enterprise коннекторы (AS2+EDI X12+SAP+IBM MQ+JMS+NATS+SFTP) — статус: done — commit: HEAD — ADR: —
- [x] I2 Data lake + CDC max (MySQL/Mongo/Oracle+Iceberg+Delta+Temporal+Beam+GraphQL subs) — статус: done — commit: HEAD — ADR: ADR-016

## Phase J — Extended Performance (P2)

- [x] J1 Performance+ max (Rust/Cython + HTTP/3 + shared-mem + NUMA + jemalloc) — статус: done — commit: HEAD — ADR: ADR-017,ADR-018,ADR-019

## Phase K — Extended DSL (P2)

- [x] K1 DSL+ max (Tooling + Authoring + Interop) — статус: done — commit: HEAD — ADR: ADR-020,ADR-021

## Phase L — Onboarding Portal (P2)

- [x] L1 Onboarding portal max (Sandbox + AI-ассистент + Learning) — статус: done — commit: HEAD — ADR: —

## Phase M — Extended Resilience (P2)

- [x] M1 Resilience+ max (Chaos + LS + Hedging + ES/CQRS + Backup) — статус: done — commit: HEAD — ADR: —

## Phase N — Business Logic Core (P2)

- [x] N1 Business Logic max (BPMN + Rules + Forms + ЭЦП + KYC + Temporal tables) — статус: done — commit: HEAD — ADR: —

## Phase O — External Env Max (P2)

- [x] O1 External env max (Vault Transit/DB + K8s + S3/Email/SMS/Push/Payments + Observability SaaS) — статус: done — commit: HEAD — ADR: —

## Phase IL — Infrastructure Layer production-доводка (follow-up, P0/P1/P2)

Фазы добавлены после initial 40/40 closure как production-доводка по слоям
(первый слой — инфраструктурный: подключения к внешним сервисам). План:
`/root/.claude/plans/tidy-jingling-map.md`. ADR: ADR-022..ADR-024.

- [x] IL1 Infrastructure Layer P0 — ConnectorRegistry + Metrics + OTEL full + CB + Kafka idempotent + deep health + admin API + PoolingProfile — статус: done — commit: HEAD — ADR: ADR-022
- [ ] IL2 Infrastructure Layer P1 — Kafka FastStream + NotificationGateway (Jinja2+DLQ+Priority) + Reconnection + Vault hot-reload + IMAP pool + HTTP upstream + Streamlit dashboard — статус: planned — commit: — — ADR: ADR-023
- [ ] IL3 Infrastructure Layer P2 — Outbox notify + gRPC interceptors + Hedging + Deadline + Load shedding + Grafana + Exemplars + Alert rules + S3 multipart + tenant pools — статус: planned — commit: — — ADR: ADR-024
- [ ] IL-DB1 DB Layer доводка — FK indexes + JSONB + selectinload N+1 fix + Query/Bulk/Transaction DB DSL — статус: planned — commit: — — ADR: ADR-025
- [ ] IL-BIZ1 Business Logic Layer — multi-tenant cache + Saga + async streaming export + PII audit — статус: planned — commit: — — ADR: ADR-026
- [ ] IL-AI1 AI Layer — cost observability + streaming LLM (SSE) + Cost Budget DSL — статус: planned — commit: — — ADR: ADR-027
- [ ] IL-CRIT1 P0 Critical fixes — SQL injection / gRPC leak / AI cleanup / OPA pool / Outbox listen / unified dispatch / SOAP async — статус: planned — commit: — — ADR: —
- [ ] IL-SEC2 Security hardening — envelope encryption + immutable audit + tenant-scoped Casbin — статус: planned — commit: — — ADR: ADR-028
- [ ] IL-BIZ2 Business ESB stack — Rules + CommandBus + Feature Store + BaseExternalAPI + ServiceError typing — статус: planned — commit: — — ADR: ADR-029
- [ ] IL-AI2 AI stack — LiteLLM + Langfuse + tenacity + Redis BM25 + ST cleanup — статус: planned — commit: — — ADR: ADR-030
- [ ] IL-WF1 Prefect removal + DSL durable workflows — статус: planned — commit: — — ADR: ADR-031
- [ ] IL-OBS1 Observability automation — OTEL middleware + body cache + Grafana + alert rules — статус: planned — commit: — — ADR: ADR-032
- [ ] IL-DOCS1 Docs + Frontend — 6 H1 docs + FE boilerplate + authenticator + cache_data — статус: planned — commit: — — ADR: —

---

**Всего фаз:** 53. **Закрыто:** 41. **В работе:** 1 (IL2). **Запланировано:** 11 (IL3, IL-DB1, IL-BIZ1, IL-AI1, IL-CRIT1, IL-SEC2, IL-BIZ2, IL-AI2, IL-WF1, IL-OBS1, IL-DOCS1).

Initial closure (40/40) зафиксирована 2026-04-21; дальнейшая production-доводка
добавляется как новые IL-фазы по мере выполнения. Каждая IL-фаза — самостоятельный
коммит с префиксом `[phase:IL<N>]` и ADR-ссылкой.

(Примечание: в тексте initial плана фигурировало "38", реальная декомпозиция
дала 40 — отличие учтено в `docs/adr/PHASE_STATUS.yml::meta`.)

MR в `master` не будет пропущен, пока счётчик «закрыто» не равен total.
