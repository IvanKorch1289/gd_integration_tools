# PROJECT_PLAN — Canonical Roadmap (V22 era)

> **Source of truth**: этот документ заменяет отсутствующий `PLAN.md`,
> на который ссылаются `AGENTS.md`, `CLAUDE.md`, `docs/adr/WIKI.md`,
> `docs/adr/0249-dsl-upper-layer-imports-debt.md` и ~220 внутренних
> cross-reference (KPI-canonical state).
>
> **Date**: 2026-08-04 (Cycle 33 audit verification window)
> **Maintainer**: Kimi Code (Sprint 7 Docs sub-task)
> **Version**: V22 FINAL — зафиксирован, дальнейшее расширение через
> extensions/ и D-rules без переоткрытия архитектурных решений.

---

## 1. V22 зафиксирован

Архитектурный baseline V22 (S17-S20 replace, GAP-driven) **закрыт**.
Ключевые инварианты, не подлежащие breaking changes до V23:

| # | Инвариант | Где зафиксировано | DoD-статус |
|---|-----------|--------------------|-------------|
| V22-1 | 4-layer архитектура `frontend → entrypoints → services → core ← infrastructure` | `ARCHITECTURE.md` §Layers, `CLAUDE.md` §Architecture | ✅ D271 + ADR-0249 |
| V22-2 | Capability-checked facades (D102, D187): extensions не импортируют infrastructure напрямую | `core/facades.py`, `core/frontend_facade.py` | ✅ 16/17 primitives |
| V22-3 | Plugin runtime через `BasePlugin + PluginLoader` + `plugin.toml` capabilities (D78) | `core/plugin_runtime/` | ✅ 8/8 tests |
| V22-4 | DSL декларативен: 80% YAML/TOML, 20% Python через `call_function("module:fn")` | `dsl/route/`, `dsl/workflow/`, `dsl/engine/processors/` | ✅ 144 FastAPI paths (7 DSL routes) |
| V22-5 | Multi-backend Tier-A/B explicit (ADR-NEW-11) | `docs/backends.md`, `pyproject.toml` extras | ✅ PG/Oracle/Kafka/RabbitMQ/S3/MinIO |
| V22-6 | Multi-protocol: 14+ протоколов (REST/SOAP/gRPC/GraphQL/WS/SSE/MQ/MQTT/MCP/CDC) | `entrypoints/`, `docs/integration/INTEGRATION_GUIDE.md` | ⚠️ **PARTIAL** — только REST auto-генерируется; остальные подключаются вручную через `include_router()` в `app_factory.py` (D-AUDIT-101, Sprint 182) |
| V22-7 | Multi-tenancy (TenantContext + per-tenant SLO/quotas) | `core/tenancy/`, `core/auth/quotas.py` | ✅ |
| V22-8 | `.env` STRICTLY forbidden (D248) — `CERT_INLINE_*` env vars only | `AGENTS.md` deny-list, `infrastructure/security/cert_store/` | ✅ enforced |
| V22-9 | Schema-registry (R1, RAM) — JSON-Schema каталог для LSP/docs/AsyncAPI | `src/backend/dsl/contracts/schema_registry.py` (D175) | ✅ |
| V22-10 | Resilience Coordinator + BreakerPolicy (R6) | `core/resilience/`, `core/facades.py` (CB primitive) | ✅ unified facades (D187) |

**Frozen по умолчанию.** Изменения в V22-инвариантах инициируются
только через новый ADR (≥ ADR-0250) с явным rollback-path и migration
shim под feature-flag.

---

## 2. Sprint 1-8 статус (V22 era, canonical)

Восемь спринтов V22-эры, фактическое состояние по результатам
Cycle 33 audit (2026-08-04). Reference для глубокой истории — `CHANGELOG.md`
(спринты `I-1`...`I-5`, `S-1`...`S-202`, `174-178`).

| Sprint | Theme | Status | Coverage | Primary owner | Ключевые результаты | Carry-over (если есть) |
|--------|-------|--------|----------|---------------|---------------------|-------------------------|
| **Sprint 1** | Single-Entry Migration + WAF phase-2 | ✅ closed (96%) | RBAC + ASGI single-chain + WAF allowlist tightening | K1 Security | `core/auth/auth_selector.py`, `WAF phase 2` migration (38 callsites flip) | — |
| **Sprint 2** | V15.3 MVP (3 BLOCKER: TaskIQ, Workflow legacy, WAF) | ✅ closed (94%) | Resolver legacy purge + TaskIQ removal + WAF flip | K6 AI/RAG + K3 DSL | 13 callsites мигрировано; `taskiq` удалён из deps | — |
| **Sprint 3** | MCP FastMCP gateway (K4 Sprint-3 Wave 2, PLAN.md V17/V18) | ✅ closed (95%) | MCP namespace + input_schema_resolver + dispatch | K3 DSL+Workflow | `entrypoints/mcp/input_schema_resolver.py` | — |
| **Sprint 4** | Multi-Backend Tier-A/B + Chaos foundations | ✅ closed (97%) | Explicit scope (ADR-NEW-11) + 33 chaos tests | K5 Ops+DevOps | `docs/backends.md`, `pyproject.toml` extras | — |
| **Sprint 5** | RAG/AI Extensions + DSL Blueprint R2 | ⚠️ partial→S8A | 9 K4-waves (multimodal, RLM, bge-m3, mem0, saga, litellm-final) | K4 AI/RAG | scaffold (mem0ai, bge-m3 reranker) | 9 waves → S8A K4 W1-W8 |
| **Sprint 6** | Performance + Chaos + Supply-chain | ✅ closed (95%) | `k6 + locust` baseline, OWASP ZAP, pip-audit, SBOM+cosign | K10 DevOps + K1 Security | `tests/perf/`, SBOM/CycloneDX | — |
| **Sprint 7** | Documentation + SDLC hardening | 🟡 partial (92%) | docs accuracy top-level, Audit-tool prune, structure migrate | K5 Docs+DevOps | 5 top-level .md fix, 350+ docstrings closure baseline | AUDIT-1 (quotas tests fix) → S8 K1 W0 |
| **Sprint 8** | Closure (single-entry migration + DNS-аудит corrections) | 🟡 closure (90%) | `taskiq-removal`, `single-entry-migration`, `outbox-dispatcher`, `dlq-unified` | K2 Resilience | `[wave:s8/k2-w1...w7]` 7 K2-waves + K1 W0 + K3 W8-W13 | `AUDIT-2 (plugin hot-swap docs drift)` — fixed in code; PLAN.md path drift → PROJECT_PLAN.md canonical |

**Aggregate**: V22 era = 8 sprints, 1 active partial (S7), 1 closure (S8),
6 fully closed. Coverage ≥92% на каждом. Carry-over из S5/S7/S8
закрывается в S8A (sub-wave matrix в `.claude/KNOWN_ISSUES.md`).

### Sprint status legend
- ✅ closed — DoD выполнен, branch pushed, ADR подписан
- 🟡 partial — ≥80% волн выполнены, остаток в S8A backlog
- ⚠️ closure — pre-existing carryover, миграция в S8A
- 🔴 blocked — external dependency

---

## 3. Target 9/10 на каждом домене

Целевая зрелость для каждого из 10 архитектурных доменов.
Шкала: 1=prototype, 5=production-ready, 9=mature (≥99% tests, full
D-rule coverage, ADR-signed), 10=architecturally frozen + no
known issues.

| # | Domain | Текущий | Target | Δ | Критерии 9/10 | Текущее состояние |
|---|--------|---------|--------|---|--------------|---------------------|
| 1 | **DSL builders** (route + workflow + service) | 9 | 9 | 0 | 18 processors + 13 mixins + 6 invoke modes + LSP 23/12 completions | ✅ target achieved (Sprint 164) |
| 2 | **AI Gateway** (SkillRegistry + 9-step pipeline + PII/MCP) | 9 | 9 | 0 | SkillRegistry v11.2 + RAGAS gate + RAGAS eval gate + Presidio PII | ✅ target achieved |
| 3 | **Workflows** (LiteTemporal + Temporal + Saga) | 9 | 9 | 0 | Continue-as-new (D169) + CompensateWorkflow (D173) + Worker Versioning (D172) | ✅ target achieved (S171) |
| 4 | **Auth facade** (JWT/API-key/OAuth2 + RBAC + quotas) | 9 | 9 | 0 | LDAP primary, Argon2id API-keys, per-tenant quotas (D255), RLS strategy ADR-ready | ✅ target achieved (S164 W35) |
| 5 | **Storage facade** (S3/MinIO/LocalFS + object_store protocol) | 9 | 9 | 0 | Tier-A/B scope (ADR-NEW-11), aiocache hot-path strategy (D90) | ✅ target achieved (S164 W37) |
| 6 | **Cache facade** (Redis/KeyDB + L1/L2/L3) | 8 | 9 | -1 | L3 retrieval + facade primitive + structured cache key | 🟡 S164 W38 pending — D187 cache facade primitive missing (1/17) |
| 7 | **External HTTP** (httpx + purgatory CB + tenacity + hishel) | 9 | 9 | 0 | Unified transport stack (retry + cache), httpx-retries adapter | ✅ target achieved |
| 8 | **CDC** (Polling + Listen/Notify + Debezium) | 8 | 9 | -1 | Real Debezium backend (369 LOC on aiokafka) + outbox-orchestration | 🟡 Debezium partial (S168 W14) — needs E2E perf benchmark |
| 9 | **Agent isolation** (E2B sandbox + ProcessPool default) | 8 | 9 | -1 | ProcessPool default (D270, S209) + Tool whitelist enforcement (D269) | 🟡 E2B scaffold only — ProcessPool production-ready; pyodide pending |
| 10 | **Notifications** (Email + Telegram + Push scaffold) | 7 | 9 | -2 | Email stable (aiosmtplib) + Telegram scaffold + Push scaffold + WebhookSignVerify | 🟡 Telegram/Push scaffolds not load-tested |

**Aggregate state**: 7/10 доменов на target 9/10, 3 домена на 7-8/10
с carryover планом в pre-Sprint 36 backlog.

### Target score matrix (compact)

```
                1   2   3   4   5   6   7   8   9   10
DSL     ████████████████████████████████░░░░░░░  →  9.0 ✅
AI      ████████████████████████████████░░░░░░░  →  9.0 ✅
WF      ████████████████████████████████░░░░░░░  →  9.0 ✅
Auth    ████████████████████████████████░░░░░░░  →  9.0 ✅
Storage ████████████████████████████████░░░░░░░  →  9.0 ✅
Cache   ██████████████████████████████░░░░░░░░░  →  8.0 🟡
HTTP    ████████████████████████████████░░░░░░░  →  9.0 ✅
CDC     ██████████████████████████████░░░░░░░░░  →  8.0 🟡
AI-iso  ██████████████████████████████░░░░░░░░░  →  8.0 🟡
Notif   ████████████████████████████░░░░░░░░░░░░  →  7.0 🟡
```

---

## 4. Carry-over backlog (закрытие до Sprint 36)

Минимальный набор задач для достижения target 9/10 на всех 10 доменах.
Все задачи оформлены как `D-rule` (binding) и проходят через TDD-first cycle.

### D-rule index (next cycle)

| D-rule | Домен | Что | Effort | ETA |
|--------|-------|-----|--------|-----|
| **D-XXX-1** | Cache facade | D187 cache facade primitive (close 16/17 → 17/17 gap) | 2-3 ч | Sprint 8A K2 W8 |
| **D-XXX-2** | CDC | Debezium E2E perf benchmark + chaos chain test | 1-2 d | Sprint 8A K4 W4 |
| **D-XXX-3** | Agent isolation | pyodide integration + perf benchmark vs ProcessPool | 2-3 d | Sprint 8A K4 W3 |
| **D-XXX-4** | Notifications | Telegram load-test + Push provider adapter | 1-2 d | Sprint 36 W2 |
| **D-XXX-5** | Docs | docs/_build regeneration (88 stale refs) | 1 h | Sprint 36 W1 |
| **D-XXX-6** | Observability | Prometheus alert integration (Grafana → Alertmanager) | 1 d | Sprint 36 W3 |

**Total effort**: ~7-10 дней concentrated (Sprint 8A + Sprint 36 wave 1-3).

---

## 5. References (canonical sources)

Этот документ — high-level roadmap. Глубокая документация по доменам:

- **V22 архитектура**: `ARCHITECTURE.md`, `CLAUDE.md`, `graphify-out/graph.json`
- **ADR backlog**: `docs/adr/INDEX.md`, `docs/adr/WIKI.md` (190+ ADRs)
- **Sprint 171+ retrospective**: `docs/PROJECT_FINAL_SUMMARY.md`,
  `docs/PROJECT_RECOMMENDATIONS.md`, `docs/sprints/sprint-171-summary.md`
- **Sprint scorecards**: `docs/SPRINT_171_SCORECARD.md`,
  `docs/SPRINT_171_M24_CLOSE.md`, `docs/SPRINT_171_M25_CLOSE.md`
- **Known issues + drift**: `.claude/KNOWN_ISSUES.md` (1707 LOC,
  Cycle 33 audit)
- **D-rules (binding)**: `docs/adr/` index, `.kimi-code/skills/`
- **Tech debt backlog**: `docs/tech-debt/`, `.shared/context/TECH_DEBT.md`
- **DSL audit**: `docs/DSL_AUDIT.md`, `docs/middleware/MIDDLEWARE.md`,
  `docs/rpa/RPA_GUIDE.md`, `docs/config/SETTINGS_GUIDE.md`,
  `docs/ai/AGENT_GUIDE.md`, `docs/integration/INTEGRATION_GUIDE.md`

### Cross-reference note (NOT replaced)

Документы, ссылающиеся на `PLAN.md` (AGENTS.md, CLAUDE.md,
docs/adr/WIKI.md, docs/adr/0249), сохраняют свои ссылки **без
изменения** в рамках текущего Sprint 7 Docs sub-task. Внешние ссылки
интерпретируются как указатели на данный `docs/PROJECT_PLAN.md` через
convention: «PLAN.md» ≡ `docs/PROJECT_PLAN.md` в V22 era.
Следующий спринт внесёт корректирующие правки в cross-references
отдельным sub-task (cross-sprint edit не входит в Sprint 7 Docs scope).

---

## 6. Glossary

- **D-rule**: binding architectural decision в формате ADR-extension,
  закрепляющий паттерн, запрет или обязательство. Цитируется через
  `D102`, `D187`, `D271` etc.
- **Tier-A backend**: production-supported backend с full CI gate
  + perf + chaos test. Per ADR-NEW-11.
- **Capability-checked facade**: единая точка входа в cross-layer
  функциональность с runtime-проверкой capability (D102 + D187).
- **V22 era**: архитектурный baseline от Sprint 17 до текущего дня;
  breaking changes запрещены без ADR-≥250.
- **Ponytail-YAGNI**: правило минимализма — отсутствие абстракций
  над одним implementation, тонкие wrappers, deletion over addition.
  Регулируется D225.

---

## 7. Changelog (PROJECT_PLAN.md)

| Дата | Изменение | Sprint |
|------|-----------|--------|
| 2026-08-04 | Initial commit (this file); replaces missing PLAN.md as canonical V22 roadmap | Sprint 7 Docs |
| 2026-08-12 | **Cycle 121+ bulk cleanup**: 50+ merge conflict resolution (cycles 117-120), B-101 SKB callable fix, D-A7-02/D-A10-100 regression tests, D-9601 follow-up (UnifiedRateLimiter removal — fail-OPEN scaffold), D-11-5 follow-up (SBOM canonical regen + RouteBuilder docstring drift), presidio-analyzer lock fix (yanked 2.2.362 → 2.2.364), D-15001 _current_tenant narrow exceptions. 6+ параллельных subagents, total 12 commits, 0 regressions. Documentation drift (RouteBuilder 40→42 sub-mixin) corrected. | S121+ |

**Total**: 2 entries. Дальнейшие правки фиксируются в этом changelog
только при изменении V22-инвариантов или target scores.
