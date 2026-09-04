# Production Readiness — FINAL Plan (M1 → M6)

> **Generated**: 2026-09-02 (Sprint 60+).
> **Source of truth**: `docs/roadmap/BASELINE_2026-09-02.md` (machine-verified).
> **Predecessor**: `docs/roadmap/PRODUCTION_READINESS.md` (M1-M4 partial, 22 P0 closed, M2 13/16, M3 STOPPED, M4 baseline 30.8%).
> **Scope**: финальный конечный план от текущего состояния до production-ready. После M6 план ЗАКРЫТ — новые находки идут в отдельный backlog.
> **Constraint**: zero new protocols / frameworks / patterns вне M1-M6.

---

## 0. Текущее состояние (baseline S60+, reverified 2026-09-02)

| Метрика | Значение | Verification |
|---|---|---|
| Ruff errors | **6** (3 auto-fixable) | `ruff check src/` |
| Bandit HIGH (severity) | **0** | `bandit -r src/ -lll` |
| Bandit HIGH (confidence) | **43** (NE disclosed) | same |
| Vulture @≥90% | **0 findings** (S50 Sprint C closed FP) | `vulture src/` |
| Layer allowlist | **37 legacy, 0 new** | `check_layers.py` |
| Tests collected | **16243** (was 15862) | `pytest --collect-only` |
| Coverage gate | 60% (baseline 30.8% — FAIL) | `pyproject.toml:fail_under` |
| Pre-prod-check gates | 38 | `tools/checks/pre_prod_check.py` |
| CVE-affected deps | **2 packages** (cryptography, diskcache) | `uv run pip-audit` |
| Velocity (2 weeks) | 683 commits (~49/day) | `git log` |
| **M1 P0** | **✅ 22/22 CLOSED** (S49 W11) | commit `57a396d84` |
| **M2 god-objects** | **15/16 (94%) — CORRECTED 2026-09-02** | Sprint 64 retro `fea658052` (was 13/16 at plan write) |
| **M3 deps** | **STOPPED at Sprint 53** | `SPRINT_53_PLAN.md` |
| **M4 coverage** | **baseline 30.8%** | Sprint 59 retro |
| **M5 high-load hardening** | **NOT STARTED** | (new in this plan) |
| **M6 final verification** | **NOT STARTED** | (new in this plan) |

---

## M1 — Security P0 zero-out ✅ DONE (S49)

**Status**: 22/22 P0 closed (Sprint 49, commit `57a396d84`).
**Done-критерий**: `grep -rn 'P0 open' docs/STATUS.md` → пусто. ✅ Met.
**Retro**: `docs/retros/SPRINT_59_COMPLETE_RETRO_2026-08-25.md`.

**No further action** in this FINAL plan — M1 is in the operational record only.

---

## Pre-Sprint Checklist (mandatory, per user directive)

**Standing rule** (user directive 2026-09-02): "перед началом спринта всегда проверяй наличие незакрытых задач с прошлых и реализуй, после - переходи к реализации спринта".

**Before starting ANY sprint**, the executor MUST:

1. **Enumerate unclosed carryover**:
   ```bash
   git log --oneline --since="<last_sprint_end>" | grep -E "M[0-9]-#[0-9]+" | head -20
   # Identify tasks mentioned but not completed
   ls docs/retros/SPRINT_<N>_COMPLETE_RETRO_*.md | tail -1
   cat $(ls docs/retros/SPRINT_<N>_COMPLETE_RETRO_*.md | tail -1) | grep -E "Out of scope|Deferred to"
   ```
2. **Prioritize**: unclosed P0/P1 from previous sprints OVER any new sprint task.
3. **Implement** unclosed tasks first, atomic commits per task.
4. **Verify** each unclosed task is closed before picking up new sprint work.
5. **Document** in sprint retro: "Carryover from <previous sprint>: N items, M closed, K remaining."
6. **Only then** proceed to current sprint implementation.

**Known carryover at start of M2 sub-sprint 1** (2026-09-02 snapshot):

| ID | Origin | Status | Action |
|---|---|---|---|
| M2-#1 (continuation) | S61-S64 partial | 4/13 methods extracted | Continue mixin split (~4-6h) |
| M2-#16 RouteBuilder Protocol | Original M2 | 2/41 mixins migrated | Migrate 39 remaining (~8h) |
| M2-#11 sample 7/10 | S60 | 3/10 done | Migrate 7 remaining (~3h) |
| M3-#2 tornado bump | Sprint 53 plan | Plan exists, not executed | `uv lock --upgrade-package tornado` (~10 min) |
| M3-#3 pypdf bump | Sprint 53 plan | Plan exists, not executed | `uv lock --upgrade-package pypdf` (~50 min) |
| M3-#4 cryptography ADR-0288 | Sprint 53 plan | ADR required | Write ADR + bump (~4h) |

**Sprint 65 starter plan** (Post-Plan A, per directive):
- Step 1 (CARRYOVER FIRST): Close M3-#2 (tornado), M3-#3 (pypdf) — ~1h total
- Step 2 (CARRYOVER): M2-#1 mixin split — close remaining 9 methods — ~4-6h
- Step 3 (NEW): M2 swarm findings M2-#18 (Express dead-code) — ~3h
- Step 4 (NEW): Continue from M2-#19...#23 per swarm synthesis

---

## M2 — God-объекты + custom→library migration (94% → 100%) + swarm findings

**Goal**: M2-#1 (final 9 methods) + M2-#16 (RouteBuilder 39 remaining) + swarm findings (Шаг 1, 2026-09-02).
**Baseline**: **15/16 (94%) — Sprint 64 retro `fea658052`** (NOT 13/16 as originally cited; corrected post-baseline reverification).
**Estimate**: ~78h (swarm-enriched backlog: 13 P0/P1 tasks).

### M2 remaining (post-Sprint 64 + swarm)

| ID | Домен | Задача | Source | Risk | Hours |
|---|---|---|---|---|---|
| M2-#1 (continuation) | Core | `AuthFacade` mixin split — final 9 methods (Sprint 64 left 4/13 done). Mixin candidates: AuthSessionMixin, AuthCredentialsMixin, or method-grouped (refresh/revoke/logout) | Sprint 64 retro | HIGH — inter-method state | 4-6h |
| M2-#16 | DSL | `RouteBuilder` Protocol migration 2/41 → 41/41 (39 remaining mixins) | Sprint 64 retro | MEDIUM — MRO fragility | 8h |
| M2-#11 sample 7/10 | DSL | `redis_client` inline imports → DI provider (7 sites remaining from S60 partial) | Sprint 60 retro | LOW — pattern reuse | 3h |
| M2-#17 | Services | audit_service DI provider cleanup (inline imports в 8 файлов) | Sprint 62 | LOW — pattern reuse | 4h |
| **M2-#18** | Services | Express dialog/session store dead-code cleanup — 11 unused vars across 2 files | **swarm** | LOW | 3h |
| **M2-#19** | DSL | DSL transactional EIP dead imports cleanup (OutboxBackend/OutboxEvent, 90% conf) | **swarm** | LOW | 0.5h |
| **M2-#20** | DSL | **DSL → infrastructure inline imports batch migration** — **REGRESSION**: 83 → 153 since Aug 31, +70 net | **swarm** | MEDIUM — pattern reuse | 6h |
| **M2-#21** | DSL | **NEW P0**: `dsl/builders/base/__init__.py` — **1422 LOC, 175 methods** — largest god-object in repo (бывший `agent_security.py` был 652 LOC; это ×2.2). Split в ~4-6 модулей | **swarm** | HIGH — core DSL surface | 16h |
| **M2-#22** | Infra | `s3_pool/client.py` god-object split (609 LOC, 25 methods) | **swarm** | MEDIUM | 6h |
| **M2-#23** | Mixed | 12 additional god-objects >400 LOC, >15 methods (services/ops/health.py 604, services/ai/agent_sandbox.py 601, dsl/builders/infrastructure_dsl.py 572, dsl/orchestration/triggers.py 543, infrastructure/storage/s3.py 517, dsl/builders/control_flow.py 508, dsl/engine/processors/rpa_browser.py 508, services/workflows/hitl_service.py 507, services/authorization/facade.py 490, infrastructure/repositories/base/sqlalchemy.py 476, infrastructure/security/token_registry.py 470, plugins/composition/app_factory.py 465, infrastructure/clients/external/express_bot.py 464) | **swarm** | MEDIUM — can parallelize | 24h (~2h each) |
| **M2-#24** | Mixed | Vulture FP triage batch — Protocol params, `__exit__` args, test scaffold args. ~25 findings to add `# noqa: ARG001` | **swarm** | LOW | 2h |
| **M2-#25** | Tests | Fix SyntaxWarnings в 10 docstrings (escape sequences in raw strings) | **swarm** | LOW | 0.5h |
| **M2-#26** | Frontend | Streamlit forms/pages unused params cleanup (3 findings) | **swarm** | LOW | 0.5h |

### M2 sub-sprint decomposition

Sub-sprint 1 (~24h): M2-#18, M2-#19, M2-#20, M2-#24, M2-#25, M2-#26 (low-risk cleanup)
Sub-sprint 2 (~16h): M2-#21 (NEW P0 — DSL builder base split)
Sub-sprint 3 (~12h): M2-#1 + M2-#16 + M2-#17 (Sprint 62 partial)
Sub-sprint 4 (~30h): M2-#22 + M2-#23 (god-objects, can be parallelized across worktrees)

**Deferral candidates** (explicit, with reason):

- `agent_security.py` god-object — DONE S187 (5/5 closed, R12) — **EXCLUDED**.
- `orchestrator_mixin.py` 466 LOC → PipelineStep — **DEFERRED**: requires inter-cycle state machine redesign (M2-#2 risk MEDIUM, no automated tooling possible). Tracking reference only.
- `gateway_orchestrator_mixin.py` — **DEFERRED**: S50 M2-#6 tracking reference committed, no path to safe split without breaking 11 dependent entrypoints.
- `services/ai/agents_pydantic/adapter.py` unused pydantic_ai params — **DEFERRED**: waiting for pydantic_ai API stabilization (4 vars unused, likely transient).

### M2 Done-критерий

```bash
grep -rn "god-object" docs/retros/ | grep -v DONE
# Expected: пусто (or only explicit deferral markers)

python3 -m ruff check src/
# Expected: 0 errors

python3 -m vulture src/ --min-confidence 70
# Expected: ≤ 5 findings (only explicit deferral + Protocol/abstract contract params)

grep -rn "from src.backend.infrastructure" src/backend/dsl/engine/processors/ | wc -l
# Expected: ≤ 50 (down from 153; M2-#20 partial closure)

# M2-#21 critical check
wc -l src/backend/dsl/builders/base/__init__.py
# Expected: ≤ 400 (from 1422 — split into multiple files)
```

---

## M3 — Dependency CVE upgrade (STOPPED → DONE)

**Goal**: закрыть 2 CVE-affected пакета (cryptography + diskcache) + закрыть unstarted tornado + pypdf из Sprint 53 plan.
**Estimate**: ~10h (~60 min per Sprint 53 plan + ADR + cryptography bump).

### M3 tasks

| ID | Домен | Задача | Risk | Hours |
|---|---|---|---|---|
| M3-#1 | Infra | **M3-AUDIT**: `uv run pip-audit` final reverification | LOW | 0.5h |
| M3-#2 | Infra | tornado 6.5.7 → 6.5.8 (per Sprint 53 plan §S53-T2) — LOW risk, no Tornado surface in production | LOW | 0.5h |
| M3-#3 | Infra | pypdf 6.14.2 → 6.16.1 (per Sprint 53 plan §S53-PDF) — LOW risk, 4-layer defense-in-depth verified | LOW | 1h |
| M3-#4 | Infra | cryptography ADR-0288: upper-bound lift `cryptography<50.0.0` → `<51.0.0` (per Sprint 53 plan §ADR-0288) | MEDIUM | 4h |
| M3-#5 | Infra | cryptography 49.0.0 → 50.0.0+ bump + full SSL test path (`make test`) | MEDIUM | 4h |
| M3-#6 | Infra | diskcache deferral confirmation (ADR-0287 already exists, no fix upstream) | N/A | 0.1h |

### M3 Done-критерий

```bash
uv run pip-audit --vulnerability-service osv
# Expected: 0 vulnerabilities (или только diskcache, явно pinned via ADR-0287)

git log --oneline --grep="M3" --since="2026-09-02"
# Expected: ≥6 atomic commits (ADR + 3 upgrades + 2 verification commits)
```

---

## M4 — Coverage 30.8% → 70% gate (приоритет — критичные пути)

**Goal**: coverage gate FAIL → PASS. **Tаргет**: 70% (НЕ 100% — анти-оверинжиниринг per AGENTS.md).
**Constraint**: gate фиксируется в `pyproject.toml:fail_under = 70` и больше не повышается в рамках этого плана.
**Estimate**: ~32h.

### M4 tasks (priority-ordered)

| ID | Домен | Задача | Hours |
|---|---|---|---|
| M4-#1 | Tests | Baseline re-measurement: `coverage run --source=src/backend -m pytest tests/unit/ && coverage report` (полный проект) | 2h |
| M4-#2 | Tests | Per-layer breakdown: `python3 tools/coverage/breakdown_by_layer.py coverage.xml` (Sprint 16 DoD-10) | 2h |
| M4-#3 | Tests | Workflow infrastructure ratchet (current ~47%) → 65% (workflow_registry уже 100%, focus на temporal client + LiteTemporalBackend) | 8h |
| M4-#4 | Tests | Entrypoints ratchet (current ~29%) → 60% (REST/SOAP/GraphQL/WS/SSE/MCP/MQTT handlers) | 8h |
| M4-#5 | Tests | DSL processors ratchet (current ~60%) → 75% (focus на unpcovered edge cases — NOT facade __init__ modules, которые уже 100%) | 8h |
| M4-#6 | Tests | Critical-path: auth (jwt/saml/mobile_jwt/api_key), DSL dispatch, payment/order flow → 85% | 4h |
| M4-#7 | Tests | `pyproject.toml:fail_under 60 → 70` (один раз, финальный) | 0.1h |

### M4 Done-критерий

```bash
coverage run --source=src/backend -m pytest tests/unit/ -q && coverage report
# Expected: TOTAL ≥ 70% (verify по `coverage report` final line)

grep "fail_under" pyproject.toml
# Expected: fail_under = 70

make pre-prod-check
# Expected: coverage gate (gate #?) exit 0
```

**Anti-оверинжиниринг**: НЕ добавлять тесты на facade `__init__.py` (61 уже at 100% — дополнительные тесты = overhead без value). НЕ добавлять тесты на pure-re-export modules (type identity tests достаточно, покрыты в Sprint 48 W15-W39). Focus на критичные пути.

---

## M5 — High-load hardening (best practices, NEW)

**Goal**: чеклист из 8 пунктов ЗАКРЫТ и верифицирован нагрузочным тестом.
**Source**: best practices высоконагруженных платформ (High Scalability, AWS Architecture Blog, Google SRE book).
**Constraint**: каждый пункт — конкретный finite task, не "продолжать улучшать".
**Estimate**: ~24h.

### M5 checklist (8 finite tasks)

| # | Пункт | Verification | Hours |
|---|---|---|---|
| M5-#1 | **Connection pool лимиты** (DB/Redis/HTTP): явные лимиты в конфиге, не default. `pyproject.toml` или `core/config/services/connection_pools.py` | `grep -rn "pool_size\|max_connections" src/backend/infrastructure/` → все default заменены на explicit. Load test: 500 RPS sustained 60s, pool exhaustion < 1%. | 4h |
| M5-#2 | **Graceful shutdown** (drain in-flight requests) на всех entrypoints (REST/SOAP/GraphQL/WS/SSE/MCP). FastAPI lifespan + aiohttp `shutdown_timeout` + WebSocket close_handshake | `kill -SIGTERM` на running app → in-flight requests complete, новые → 503, lifespan cleanup runs | 4h |
| M5-#3 | **Circuit breaker + rate limiter — библиотечные** (см. M2 deferral). Уже есть `purgatory` per S50 M2-#14 verification, `slowapi` alternative `slowapi`/built-in per S51 M2-#15 | `pip show purgatory slowapi tenacity` → installed. Custom implementations → migrated or explicit deferral ADR | 1h (mostly verification) |
| M5-#4 | **Backpressure на очередях** (RabbitMQ/Kafka/Redis Streams): явные prefetch/batch лимиты, не infinite | `grep -rn "prefetch_count\|batch_size" src/backend/infrastructure/messaging/` → all explicit | 3h |
| M5-#5 | **Idempotency-ключи** на critical write-путях (orders, saga steps, payment). `Idempotency-Key` header middleware + Redis-backed dedup | cURL same Idempotency-Key × 3 → 1 эффект (1st 200, 2nd-3rd cached 200 or 409 per RFC) | 4h |
| M5-#6 | **Timeout-ы на каждом внешнем вызове** (HTTP/gRPC/DB): явные `timeout=` параметры, без "no timeout" мест | `grep -rn "httpx\.\(get\|post\)\|aiohttp\.\(get\|post\)" src/backend/ -A2` → 100% have timeout= | 3h |
| M5-#7 | **Structured logging + correlation ID** сквозно (уже частично есть per S47 W6 — verify coverage). `correlation_id` middleware → propagates в headers + logs + DB queries | `X-Correlation-ID` header in → request log → DB query log → response header (all carry same UUID) | 3h |
| M5-#8 | **Health-check/readiness-probe корректно отражают реальную готовность**. `/health` liveness (process alive) vs `/ready` readiness (DB+Redis+MQ connected). НЕ "200 OK always" | Kill Redis → `/ready` returns 503 within 5s; restart Redis → `/ready` returns 200 within 30s | 2h |
| **M5-#9** | **NEW (swarm finding)**: Auth middleware coverage — 12/16 entrypoints reference `auth_middleware` (75%). Missing: `cdc/`, `filewatcher/`, `scheduler/`, `email/`. Verify which actually need app auth (CDC may be internal-only, scheduler cron-triggered, email uses IMAP creds, filewatcher uses service account) | Per-protocol decision matrix in `docs/security/AUTH_PROTOCOL_MATRIX.md`; `grep -rln "AuthMiddleware" src/backend/entrypoints/ | wc -l` ≥ 14 (was 12) | 4h |

### M5 Done-критерий

```bash
# Pre-load-test checks
grep -rn "TODO\|FIXME\|XXX" src/backend/infrastructure/ src/backend/entrypoints/
# Expected: 0 critical (info-level OK)

# Load test (locust или k6)
locust -f tests/load/locustfile.py --headless --users 100 --spawn-rate 10 --run-time 5m \
       --host http://localhost:8000
# Expected: p99 latency < 300ms on 3 key endpoints (REST /health, /api/v1/admin/users, /api/v1/orders)
# Expected: 0 unhandled exceptions
# Expected: 0 circuit breaker trips (or only intentional test trips)
```

**Pre-agreed SLO targets** (зафиксировать перед M5-S1, согласовать с пользователем):
- Sustained RPS: **500** (per user prompt)
- p99 latency: **< 300ms** on REST/GraphQL/SSE entrypoints
- Error rate: **< 0.1%** during sustained load
- Circuit breaker cold-start: **OK** (no false trips during warmup)

---

## M6 — Final verification (последний, безусловно конечный)

**Goal**: pre-prod-check exit 0 + функциональная верификация всех протоколов + final STATUS sync.
**Source**: user prompt §M6 + AGENTS.md completion rules.
**Estimate**: ~8h.

### M6 tasks (strictly sequential)

| # | Задача | Verification | Hours |
|---|---|---|---|
| M6-#1 | `make pre-prod-check` → exit 0 (all 38 gates) | Command output: zero FAIL lines | 1h |
| M6-#2 | `make lint-strict && make type-check-strict && make test` → all exit 0 | Three commands, three exit 0 | 2h |
| M6-#3 | Functional cURL: все 17 протоколов минимум по 1 сценарию (REST + auth, SOAP + WSDL, GraphQL query, gRPC reflection, WS handshake, SSE event, MCP tool call, MQTT subscribe, AsyncAPI spec, CDC event, email IMAP, filewatcher event, scheduler cron, webhooks inbound, ETL pipeline, MQ publish, HTTP/3) | 17 cURL-equivalent команды, 17 успешных responses | 2h |
| M6-#4 | Browser verification: Swagger UI loads, GraphQL Playground loads, Streamlit portal loads (3 URL checks) | `curl -fsS http://localhost:8000/docs` → 200; same for `/graphql` and Streamlit | 1h |
| M6-#5 | Load test (M5 locust/k6) final run + write results to `docs/roadmap/LOAD_TEST_RESULTS_<дата>.md` | Final p99 / RPS / error rate documented | 1h |
| M6-#6 | Final `docs/STATUS.md` sync с verified метриками (machine-checked output). Зафиксировать: "план доработки завершён, дальнейшие изменения — только по новым бизнес-требованиям, не по этому плану" | STATUS.md §TL;DR reflects M1-M6 closure | 0.5h |
| M6-#7 | `docs/roadmap/PRODUCTION_READINESS_FINAL.md` (этот файл) — bump status `in-progress` → `closed`; append final report section with verification summary | Document status field | 0.5h |

### M6 Done-критерий

```bash
# Single command (script-style)
make pre-prod-check && \
  (make lint-strict && make type-check-strict && make test) && \
  (curl -fsS http://localhost:8000/health && \
   curl -fsS http://localhost:8000/docs && \
   curl -fsS http://localhost:8000/graphql && \
   curl -fsS http://localhost:8501) && \
  echo "M6 CLOSED"
# Expected: "M6 CLOSED" printed

cat docs/roadmap/PRODUCTION_READINESS_FINAL.md | grep "^status:"
# Expected: status: closed

cat docs/STATUS.md | grep "План доработки"
# Expected: явное закрытие ("План доработки завершён")
```

**Hard constraint** (anti-оверинжиниринг):
- После M6 план **ЗАКРЫТ по scope**. Любые новые находки после этого момента идут в **отдельный backlog "Sprint N+1 (пост-план)"**, НЕ расширяют текущий план задним числом.
- Coverage gate = 70%, **фиксируется**. Повышение > 70% — отдельный backlog.
- Не добавлять новые протоколы/фреймворки/паттерны вне M1-M6.

---

## Cross-references

- BASELINE (source of truth): `docs/roadmap/BASELINE_2026-09-02.md`
- **ШАГ 1 swarm synthesis** (10-domain scan, 2026-09-02): `docs/roadmap/SWARM_SYNTHESIS_2026-09-02.md`
- Operational record M1-M4 partial: `docs/roadmap/PRODUCTION_READINESS.md`
- M3 execution plan: `docs/roadmap/SPRINT_53_PLAN.md`
- M3 audit: `docs/roadmap/M3_AUDIT_2026-09-01.md`
- STATUS: `docs/STATUS.md` (sync deferred to M6-#6)
- Pre-prod check: `tools/checks/pre_prod_check.py` (38 gates)
- Working tree WIP (NOT mine, do not touch): 7 files modified per `git status -uno` (auth/facade.py was committed by other session mid-session)

---

## ШАГ 3 — Sprint execution protocol (для будущих исполнителей)

План составлен в режиме **"Только финальный план"** (пользовательский выбор). Само исполнение спринтов будет делаться в последующих сессиях. Когда исполнитель берёт любой M-sprint, **обязательный протокол** (per user prompt §ШАГ 3):

После каждого спринта — **3 отдельных агента**:

1. **Агент-ревьюер**: построчный code review всех diff'ов спринта против чеклиста чистой архитектуры (слои, DI, отсутствие god-объектов, отсутствие новых кастомных реализаций там, где есть библиотека).
2. **Агент-ретроспективист**: собирает метрики до/после (только verified командами), фиксирует false claims, документирует отклонённые изменения.
3. **Агент-аналитик следующего спринта**: пересчитывает backlog, подтверждает, что план по-прежнему конечен.

**Все три отчёта** — в `docs/retros/SPRINT_<N>_REVIEW.md`, `SPRINT_<N>_RETRO.md`, `SPRINT_<N>_NEXT_ANALYSIS.md`.

**Hard rules для исполнителя**:
- Не делать git push (запрет AGENTS.md).
- Не редактировать lockfile без явного согласования.
- Атомарные коммиты (conventional prefix: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`).
- Каждый sprint = один M-милстоун или его логическая часть при объёме >40h.

---

## Plan metadata

- **Total estimate**: M2 (78h, swarm-enriched) + M3 (10h) + M4 (32h) + M5 (28h, +4h for M5-#9) + M6 (8h) = **~156h** (~19-20 рабочих дней при 8h/день).
- **Sprint mapping** (suggested):
  - Sprint 61-63: M2 sub-sprint 1 (cleanup batch, ~24h)
  - Sprint 64-66: M2 sub-sprint 2 (M2-#21 NEW P0 DSL builder base split, ~16h)
  - Sprint 67-68: M2 sub-sprints 3+4 (~42h, can use parallel worktrees)
  - Sprint 69-70: M3 dependency upgrade
  - Sprint 71-74: M4 coverage ratchet
  - Sprint 75-78: M5 high-load hardening (incl. M5-#9 auth coverage)
  - Sprint 79: M6 final verification + closure
- **Risk**:
  - M2-#21 (DSL builder base 1422 LOC split) — HIGH, core DSL surface, requires careful inter-module state preservation
  - M5-#2 (graceful shutdown) — HIGH, requires careful lifespan refactor across 16 entrypoint types
  - M2-#20 (layer violation regression) — MEDIUM, signal of architectural drift
- **Hard stops**: pip install / force-push / secrets in logs / `rm -rf` (per AGENTS.md).
- **Шаг 1 source**: `docs/roadmap/SWARM_SYNTHESIS_2026-09-02.md` (10-domain parallel scan, 2026-09-02).

---

## Status

- **status**: designed (in-progress at M2 → M6; closed at M6-#7)

---

## Report

(empty — final state filled at M6-#7)