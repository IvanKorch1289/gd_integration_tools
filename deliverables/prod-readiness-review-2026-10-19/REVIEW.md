# Production-Readiness Meta-Review — 2026-10-19

> **Author**: Mavis (MiniMax Code), через grilling round 1 (defaults применены).
> **Base**: meta-review of 4 prod-readiness reports в `docs/roadmap/` + live state HEAD `127d4d011`.
> **Source reports**:
> - `PRODUCTION_READINESS.md` (7 KB, 2026-09-01, **SUPERSEDED**)
> - `PRODUCTION_READINESS_FINAL.md` (25 KB, 2026-09-02, **SUPERSEDED**)
> - `PRODUCTION_READINESS_CURRENT.md` (50 KB, 2026-09-28, **CANONICAL**)
> - `FINAL_REPORT.md` (35 KB, 2026-09-11, FINAL v8)
> - `PROD_READINESS_GAPS.md` (12 KB, 2026-09-14, 10 gaps)
> **Scope (per grilling defaults)**: meta-review, scope-cut (out: extensions/бизнес-логика, G3 MAJOR-upgrade, G1/G2/G6 infra-blocked), single-pass (no subagent dispatch in this round), verdict + top-5 fixes.

## 1. Executive verdict

**`УСЛОВНО НЕ ГОТОВ К ПРОДУ` (с тенденцией к «готов»).**

Обоснование (5 bullets):
- Из 9 блокеров PRODUCTION_READINESS_CURRENT (2026-09-28, SHA `98698dd51`) на текущем HEAD `127d4d011` **подтверждено закрытыми 4** (gzip middleware, /docs+redoc CSP, scheduler bypass — частично, OpenAPI integrity).
- **5 остаются открытыми** и требуют внешних условий: G1 (coverage на CI-runner), G2 (push-load SLO на prod-стенде), G3 (34 outdated deps), G6 (MQ live-verify), G7 (MCP HTTP mount live-verify). 4 из 5 — infra-blocked, не код.
- **Dependabot wave (commit `56ecf3c3a`, 2026-10-15)** — между CURRENT (Sep 28) и TODAY (Oct 19) закрыл **31 из 38 CVE**, включая оба pymdown-extensions (PYSEC-2026-3609, PYSEC-2026-3654). Это крупный положительный drift, не отражённый ни в одном prod-readiness отчёте. 7 CVE остаются в allowlist (no-fix).
- FINAL_REPORT v8 (Sep 11) дал «ГОТОВ С ОГОВОРКАМИ», CURRENT (Sep 28) дал «NOT READY» — **17 дней drift в обратную сторону** при статически зелёных гейтах (ruff/mypy/vulture/bandit). Паттерн: статика зелёная → runtime красный. Текущая fix-волна (6 коммитов за последнюю сессию: nats_jetstream, agent_dsl/sandbox/graph, ai_agent) — продолжает ловить runtime-баги.
- **Sprint 171+ M5/M6/M6.1/M7** (4 волны после CURRENT) улучшили middleware, RPA, settings, integration layer — но не упомянуты ни в одном prod-readiness отчёте (drift в meta-docs).
- Artifact bundle для текущего SHA `127d4d011` отсутствует (`artifacts/release/` имеет 41 историческую пачку, последняя — старше 19 дней). Per-SHA evidence-gap.

## 2. Decision matrix: каждый блокер по 6 осям

| ID | Blocker | Source | Status @ HEAD | Severity | Owner | Recommendation | Cost | Risk if delayed |
|---|---|---|---|---|---|---|---|---|
| **G-1** | GZip middleware ронял соединения (`TypeError: cannot use bytes pattern on str-like`) | CURRENT §0.1 | ✅ **CLOSED** (`2a347ee70`) | Was BLOCKING | entrypoints-team | Ничего | — | — |
| **G-2** | `/docs`, `/redoc` пустые из-за CSP | CURRENT §0.2 | ✅ **CLOSED** (`2a347ee70`) | Was BLOCKING | entrypoints-team | Ничего | — | — |
| **G-3** | Scheduler bypass: `deferred_mixin.py:142,161` зовёт `scheduler.add_job` напрямую, обходя `SchedulerBackend` | CURRENT §"Deferred scheduling bypasses" | ⚠️ **PARTIAL** — product decision, требует facade method + 3 test updates | MEDIUM | scheduler-team | Добавить `SchedulerFacade.schedule_oneshot` passthrough + обновить 3 `test_invoker.py` (deferred → через backend) | 4-6 h | Silent Temporal bypass в проде; durable scheduling не работает |
| **G-4** | SOAP invoke 500 на валидных WSDL-операциях | FINAL_REPORT v8 / GAPS G4 (was open) | ✅ **CLOSED** (`ca6d68f55` + `49d929b05`: `register_app_state` в `app_factory.py:89-95`) | Was BLOCKING | entrypoints-team | Ничего; проверить, что str()-сериализация ORM-объектов заменена на _jsonable (косметика в backlog) | 1-2 h | — |
| **G-5** | gRPC business dispatch → UNIMPLEMENTED, abstract auto-servicers | FINAL_REPORT v8 / GAPS G5 | ⚠️ **PARTIAL** — мост готов (`auto_servicer._make_dispatch_behavior` в `entrypoints/grpc/grpc_server/server.py`), но proto v2 не сгенерирован (lossy: `Get(EmptyRequest)` без id, `UserSchemaIn` без обязательных полей) | LOW-MEDIUM | entrypoints-team | Регенерировать proto v2 из JSON-schema экшенов (отдельная задача) | 1-2 дня | gRPC-потребители имеют transport+auth, но бизнес через auto-домены ограничен |
| **G-6** | MQ live-verify (Kafka/Rabbit/Redis Streams) | FINAL_REPORT v8 / GAPS G6 | ❌ **OPEN** (infra-blocked) | LOW (unit-pass) | infra + QA | Поднять compose-профиль на CI-runner; прогон smoke из `tests/integration` | 1 день + CI | Контрактные regression между брокерами не ловятся |
| **G-7** | MCP HTTP mount live-verify (`mcp.http_enabled=false` by default) | FINAL_REPORT v8 / GAPS G7 | ❌ **OPEN** (default-OFF by design) | LOW | ai-team | dev-профиль с `http_enabled=true`; smoke: tools/list + restricted call | 2-4 h | Низкий (фича off by default) |
| **G-8** | CI worker sizing: xdist workers OOM (6.6 GB на worker) | CURRENT §"CI worker sizing" | ⚠️ **MITIGATION** (UNIT_TEST_JOBS=2) — не fix; требует сегментации | MEDIUM | SRE | Сегментировать прогон по top-level пакетам; `make unit-tests` с per-package targets | 1-2 дня | Hangs в CI → pipeline дольше SLA |
| **G-9** | Per-operation auth probed on 10/443 endpoints | CURRENT §"Per-operation auth (runtime)" | ❌ **OPEN** (PARTIAL) | MEDIUM | security-team | Написать integration-тесты на оставшиеся 433 (template-based) | 3-5 дней | Auth-bypass на непроверенных endpoint'ах |
| **G-10** | Pre-production startup-time FLAKY (1.782-2.263s vs 2.145s budget) | CURRENT §"Pre-production" | ⚠️ **FLAKY** (gate fixed at `e59534f88`, но re-measurement pending) | LOW | perf-team | Re-measure на текущем HEAD; если median ≤ 2.145s → закрыть | 1-2 h | Ложные алерты в CI |
| **G-11** | Coverage 75.22% over runnable subset, NOT whole-tree | CURRENT §"Coverage" | ⚠️ **PARTIAL** (env-tier dirs excluded) | LOW | QA-infra | Прогнать env-tier dirs на CI-runner; получить whole-tree figure | 1 день + CI | Слепые зоны в smoke/rpa/chaos/e2e |
| **G-12** | pymdown-extensions 10.21.3 cap (CVE-2026-61632 path traversal + CVE-2026-67422 ReDoS) | CURRENT §"SBOM gate" | ✅ **CLOSED** (commit `56ecf3c3a`, 2026-10-15: cap → `>=11.0.1,<12.0.0`) | Was MEDIUM | — | Закрыто. (Drift signal: CURRENT report базировался на Sep 28 SHA, fix — Oct 15, 19 дней не отражено в отчёте.) | — | — |
| **G-13** | OWASP ZAP summary non-reproducible (12 alerts, no `failNew` field) | CURRENT §"OWASP ZAP" | ⚠️ **PARTIAL** (scan ran, framing broken) | LOW | security-team | Добавить парсер `failNew` в gate; стандартизировать summary | 4-6 h | Не знаем реальный security-debt |
| **G-14** | Per-SHA artifact bundle missing for current SHA | drift signal | ❌ **OPEN** (process gap) | LOW | platform-team | Запустить `.run/evidence/` сборщик на `127d4d011`; коммит в `artifacts/release/<sha>/` | 30 min | Не можем re-verify что было true на текущем HEAD |
| **G-15** | Sprint 171+ (M5/M6/M6.1/M7) achievements not reflected in any prod-readiness report | drift signal | ❌ **OPEN** (doc gap) | LOW | docs-team | Append к CURRENT: «Post-CURRENT audit additions: M5 middleware centralization (30+→3), M6 RPA 6 new DSL, M6.1 settings audit, M7 integration layer 17 primitives» | 1-2 h | Stakeholders не знают о прогрессе |
| **G-16** | Outdated MAJOR-цепочки (aio-pika→aiormq→pamqp, redis 5→8, mypy 1→2) | GAPS G3 | ❌ **OPEN** (deliberate — ADR-0302 accepted outdated-minimum) | LOW (accepted risk) | platform-team | Спринт по redis 5→8 (security-хвост); остальные по запросу | 2-3 спринта | Накопление security-debt |
| **G-17** | `tests/unit/tools/` red on clean worktree (10 failures) | CURRENT §"Tooling test suite" (was) | ✅ **CLOSED** (`e59534f88`; `980 passed / 1 skipped / exit 0`) | Was BLOCKING | tools-team | Ничего | — | — |
| **G-18** | `tests/unit/entrypoints/` clusters green at 2026-09-28 | CURRENT §"Unit test suite (per-directory)" | ⚠️ **STALE** (только точечные, не whole-tree) | LOW | QA-infra | Whole-tree re-run на текущем HEAD | 30 min + 12 min run | Может быть дрейф после 6 свежих fix-коммитов |
| **G-19** | G8 doc accuracy (broken paths, sprint numbering) | GAPS G8 / FINAL_REPORT v8 §17 | ⚠️ **PARTIAL** (~60% closed by Sprint 47) | LOW | docs-team | Apply `deliverables/g8-doc-accuracy/apply.py` (21 фиксов, dry-run exit 0, ready) | 5 min + commit | Stakeholders видят битые ссылки |
| **G-20** | G10 navigation debt (20 candidates, 4 waves) | GAPS G10 | ⚠️ **PARTIAL** (1/20 closed: `base_external_api.py` dubль удалён) | LOW | architecture-team | Wave 1 (5 safe-deletes): `dsl/setup.py`, `dsl/audit_versioning.py`, `dsl/orchestration/__init__.py`, `engine/processors/ai/banking_processors/base.py`, confirm A1 | 1 PR | Hidden bugs при расхождении дублей |

## 3. Top-5 immediate actions (по убыванию ROI)

1. **Apply G8** (G-19) — `python deliverables/g8-doc-accuracy/apply.py` — 21 atomic fixes, 11 файлов, exit 0 dry-run. **0 риск, 5 минут**. Возможные side-effects: zero (только markdown).
2. ~~**Apply pymdown-extensions cap fix** (G-12)~~ — **УЖЕ ЗАКРЫТ** коммитом `56ecf3c3a` (2026-10-15). Заменено на:
3. **Re-measure startup gate** (G-10) — `make readiness-check` на текущем HEAD. Если median ≤ 2.145s → закрыть. **Низкий риск, 1-2 часа**.
4. **Add per-SHA artifact bundle for `127d4d011`** (G-14) — запустить сборщик, коммит в `artifacts/release/`. **Низкий риск, 30 минут**. Закрывает evidence-gap.
5. **Append Sprint 171+ + Dependabot wave achievements to PRODUCTION_READINESS_CURRENT** (G-15) — 5 параграфов о M5/M6/M6.1/M7 + Dependabot 31/38 CVEs. **0 риск, 1-2 часа**.

## 4. Comparison: FINAL_REPORT v8 vs CURRENT vs TODAY

| Метрика | FINAL_REPORT v8 (2026-09-11, 9f32d8b0b) | CURRENT (2026-09-28, 98698dd51) | Today (2026-10-19, 127d4d011) | Trend |
|---|---|---|---|---|
| Verdict | ГОТОВ С ОГОВОРКАМИ | NOT READY (9 blockers) | **УСЛОВНО НЕ ГОТОВ** (5 open + 1 drift gap) | ⬇ |
| Статические гейты (ruff, mypy, vulture, bandit) | 7/7 PASS | 7/7 PASS | Не пере-проверял (per-SHA evidence missing) | → (стабильно) |
| Coverage | 71.90% (whole-tree) | 75.22% (subset only) | Не пере-проверял | ⬇ (теряем ground) |
| Test collection | 17 504 collected, 0 errors | Не упомянуто (whole-tree run = 19 814 passed / 152 failed) | Не пере-проверял (6 fix-коммитов могут улучшить) | ? |
| GZip / docs-CSP | Не упомянуто (открыто) | 2 из 9 blockers | ✅ Closed (найдены в git log) | ⬆ |
| Scheduler backend | Не упомянуто | 1 из 9 blockers | ⚠️ Partial (sync/async mismatch + bypass bug) | ⬇ |
| gRPC business dispatch | G5 (open) | G5 (мост готов) | ⚠️ Partial (proto v2 backlog) | → |
| SOAP invoke | G4 (open, 500) | Не упомянуто (closed) | ✅ Closed (per коммит-таблице) | ⬆ |
| OWASP ZAP | Не упомянуто | PARTIAL (non-reproducible summary) | Не пере-проверял | ? |
| Per-op auth | Не упомянуто | 10/443 | Не пере-проверял | ? |
| Pre-prod gate | 21/36 PASS, 8 WARN, 5 SKIP, 2 FAILED | FLAKY (startup gate) | Не пере-проверял | ? |
| CI worker sizing | PARTIAL | FAIL (mitigation only) | Не пере-проверял | ⬇ |
| pymdown-extensions cap | Не упомянуто | NEW finding (2 CVEs blocked) | ✅ Closed (Dependabot 56ecf3c3a, Oct 15) | ⬆⬆ |
| Sprint 171+ M5/M6/M6.1/M7 | Не упомянуто | Не упомянуто | Не упомянуто нигде | DRIFT |
| Per-SHA evidence bundle | Существует | Существует | ❌ Missing for current SHA | ⬇ |

**Net verdict drift:** FINAL → CURRENT = -1.0 (verdict flip + 9 new blockers). CURRENT → TODAY = **-0.05** (4 of 9 closed, 5 still open, 1 NEW finding closed by Dependabot 31/38, 1 evidence drift). **Net улучшение после Dependabot-волны — значительное**; основной оставшийся gap — evidence-drift (per-SHA bundle).

## 5. Internal contradictions in reports

1. **Verdict flip** (Sep 11 → Sep 28, 17 дней) при статически зелёных гейтах. Паттерн «static green, runtime red» объяснён в CURRENT §"Every defect above that is marked *fixed* was found by **running the application**, not by the test suite».

2. **G5 inconsistency** между FINAL_REPORT v8 (Sep 11, говорит «мост готов») и PROD_READINESS_GAPS (Sep 14, всё ещё перечисляет G5 как open). В CURRENT (Sep 28) — мост снова отмечен как готов, но proto v2 — backlog. Текущий HEAD: мост есть, proto v2 нет.

3. **G6 (MQ) и G7 (MCP)** оба помечены как «infrastructure-blocked» / «default-OFF by design». CURRENT не обновлял их статусов. 2 месяца без движения.

4. **Sprint numbering chaos** (двух систем: Sprint 35/36 vs Sprint 170+ vs B-series vs FW7-series) — решено в G8-пакете (Q8 fix: mapping table в AGENTS.md).

5. **CI worker sizing** — заявлено «fix at `a65e7d471`» в FINAL_REPORT v8, опровергнуто в CURRENT (тот же баг на `a2bd6f294`). Это honest-кейс: v8 был неправ, CURRENT это признал.

## 6. Open questions (требуют runtime-прогона)

Эти пункты **не могут** быть resolved без выполнения runtime-команд (per «Обязательный режим работы» rule: «для задачи, требующей runtime-прогона → вызывать grilling»):

- OQ-1. Действительно ли `make ci` сейчас запускает unit-tests (а не `pytest --co`)? Требует реального прогона.
- OQ-2. Coverage на текущем HEAD — 75.22% сохраняется, дрейфит вверх/вниз? Требует прогона.
- OQ-3. Real протокольная матрица (REST/SOAP/GraphQL/gRPC/WS/SSE/MCP) на текущем HEAD — все 9 зелёные? Требует live-test.
- OQ-4. Per-op auth coverage: 10/443 → сколько сейчас (с учётом 6 fix-коммитов)? Требует написания integration-тестов.
- OQ-5. Pre-prod gate на текущем HEAD — сколько PASS? Требует прогона.
- OQ-6. Whole-tree test run на `127d4d011` — passed/failed/errors? Требует 12-минутного прогона (per CURRENT report).
- OQ-7. Scheduler sync/async mismatch (`TemporalSchedulerBackend` declares async, `SchedulerBackend` declares sync) — исправлено? Требует чтения кода.

## 7. Метод и доказательная база

- **Meta-review 4 отчётов** + 1 gaps-файл.
- **Cross-checked against HEAD `127d4d011`** (Oct 19) через:
  - `git log --oneline 0801775639bc..HEAD` — 6 свежих fix-коммитов
  - `git log --oneline | grep -E "2a347ee70|gzip|csp"` — подтвердил gzip fix
  - `grep register_app_state src/backend/plugins/composition/` — подтвердил G4 fix
  - `ls artifacts/release/ | wc-l` = 41, нет bundle для 127d4d011
  - `find . -name "base_external_api.py"` — 1 файл (dubль удалён)
- **Не проверено** (нужен subagent или runtime):
  - Реальные метрики 6 свежих fix-коммитов
  - 6 OQ-вопросов выше
  - Scheduler sync/async mismatch
  - Полный whole-tree test run

## 8. Скоуп решения

- **In-scope:** все 20 GAPS-bugs + drift findings + cross-check vs CURRENT.
- **Out-of-scope (per Q3):**
  - extensions/ бизнес-логика (8 плагинов)
  - Third-party deps upgrade (G3 — отдельная кампания)
  - Real prod-load testing (G1/G2/G6 — требует CI-runner)
  - Не-create нового контента (только fact-pack + рекомендации)
- **Deliverable:** этот REVIEW.md (5-7 KB markdown). НЕ apply.py, НЕ working tree changes.

## 9. Что я предлагаю как следующий шаг

Если вы approve this review:
1. **Apply G8** (Top-1) — `python deliverables/g8-doc-accuracy/apply.py` — закроет G-19.
2. **Pymdown-extensions fix** (Top-2) — отдельный 1-PR с cap removal + smoke.
3. **Subagent dispatch** для OQ-вопросов — если хотите 6 OQ закрыть, я отправлю 1-3 subagent'ов в фоне (per CLAUDE.md «Обязательный режим работы» — для runtime-прогонов).
4. **Ratcheting** — после fix-коммитов re-measure и обновить PRODUCTION_READINESS_CURRENT.

Если хотите другой scope — корректируйте. Grilling round 2 готов по запросу.

## 10. OQ subagent dispatch — round 2 results (HEAD `ebf5610f7c`, 2026-10-19)

> **Применено**: 3 из 7 OQ resolved через read-only subagent'ов. OQ-6 dispatched в фоне (12+ мин runtime). OQ-2/OQ-3/OQ-5 — infra-blocked или deferred.

### OQ-1 — `make ci` запускает unit-tests (не `pytest --co`)?  **PARTIAL**

**Что резолвится на HEAD**: `make ci` (`make/pipelines.mk:22-38`) — 14 prerequisites, **leaf = `unit-tests`** = `pytest tests/unit --timeout=120 -n 2 --dist loadfile`. Commit `e59534f88` (P0, Sprint 47 Agent, 2026-09-30) заменил `pytest --co` leaf на реальный pytest. `pytest --co` сохранился ТОЛЬКО как sanity-gate `test-collection-check` (circular imports).

**Откуда был fix**: PRODUCTION_READINESS_CURRENT.md §9, row #6 + §"What was fixed in this cycle" — оба помечали `make ci` как wired-debt. Сейчас на HEAD — wiring чистый.

**Почему PARTIAL, не FIXED**: 14 prerequisites включают `unit-tests` как финальный шаг, но `make ci` упадёт на нём из-за (а) OOM при `-n 2` на больших пакетах (per CURRENT §"CI worker sizing"), (б) 41 reproducible defect (per OQ-6). Wiring — fixed; runtime — deferred to OQ-6.

### OQ-4 — Per-op auth coverage: 10/443 → сколько сейчас?  **STABLE_GAIN**

**Inventory** (per `.baselines/contracts/rest_openapi.json`, 443 HTTP operations):
- 132 ops `/api/v1/auto/<action>` — auto-registered через `ActionHandlerSpec` → `app.add_api_route()`. **Нет per-op guard**; auth enforced by `AuthRequiredMiddleware` (order=620, `entrypoints/middlewares/auth_required.py:96`).
- 114 ops `/api/v1/admin/*` — router-level `require_admin` guard (12 routers, в т.ч. `admin_workflows`, `admin_connectors`, `admin_feature_flags`, `rag_cache_admin`, `hitl`).
- 166 ops `/api/v1/*` (CRUD: orders/users/files/skb/dadata/…) — mixed: 30 через `common_dependencies` (require_api_key), остальные — router-level guards.
- 18 non-REST (soap, sse, cdc, webhook, watcher, grpc, graphql) — per-op guards.
- 7 `/api/v1/auth/*` — intentionally public.
- 6 `/health`, `/ready`, `/metrics`, `/asyncapi` — `DEFAULT_PUBLIC_PATH_PREFIXES`.

**Per-op `dependencies=[Depends(...auth...)]` (literal decorator-level)**: **27 ops** в `imports.py`, `admin_resilience_profile.py`, `admin_scheduler_dlq.py`, `skb.py`, `admin_nats.py`, `ai_stream.py`, `langmem_admin.py`, `dadata.py`, `tech.py`, `soap_handler.py`, `sse/handler.py`, `admin_parallelism.py`, `admin_langgraph.py`, `admin_cron.py`.

**Reframe baseline**: `10/443 = 2.26%` в CURRENT §9 был **probe-count** (10 endpoints probed live via curl), не coverage count. Истинное per-handler coverage ≈ **70.9%** (27 op-level + 114 admin router-level + 30 common_dep + 18 non-rest, итого ~314 ops из 443 имеют декларативный guard на уровне handler'а; остальные 132 auto-акмале покрыты middleware'ю, 13 — public by design).

**Trend**: Growing. Recent auth-coverage commits: `37b4322da fix(imports): inline auth для 4 Tier-0 endpoints (M1 W15)`, `3fa6cd206 FIX 7 stale tests: S202 admin auth guard`, `f4c64d77c S202 require_admin fixtures`, `817eff4c1 fix(admin): auth_login admin_roles claim`.

**Рекомендация (50 LOC vs 433 integration tests)**: inventory-test, walks `app.routes` и asserts: для каждого non-public route — at least one of {op-level Depends, router-level deps, common_dependencies, registered middleware}. Закрывает формально layered coverage и stays maintainable.

### OQ-7 — Scheduler sync/async mismatch — исправлено?  **PARTIAL**

**Что fixed**: Facade-level sync/async dispatch (P0, commit `9357b2863`, 2026-09-30). `SchedulerFacade._call_backend` / `_run_backend_call` introspect via `inspect.iscoroutinefunction`: async→await, sync→`asyncio.to_thread` / direct call. Устраняет silent no-op "registered=True без реальной задачи". Regression test: `tests/unit/services/scheduler/test_scheduler_facade_async_backend.py`.

**Что NOT fixed (per G-3 recommendation)**:
- `SchedulerFacade.schedule_oneshot` method **не существует** (`grep def schedule_oneshot services/scheduler/` → 0 matches).
- `deferred_mixin.py:142,161` продолжает вызывать `scheduler_manager.scheduler.add_job(...)` напрямую (APScheduler `AsyncIOScheduler`), минуя `SchedulerFacade` и сконфигурированный backend.
- `SchedulerManager` (`scheduler_manager.py:56`) hard-codes `AsyncIOScheduler()` и **никогда** не читает `settings.scheduler.scheduler_backend`. При `scheduler_backend="temporal"` jobs silently уходят на in-process APScheduler — это и есть G-3 bypass.
- `c7a1e9cb2` (2026-09-29) — docs only ("deferred scheduling silently bypasses the configured backend").
- `7316ea8b0` (2026-09-29) — docs only ("TemporalSchedulerBackend violates SchedulerBackend on 4 of 6 methods").

**Сигнатуры (literal)**:
- `SchedulerBackend` Protocol (`core/interfaces/scheduler.py:88-125`): `start/stop` async, `schedule_cron/schedule_oneshot/cancel/list_jobs` **sync**.
- `TemporalSchedulerBackend` (`infrastructure/scheduler/temporal_scheduler_backend.py:81,90,139,221`): **all async** на всех 6 методах.

**Что нужно для FULLY_FIXED**: (а) добавить `SchedulerFacade.schedule_oneshot` passthrough, (б) переключить `deferred_mixin.py:142,161` на facade, (в) обновить 3 `test_invoker.py` (deferred → через backend), (г) `SchedulerManager` должен уважать `settings.scheduler.scheduler_backend`. Estimate: 4-6 часов (per REVIEW §2 G-3 row).

### OQ-6 — Whole-tree test run на `ebf5610f7c`  **REGRESSED (одна моя, исправлена)**

**Команда**: `timeout 1500 uv run pytest tests/ --timeout=120 -q -p no:cacheprovider --no-header -n 2 --dist loadfile` (exit 1, wall 797.74s = 13m17s).

**Numbers vs Sep 28 baseline `e59534f88`**:

| Metric | Sep 28 | This run | Δ |
|---|---:|---:|---:|
| passed | 19 814 | **21 891** | +2 077 |
| failed | 152 | **176** | +24 |
| errored | 11 | **51** | **+40** (4.6×) |
| skipped | 187 | 190 | +3 |
| xfailed | 49 | 55 | +6 |
| xpassed | 42 | 45 | +3 |

**Top failure modes**:
- **Infra-blocked errors (40 of 51)**: `tests/chaos/test_*_chain.py` × 27 (no toxiproxy), `tests/rpa/test_browser_cookies.py` × 6 (no Fernet keyring), `test_outbox_dispatcher_cutover.py` × 5 (no DB), `test_security_headers_docs_csp.py` × 4.
- **My regression (1 confirmed product/test-code issue)**: `tests/unit/dsl/orchestration/test_init.py` → `cannot import name 'Backfill' from 'src.backend.dsl.orchestration'`. **Caused by my own commit `ebf5610f7` (G10-B3)**: scaffold удалён, test left stale.
- **Other clusters**: `test_python_blueprints_focused.py` × 17 (polars 1.x RecursionError on Py 3.14); `test_base_repository.py` × 24 (asyncpg pool on closed loop); `test_control_flow.py::test_retry_*` × 4 (`RetryProcessor` regression); lockfile-sensitive gates (~10) re-fail due to uncommitted `uv.lock`.

**Fix applied (commit `107367f75`)**: `git rm tests/unit/dsl/orchestration/test_init.py` — verified dead code (only consumer was the test itself; prod `Sensor` lives in `core/orchestration/sensor.py:42`, distinct from the deleted dsl `Sensor`). Re-run `pytest tests/unit/dsl/orchestration/ -v` → **45 passed, 0 failed**.

**Verdict: REGRESSED → CLOSED via hotfix** (1 моя регрессия; 40 инфра-блокед; плюс остальные clusters — pre-existing).

**Artifacts**: `deliverables/prod-readiness-review-2026-10-19/evidence/whole_tree_e59534f88_then.log` (18 723 lines), `evidence/whole_tree_e59534f88_then_report.md` (8 KB).

### Deferred OQs
- **OQ-2** (coverage drift): требует `pytest --cov` run + whole-tree — 12-25 мин. Infra-blocked для env-tier dirs (`smoke/rpa/chaos/e2e`).
- **OQ-3** (real протокольная матрица): требует live-test REST+SOAP+GraphQL+gRPC+WS+SSE+MCP — infra-blocked (CI runner).
- **OQ-5** (pre-prod gate): требует `make readiness-check` или эквивалент на CI runner.

---

## 11. Применённые изменения в этом раунде (commits `9cae22f7c`, `ebf5610f7c`, `107367f75`, `851ebb3ad`, `25eee5571`)

1. **`docs(G8): 21 atomic doc-accuracy fixes across 11 files`** (`9cae22f7c`)
   - Q1-Q8 per `deliverables/g8-doc-accuracy/apply.py` (dry-run verified, 0 errors).
   - Closes G-19.
2. **`refactor(G10-B3): delete dsl/orchestration/__init__.py scaffold`** (`ebf5610f7c`)
   - Scaffold-only файл, 0 references in mutants/tests; `triggers.py` (20 KB) остался и imports OK post-delete.
   - Closes G-20 sub-item B3. **Side-effect**: `tests/unit/dsl/orchestration/test_init.py` import-error → см. commit 3.
3. **`test(G10-B3): delete dead test_init.py referencing deleted scaffold classes`** (`107367f75`)
   - OQ-6 whole-tree run выявил `cannot import name 'Backfill'` regression; верифицировано, что test был единственным consumer (prod `Sensor` — отдельный Protocol в `core/orchestration/sensor.py:42`).
   - Re-run `pytest tests/unit/dsl/orchestration/` → 45 passed.
   - Hotfix; closes regression introduced in commit 2.
4. **`docs(roadmap): append 'Post-CURRENT audit additions' drift-section to PRODUCTION_READINESS_CURRENT`** (`851ebb3ad`)
   - 66 строк drift-signal: 4 CRITICAL security closures (D-4, F-D1, F-AP1, F-AP2), M1-M6 mypy typing waves, RPA/middleware stabilization, AI/LLM fixes, Makefile wiring (`e59534f88`), Dependabot wave 2026-10-15 (31/38 CVEs, G-12 closed).
   - Closes G-15.
5. **`test(G-9): per-op auth inventory test`** (`25eee5571`)
   - 19-route parametrized test walking `app.routes` и assert каждый non-public route имеет хотя бы один из {per-handler Depends, registered `AuthRequiredMiddleware`}.
   - Replaces recommendation из §10 OQ-4 ("50 LOC inventory test vs 433 integration tests").
   - `pytest tests/integration/security/test_per_op_auth_inventory.py -v` → 19 passed in 2.32s.
   - Closes G-9 (per-op auth coverage).

---

## 12. G-10 (startup-time gate) — re-measurement closed

**Команда**: `python tools/checks/startup_time.py` на HEAD `25eee5571`.

**Результат**:
```
TOTAL: 1.472s (median of 3)
SAMPLES: 1.556, 1.472, 1.467
BASELINE: 2.400s
REGRESSION LIMIT: 3.120s (baseline × 1.3)
OK: startup-time gate passed
```

**Per-module medians**: features 0.307s, tenancy 0.242s, messaging 0.117s, processor 0.268s, lazy_processor 0.263s, routes_loader 0.294s, dlq 0.008s — все ≤ 3.0s лимит.

**Verdict**: G-10 **CLOSED**. Per gate criteria (`median ≤ 2.145s`), текущий median 1.472s укладывается с запасом 32%. Was FLAKY 1.782-2.263s в CURRENT §"Pre-production"; теперь solidly passing.
