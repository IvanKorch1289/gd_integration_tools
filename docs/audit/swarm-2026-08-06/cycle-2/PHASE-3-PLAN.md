# Cycle 2 / Phase 3 — План доработки (DRAFT)

**Дата:** 2026-08-06
**HEAD:** `ca5bff93058f2580041a7339913b52943babb329` (cycle-2 baseline, +15 над cycle-1 baseline `b69d6b49`)
**Режим:** создаётся только `docs/audit/swarm-2026-08-06/cycle-2/PHASE-3-PLAN.md`. Source/lockfile/allowlist/s3.py/blue_green **НЕ модифицируются**.
**Evidence:** `PHASE-2-SUMMARY.md` (190 findings: 52 P0 / 49 P1 / 51 P2 / 24 P3 / 14 P4) + `BASELINE.md` (175 legacy / 0 new; 35 active CVE; 0 missing docstrings).
**Uncommitted cycle-1 правки НЕ переписывать (ответственность developer commit step):**
- T-0.1 — `tools/cycle-1-preflight.sh` (reference, verify-only);
- T-1.4 — `gateway_pipeline_mixin` / `redelivery_policy` (DSL multicast+redelivery);
- T-1.5 — `AIGateway` dual-signature detection (`policy_mixin`/`gateway_adapter`);
- T-3.1 — `cachetools` (`embedding_cache`).

**Pre-existing drift атрибутируется developer commit step, НЕ этому плану:**
`M uv.lock -15 svcs`, `M tools/blue_green.sh`, `M tests/unit/tools/test_blue_green_switch.py`, `?? pip-audit.json`, `?? .blue_green.state`. Cycle 2 НЕ предписывает их рою.

**Cycle-1 MUTATED (не переоткрывать):** T-1.4, T-1.5, T-3.1 (закрыты в working tree; см. PHASE-2-SUMMARY §5.5).
**Cycle-1 RESIDUAL (основная цель cycle 2):** 30+ находок, верифицированных cross-domain (см. PHASE-2-SUMMARY §5.4).

---

## 0. Definition of Done (DoD) cycle 2

Минимально-обязательные гейты для признания cycle 2 закрытым:

1. `python tools/check_layers.py --root src` → exit 0; **175 legacy / 0 new** (no-growth gate).
2. `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → **35 active** (no-new-CVE gate).
3. `make check-docstrings MAX_ALLOWED=0` → 0 missing (838 файлов).
4. `tools/cycle-1-preflight.sh` (T-0.1) присутствует, executable, прогнан self-check без перезаписи.
5. Все новые regression-тесты — **runtime без mock** на критические API. 5 test-masking issues из PHASE-2-SUMMARY §5.3 (08-P0-005, 09-P0-002, 08-P0-003, 02-P0-003, 06-P0-001) — для закрытых в Wave 1 — строгий runtime assertion (без `AsyncMock` на runtime-критичных вызовах); 06-P0-001 — оставлен для cycle 3 (нужен source-read).
6. Никаких `except Exception: pass` без concrete handling + `logger.error`/DLQ. Pre-existing residual `gateway_adapter.py:128-129` (critic cycle 1) — **НЕ переписывать**; рядом — test-фиксация (T-W1-03).
7. 5 uncommitted cycle-1 правок **НЕ переписаны**; cycle-2 commits атомарны и поверх working tree.
8. Все security/data-loss fixes содержат B-XX/cycle-2/D-AUDIT-## docstring marker.
9. По pre-existing `uv.lock` diff (Sprint 36 несогласован) — **НЕ** инициируется `uv add`/`uv remove`/`uv lock`.

**Причины, по которым потребуется cycle 3:**

A. Из 52 P0 cycle 2 закрывает 8 наиболее-локальных; остаётся 44 P0 (workstreams A–F из PHASE-2-SUMMARY §6).
B. 5+ test-masking issues требуют отдельного integration-workstream'а (mock-free тесты; вне scope cycle 2).
C. 30+ cycle-1 RESIDUAL — выполнение за рамками cycle 2.
D. 4 ранее-deferred cycle-1 задачи (T-1.1 composition root, T-1.2 SSE/HITL auth, T-1.3 MQ DLQ, T-2.1 reverse-layer cleanup, T-4.1 text-RAG E2E) — T-4.1 закрывается частично через T-W4-01; T-1.1/T-1.2/T-1.3/T-2.1 — для cycle 3.
E. Workstreams G (DSL @processor 58 классов / 3100 LOC), H (CVE drift), J (dead code 500–1000 LOC) — большие LOC, требуют отдельного спринта.
F. 6 pending unresolved (PHASE-2-SUMMARY §5.7) — требуют source-read в Phase 1 cycle 3 для дизайн-решений.
G. 10 доменов (01–10) дают 0 P0 в Phase 1 cycle 2 для ≥80 readiness; cycle 2 поднимает 1–4 домена на 45–90.

---

## 1. Структура плана (16 задач)

| Волна | Кол-во | Домены | Effort | Зависимости |
|---|---|---|---|---|
| **Wave 0** | 2 | 11 / all | 0.5 dev-day | — |
| **Wave 1 (P0)** | 8 | 01 / 02 / 04 / 08 / 09 / 10 | 4–6 dev-days | W0 + W1-04 composition root |
| **Wave 2 (P1 layer)** | 4 | 02 / 08 / 10 / all | 2–3 dev-days | W1-04 composition root |
| **Wave 3 (P3 lib)** | 1 | 03 / 11 | 1–2 dev-days | — |
| **Wave 4 (P4 feat)** | 1 | 09 | 0.5–1 dev-day | — |
| **Wave N (deferred)** | 30+ | все | — | cycle 3+ |

**Total cycle 2 effort:** 8–12 dev-days (4 devs × 2–3 days; или 6 devs × 1.5–2 days).
**Coverage cycle 2:** 7 из 12 доменов (01, 02, 03, 04, 08, 09, 10, 11). 05, 06, 07, 12 — deferred (требуют source-read / больших LOC).

---

## 2. Wave 0 — Пре-флайт и защита от stale evidence

### T-W0-01: Верифицировать `tools/cycle-1-preflight.sh` (cycle-1 RESIDUAL, verify-only)

**Finding IDs:** T-0.1 (cycle-1 RESOLVED; reference-only в cycle 2).
**Priority:** P0 (gate).
**Domain:** 11 Dependencies.

**Пути:**
- Implementation: `tools/cycle-1-preflight.sh` (НЕ модифицировать; verify-only).
- Тест: `tests/unit/tools/test_cycle_1_preflight.py` (новый, ≤50 LOC).
- Docstring marker: `B-CC-01` в test file header.

**Что сделать:**
- Зафиксировать наличие и executable bit `tools/cycle-1-preflight.sh`.
- Прогнать `--self-check` (или эквивалентный dry-run режим) → exit 0.
- Сохранить вывод: `docs/audit/swarm-2026-08-06/cycle-2/W0-preflight.log` (новый, ≤200 LOC).
- Если скрипт отсутствует — REPAIR из git stash/show (НЕ переписывать).

**Минимальный diff:**
- Только test file: assert script exists, assert `subprocess.check_call` exit 0.
- Log файл — read-only verification.

**Зависимости:** нет.
**Параллельная группа:** G0 (gate).
**LOC range:** 0 + 30–50 LOC (test).
**Готово когда:** `python tools/cycle-1-preflight.sh --self-check` exit 0; test passes; W0-preflight.log сохранён.
**Rollback risk:** нет (read-only verify).
**Docstring marker:** `B-CC-01`.

### T-W0-02: Свежий-evidence gate (baseline 175/0 / 35 / 0 / preflight)

**Finding IDs:** cycle-2 BASELINE gate.
**Priority:** P0 (gate).
**Domain:** all 12.

**Пути:**
- Implementation: `tests/unit/audit/test_cycle_2_baseline_gates.py` (новый, ≤80 LOC).
- Тест: same file.
- Docstring marker: `B-CC-02`.

**Что сделать:**
- Создать baseline-тест, прогоняющий 4 метрики и сравнивающий с BASELINE.md.
- Если хоть одна метрика WORSE — тест FAIL; future drift виден.
- Фиксирует 175 legacy / 0 new / 35 active CVE / 0 missing docstrings / preflight exits 0.

**Минимальный diff:**
- 4 отдельных test-функции (layer / allowlist / docstrings / preflight).
- `subprocess.run` + `assert` на exit code и stdout substrings.

**Зависимости:** T-W0-01.
**Параллельная группа:** G0 (gate, после T-W0-01).
**LOC range:** 60–80 LOC.
**Готово когда:** pytest test passes; 4 метрики == BASELINE.
**Rollback risk:** низкий (test-only).
**Docstring marker:** `B-CC-02`.

---

## 3. Wave 1 — P0 security / reliability (8 задач)

### T-W1-01: AuthValidateProcessor fail-closed (02-P0-003)

**Finding IDs:** 02-DOMAIN-P0-003.
**Priority:** P0.
**Domain:** 02 Security.

**Пути:**
- Implementation: `src/backend/dsl/engine/processors/security.py` (`_load_verifiers`, `process`).
- Тест: `tests/unit/dsl/processors/security/test_auth_validate_failclosed.py` (новый, ≤60 LOC).
- Docs: `docs/security/AUTH_CHAIN.md` (mark section).

**Что сделать:**
- Replace `return {}` (fail-open) → `raise AuthenticationProviderUnavailableError` (fail-closed).
- Pure ASGI pattern: `AuthRequiredMiddleware` уже верифицирует request.state.auth; dead branch убирается.
- Existing xfail mock test `test_handler_auth.py` — перевести в `pytest.fail` (strict) или runtime-assertion.

**Минимальный diff:**
- `_load_verifiers` → verifiers empty → raise + `logger.error("auth_provider_unavailable", extra={...})`.
- `process` → `required=True` + verifiers empty → 401.

**Зависимости:** нет.
**Параллельная группа:** G1 (W1-A auth).
**LOC range:** 30–50 fix + 40–60 test.
**Готово когда:** test passes; xfail removed; runtime без mock → 401 при пустых verifiers.
**Rollback risk:** низкий (fail-closed безопасный).
**Docstring marker:** `D-AUDIT-03` (security fix).

### T-W1-02: CDC DLQ writer failure → DLQ + logger.error (01-P0-001)

**Finding IDs:** 01-DOMAIN-P0-001.
**Priority:** P0 (data-loss).
**Domain:** 01 Infrastructure.

**Пути:**
- Implementation: `src/backend/infrastructure/clients/external/cdc/client.py` (DLQ writer section).
- Тест: `tests/unit/infrastructure/cdc/test_cdc_dlq_writter_fails_closed.py` (новый, ≤50 LOC).
- Docs: `docs/infrastructure/CDC_DLQ.md`.

**Что сделать:**
- Replace `log "EVENT WILL BE LOST"` + return без DLQ → enqueue в DLQ через `DLQWriter` Protocol + `logger.error(...)`.
- B-17 fail-loud: при невозможности DLQ-enqueue → re-raise original exception (caller retry).
- Никаких `except Exception: pass` без concrete handling.

**Минимальный diff:**
- В DLQ writer catch: `await dlq_writer.write(payload, reason="cdc_write_failure")` + `logger.error("CDC DLQ enqueued", extra={"payload_id": ...})`.
- Если dlq_writer недоступен → re-raise (fail-loud).

**Зависимости:** T-W1-04 (DLQWriter в composition root).
**Параллельная группа:** G2 (W1-B DLQ).
**LOC range:** 25–40 fix + 40–50 test.
**Готово когда:** test asserts dlq_writer.write вызван; симуляция IOError → assert DLQ + logger.error.
**Rollback risk:** низкий.
**Docstring marker:** `D-AUDIT-04` (data-loss fix).

### T-W1-03: MQ subscribers ACK → DLQ + gateway_adapter fix-защита (04-P0-002)

**Finding IDs:** 04-DOMAIN-P0-002.
**Priority:** P0 (data-loss).
**Domain:** 04 Entrypoints.

**Пути:**
- Implementation: `src/backend/entrypoints/stream/{subscribers,invoker_subscribers}.py`.
- Тест: `tests/unit/entrypoints/stream/test_mq_subscribers_dlq.py` (новый, ≤70 LOC).
- Gateway_adapter protection: `tests/unit/entrypoints/stream/test_gateway_adapter_except_protection.py` (новый, ≤30 LOC).
- Docs: `docs/entrypoints/MQ_DLQ.md`.

**Что сделать:**
- Replace ACK-on-error → NACK + DLQ enqueue.
- B-17 fail-loud: при exception в handler → DLQ + logger.error.
- Pre-existing residual `gateway_adapter.py:128-129` (critic cycle 1) — **НЕ переписывать**; создать test-фиксацию поведения, чтобы cycle 3 увидел regression. Test фиксирует: либо fail-closed (если найден concrete handler), либо явно fail-OPEN (как regression marker).

**Минимальный diff:**
- В on_message exception handler: `await dlq_writer.write(message, reason=...)` + `logger.error(...)` + `await msg.nack()`.
- DI: DLQWriter в subscription handler factory.
- Test для gateway_adapter: snapshot поведения + assertion marker.

**Зависимости:** T-W1-04 (composition root).
**Параллельная группа:** G2 (W1-B DLQ).
**LOC range:** 40–60 fix + 50–70 test (DLQ) + 30 test (gateway_adapter).
**Готово когда:** mock dlq_writer + raise subscriber → assert DLQ called; gateway_adapter test показывает regression marker.
**Rollback risk:** низкий.
**Docstring marker:** `D-AUDIT-05` (data-loss fix).

### T-W1-04: composition-root DI + AIGatewayProductionWiringError (08-P0-006 + 08-P0-004)

**Finding IDs:** 08-DOMAIN-P0-006, 08-DOMAIN-P0-004 (overlap).
**Priority:** P0 (critical path; root для W1-B, W2-*).
**Domain:** 08 Agents.

**Пути:**
- Implementation: `src/backend/core/di/composition_root.py` (canonical register); `src/backend/core/di/errors.py` (AIGatewayProductionWiringError); `src/backend/services/ai/ai_agent/__init__.py` (replace NotImplementedError).
- Protocol: `src/backend/core/ai/workflow_protocol.py` (≤40 LOC, для 08-P0-004).
- Тест: `tests/unit/core/di/test_composition_root_ai_gateway.py` (новый, ≤80 LOC).
- Docs: `docs/agents/COMPOSITION_ROOT.md`.

**Что сделать:**
- Создать `AIGatewayProductionWiringError(RuntimeError)` в `core/di/errors.py`.
- `get_ai_agent_service()` → если app.state.ai_agent_service is None → raise `AIGatewayProductionWiringError` (не `NotImplementedError`).
- Composition root provider: `app.state.ai_agent_service = AIGateway(...)` в lifespan.
- DSL→infra fastmcp coupling (08-P0-004) → runtime Protocol в `core/ai/workflow_protocol.py` (одна реализация → interface не нужен; просто Protocol для typing).

**Минимальный diff:**
- `core/di/errors.py` (≤30 LOC).
- `core/di/composition_root.py` (≤80 LOC register).
- `services/ai/ai_agent/__init__.py` — replace NotImplementedError → raise AIGatewayProductionWiringError.
- `dsl/agents/fastmcp_server.py` — import через Protocol вместо прямого `infrastructure.workflow.registry`.

**Зависимости:** T-W0-02.
**Параллельная группа:** G3 (composition root, critical path).
**LOC range:** 80–120 fix + 60–80 test.
**Готово когда:** 7 callsites больше не NotImplementedError; runtime pipeline проходит; test passes.
**Rollback risk:** средний (composition root — sensitive).
**Docstring marker:** `D-AUDIT-06` (production crash fix).

### T-W1-05: CDC + Filewatcher management no-auth (04-P0-003)

**Finding IDs:** 04-DOMAIN-P0-003.
**Priority:** P0.
**Domain:** 04 Entrypoints.

**Пути:**
- Implementation: `src/backend/entrypoints/cdc/cdc_routes.py`, `src/backend/entrypoints/filewatcher/watcher_routes.py`.
- Тест: `tests/unit/entrypoints/cdc/test_management_endpoints_auth.py` (новый, ≤40 LOC).
- Docs: `docs/entrypoints/CDC_AUTH.md`.

**Что сделать:**
- Подключить `AuthRequiredMiddleware` ко всем management-endpoint'ам (list/create/delete).
- Pure ASGI pattern: middleware-level (раньше route-level) — fail-closed.
- Tenant ContextVar присутствует в request.state.auth → роут проверит.

**Минимальный diff:**
- В router: `dependencies=[Depends(require_admin)]` (existing pattern).
- Pure ASGI middleware-level attachment.

**Зависимости:** нет.
**Параллельная группа:** G1 (W1-A auth).
**LOC range:** 15–25 fix + 30–40 test.
**Готово когда:** test: GET / POST / DELETE без auth → 401; с admin principal → 200.
**Rollback risk:** низкий.
**Docstring marker:** `D-AUDIT-07` (security fix).

### T-W1-06: RagCachePrewarmer silent no-op + phantom fill_cache (09-P0-002 + 09-P0-004)

**Finding IDs:** 09-RAG-P0-002, 09-RAG-P0-004.
**Priority:** P0 (RAG silent fail).
**Domain:** 09 RAG.

**Пути:**
- Implementation: `src/backend/services/ai/rag_cache_prewarmer.py`.
- Тест: `tests/unit/services/ai/test_rag_cache_prewarmer_runtime.py` (новый, ≤80 LOC, **БЕЗ mock**).
- Docs: `docs/rag/CACHE_PREWARMER.md`.

**Что сделать:**
- Runtime test: реальный DB/cache → assert prewarmer enqueue'ит ≥ 1 entry. Existing test mock'ит `rag.query = AsyncMock(...)` — отказаться от mock этого вызова.
- Phantom `fill_cache` parameter: убрать или реализовать в `RAGService.augment_prompt` сигнатуре.
- Integration test: streamlit pipeline ingesting real docs → cache статистика non-zero.

**Минимальный diff:**
- Зафиксировать runtime contract в `rag_cache_prewarmer.py` docstring.
- Если fill_cache отсутствует → реализовать в сигнатуре (≤20 LOC).

**Зависимости:** нет.
**Параллельная группа:** G1 (W1-D RAG).
**LOC range:** 20–30 fix + 60–80 test (integration).
**Готово когда:** integration test passes; `Loaded: N` где N > 0 (реальный runtime).
**Rollback risk:** низкий.
**Docstring marker:** `D-AUDIT-08` (data-loss fix).

### T-W1-07: SSE principal/permissions fail-open (04-P0-001)

**Finding IDs:** 04-DOMAIN-P0-001.
**Priority:** P0.
**Domain:** 04 Entrypoints.

**Пути:**
- Implementation: `src/backend/entrypoints/sse/handler.py`, `src/backend/entrypoints/sse/_action_bridge.py`.
- Тест: `tests/unit/entrypoints/sse/test_sse_principal_propagation.py` (новый, ≤50 LOC).
- Docs: `docs/entrypoints/SSE_AUTH.md`.

**Что сделать:**
- Tenant ContextVar `request.state.auth.principal` → propagation в SSE handler.
- Post-filter: если `principal is None` → 401 (раньше 200).
- 8 xfail sf → strict: `xfail(strict=False)` → strict + runtime assertion.

**Минимальный diff:**
- В handler: `principal = request.state.auth.principal` → если None → raise.
- `_action_bridge.py` → передача principal в dispatch.

**Зависимости:** T-W1-04 (composition root, AuthContext).
**Параллельная группа:** G2 (W1-A auth).
**LOC range:** 20–30 fix + 40–50 test.
**Готово когда:** 8 xfail → 0 xfail; новый test principal=None → 401.
**Rollback risk:** низкий.
**Docstring marker:** `D-AUDIT-09` (security fix).

### T-W1-08: Credit scoring fail-OPEN base_score=750 (10-P0-003)

**Finding IDs:** 10-DOMAIN-P0-003.
**Priority:** P0 (banking-critical).
**Domain:** 10 Business Logic.

**Пути:**
- Implementation: `extensions/credit_pipeline/agents/__init__.py`.
- Тест: `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` (новый, ≤40 LOC).
- Docs: `docs/extensions/credit_pipeline/SCORING.md`.

**Что сделать:**
- Replace `base_score=750` default → `Decision.UNDECIDED` (или `REJECTED`) для unknown tenant.
- Per-plugin lifecycle: `plugin.toml` capability-check.
- Audit event: `audit.emit("credit_rejected", reason="unknown_tenant")`.

**Минимальный diff:**
- В scoring function: явный branch на unknown → `Decision.REJECTED`.
- Audit event emission.

**Зависимости:** нет.
**Параллельная группа:** G1 (W1-D extensions).
**LOC range:** 15–25 fix + 30–40 test.
**Готово когда:** test_scoring_rejects_missing_income PASS; test_scoring_unknown_tenant_rejected PASS.
**Rollback risk:** средний (banking decision).
**Docstring marker:** `D-AUDIT-10` (banking-critical fix).

---

## 4. Wave 2 — P1 architectural / layer track

### T-W2-01: Layer checker no-growth gate (tools/check_layers.py)

**Finding IDs:** cycle-2 BASELINE gate.
**Priority:** P0 (gate; не P1 архитектурный, но runtime-тест).
**Domain:** all 12.

**Пути:**
- Implementation: `tests/unit/audit/test_layer_checker_no_growth.py` (новый, ≤50 LOC).
- Тест: same file.
- Docs: `docs/architecture/LAYER_CHECKER.md`.

**Что сделать:**
- Прогон `python tools/check_layers.py --root src` → assert exit 0; stdout contains "175 legacy / 0 new".
- Pre-commit hook: при появлении NEW (non-legacy) violation → exit 1.

**Минимальный diff:**
- Test: subprocess.run; assert output не содержит " new" сверх 0.

**Зависимости:** T-W0-02.
**Параллельная группа:** G2 (W2-A architecture).
**LOC range:** 30–50 LOC.
**Готово когда:** test passes; baseline stable 175/0.
**Rollback risk:** нет.
**Docstring marker:** `B-CC-03`.

### T-W2-02: DSL→entrypoints runtime importlib (02-P1-001)

**Finding IDs:** 02-DOMAIN-P1-001.
**Priority:** P1 (architecture).
**Domain:** 02 Security.

**Пути:**
- Implementation: `src/backend/dsl/engine/processors/security.py` (или `core/auth/capability_check.py`).
- Тест: `tests/unit/dsl/processors/test_dsl_to_entrypoints_no_importlib.py` (новый, ≤40 LOC).
- Docs: `docs/architecture/LAYERS.md`.

**Что сделать:**
- DSL workspace import path: `importlib.import_module("backend.entrypoints.api.dependencies.auth_selector")` → статический импорт через core capability registry.
- Layer check: DSL не должен импортировать entrypoints напрямую.

**Минимальный diff:**
- `core/auth/capability_check.py` (≤60 LOC capability registry).
- Replace dynamic import → static via capability.

**Зависимости:** T-W1-04.
**Параллельная группа:** G2 (W2-A architecture).
**LOC range:** 40–60 fix + 30–40 test.
**Готово когда:** layer_checker no-growth; test passes.
**Rollback risk:** средний.
**Docstring marker:** `D-AUDIT-11` (architecture fix).

### T-W2-03: DSL→infra fastmcp coupling (08-P0-004, partial)

**Finding IDs:** 08-DOMAIN-P0-004 (overlap с T-W1-04).
**Priority:** P1 (architecture).
**Domain:** 08 Agents.

**Пути:**
- Implementation: `src/backend/dsl/agents/fastmcp_server.py` (финализация после T-W1-04).
- Тест: `tests/unit/dsl/agents/test_fastmcp_no_infra_import.py` (новый, ≤40 LOC).
- Docs: `docs/agents/FAST_MCP.md`.

**Что сделать:**
- Завершить то, что T-W1-04 не покрыл: explicit Protocol-based static imports.

**Минимальный diff:**
- fastmcp_server.py: импорт через Protocol (≤30 LOC).

**Зависимости:** T-W1-04 (Protocol создан).
**Параллельная группа:** G2 (W2-A architecture).
**LOC range:** 20–30 fix + 30–40 test.
**Готово когда:** layer_checker no-growth; test passes.
**Rollback risk:** средний.
**Docstring marker:** `D-AUDIT-12` (architecture fix).

### T-W2-04: extension→infra dynamic import (10-P1-001)

**Finding IDs:** 10-DOMAIN-P1-001.
**Priority:** P1 (architecture).
**Domain:** 10 Business Logic.

**Пути:**
- Implementation: `extensions/core_entities/orders/services/orders.py`.
- Тест: `tests/unit/extensions/core_entities/test_orders_no_infra_import.py` (новый, ≤40 LOC).
- Docs: `docs/extensions/LAYERS.md`.

**Что сделать:**
- Replace `importlib.import_module("backend.infrastructure.external_apis.s3")` → `from core.facades import get_s3_client` (capability-checked facade, D160 уже реализован).

**Минимальный diff:**
- ≤25 LOC: замена import.

**Зависимости:** T-W1-04 (composition root).
**Параллельная группа:** G2 (W2-A architecture).
**LOC range:** 15–25 fix + 30–40 test.
**Готово когда:** direct import отсутствует; layer check no new violations.
**Rollback risk:** низкий.
**Docstring marker:** `D-AUDIT-13` (architecture fix).

---

## 5. Wave 3 — P3 library replacement

### T-W3-01: `tenacity` consolidation (already in pyproject)

**Finding IDs:** 03-SVCS-P3-001, 11-P3-001.
**Priority:** P3.
**Domain:** 03 Services / 11 Dependencies.

**Пути:**
- Implementation: `src/backend/core/resilience/retry/retry_async.py` (consolidation entry); `src/backend/services/resilience/facade.py` (with_retry); `src/backend/entrypoints/stream/invoker_subscribers.py`; `src/backend/entrypoints/mqtt/mqtt_handler.py`.
- Тест: `tests/unit/core/resilience/test_tenacity_consolidation.py` (новый, ≤40 LOC); `tests/unit/core/resilience/test_retry_alias_compat.py` (новый, ≤30 LOC, compat).
- Docs: `docs/resilience/TENACITY_MIGRATION.md`.

**Maturity / License rationale (evidence-based):**
- `tenacity` ≥ 9.0.0,<10.0.0 — **уже в pyproject** (dependency manifest, line 74), used in 5+ files.
- License: Apache-2.0 (verifiable через `pip show tenacity`).
- Maintenance: active (Long Now Foundation sustainable; releases twice yearly).
- **Already in dependency manifest — NO lockfile change required.** Безопасный replacement.

**Custom code to replace:**
- `core/resilience/retry/retry_async.py` (~50 LOC wrapper) → `tenacity.AsyncRetrying`.
- `services/resilience/facade.py:205+` `with_retry` (~10 LOC) → `tenacity.retry` decorator.
- `stream/invoker_subscribers.py:60-66` reconnect (~10 LOC) → `tenacity` exponential backoff.
- `mqtt/mqtt_handler.py:128-129` hardcoded `asyncio.sleep(5)` (~5 LOC) → `tenacity.wait_exponential`.

**Минимальный diff:**
- `retry_async.py` → thin wrapper над `tenacity.AsyncRetrying().call` (≤80 LOC).
- Backward-compat alias: `retry_async = tenacity.AsyncRetrying().call` (сохраняет public API).
- 3 callsites → `tenacity.retry` decorator.

**Зависимости:** нет.
**Параллельная группа:** G1 (W3-A library).
**LOC range:** –50 to –100 LOC reduction.
**Готово когда:** все 3 callsites используют tenacity; `retry_async` остаётся как alias; compat test passes.
**Rollback risk:** низкий (tenacity уже в lockfile).
**Compatibility test:** `tests/unit/core/resilience/test_retry_alias_compat.py` (≤30 LOC) — assert public API не изменился.
**Docstring marker:** `B-CC-04`.

---

## 6. Wave 4 — P4 organic feature

### T-W4-01: Text-RAG E2E test (RAG-P4-001)

**Finding IDs:** 09-RAG-P4-001 (cycle-1 deferred T-4.1).
**Priority:** P4 (organic feature / test).
**Domain:** 09 RAG.

**Пути:**
- Implementation: `tests/integration/rag/test_text_rag_e2e.py` (новый, ≤120 LOC).
- Тест: same file.
- Docs: `docs/rag/E2E_TESTS.md`.

**Польза для проекта (evidence-based):**
- Cycle-1 deferred T-4.1 (text-RAG E2E); PHASE-2-SUMMARY §8 рекомендует PLAN priority.
- Reuses `test_multimodal_rag_e2e.py` pattern (cycle-33 baseline).
- Покрывает путь `RAGService.augment_prompt → llm_call → response` (production sign-off).
- **Не усложняет архитектуру** (только test).
- Закрывает 1 из 4 phase-1-deferred cycle-1 tasks (T-4.1).

**Минимальный diff:**
- Setup: 3 fixtures (tenant, query, doc).
- Steps: ingest → query → augment → LLM mock (mock допустим здесь — это LLM-out, не runtime-crit) → response validation.
- Assert: response содержит source citations.

**Зависимости:** нет.
**Параллельная группа:** G1 (W4-A organic).
**LOC range:** 80–120 LOC (новый test file).
**Готово когда:** `pytest tests/integration/rag/test_text_rag_e2e.py -q` PASS.
**Rollback risk:** нет (test-only).
**Docstring marker:** `B-CC-05`.

---

## 7. Wave N — deferred до cycle 3+

(НЕ выполнять в cycle 2; перечислить для прозрачности.)

### 7.1 P0 остаётся для cycle 3+ (44 P0 из 52; 8 в Wave 1)

- 02-DOMAIN-P0-001 (validate_sql policy_override), 02-DOMAIN-P0-002 (deprecated auth_selector shim, 5 consumers), 02-DOMAIN-P0-004 (sync AuthorizationGateway bypass).
- 03-DOMAIN-SVCS-P0-001 (AdminService fail-open).
- 04-DOMAIN-P0-001 (partial fix в T-W1-07, остаток — IF insufficient).
- 05-API-P0-001/002 (admin_actions/plugins mock fallback), 05-API-P0-003 (generator/setup.py broken), 05-API-P0-004 (hitl no auth), 05-API-P0-005 (mobile orphan).
- 06-DSL-P0-001 (ScanFile fail-open — design decision pending), 06-DSL-P0-002/003 (XML XXE).
- 07-DOMAIN-WF-P0-001..005 (WorkflowFlags lie, 4 unregistered, ActivityBridge, TemporalWorkerPool, bootstrap saga).
- 08-DOMAIN-P0-005 (LangGraph TypeError — partial fix в T-W1-04).
- 09-RAG-P0-001 (single-doc PII), 09-RAG-P0-003 (sanitizer fail-open).
- 10-DOMAIN-P0-001 (repos.files stale), 10-DOMAIN-P0-002 (saga imports), 10-DOMAIN-P0-004 (OSINT fabrication).
- 11-DOMAIN-P0-001/002/003/004 (CVE drift).
- 12-ENVSET-C2-P0-001/002 (Granian flag, dup field).

### 7.2 P1 architecture, P2 dead code, P3 library, P4 feature остаются

- 5 P1 architecture (sync AuthorizationGateway, SAML trust, MCP private symbols, etc.).
- 51 P2 dead code (cycle-38 W-series cleanup).
- 23 P3 library replacement (xmltodict, rank_bm25, presidio, faststream_fastapi, defusedxml, OutboundHttpClient, etc.).
- 13 P4 organic features (workflow timeout-cancellation, LiteLLM streaming, cellular scoring, BPMN multi-instance, etc.).

### 7.3 Pending unresolved (PHASE-2-SUMMARY §5.7)

Требуют source-read в Phase 1 cycle 3 для дизайн-решений:
- 02-P0-004 sync path semantics.
- 07-P0-001 WorkflowFlags default.
- 11-P0-002 9 CVE carryover.
- 12-P0-002 field dup canonical.
- 06-P0-001 scan_file design.
- 08-P0-006 composition root registration (частично закрывается T-W1-04).

---

## 8. Граф зависимостей и параллельные группы

### 8.1 Dependency graph

```
T-W0-01 ─→ T-W0-02 ─┬─→ W1-A: T-W1-01, T-W1-05, T-W1-07  (auth cluster)
                    ├─→ W1-B: T-W1-02, T-W1-03           (DLQ, depends T-W1-04)
                    ├─→ W1-C: T-W1-04                     (composition root, critical path)
                    ├─→ W1-D: T-W1-06, T-W1-08            (RAG/extensions)
                    │
                    ├─→ W2-A: T-W2-01, T-W2-02, T-W2-03, T-W2-04  (architecture; depends T-W1-04)
                    │
                    ├─→ W3-A: T-W3-01                     (lib, independent)
                    │
                    └─→ W4-A: T-W4-01                     (organic, independent)

T-W1-04 ─→ T-W1-02, T-W1-03, T-W1-07, T-W2-02, T-W2-03, T-W2-04
```

### 8.2 Параллельные группы для Phase 4 developers

| Группа | Состав | Кол-во devs | Куда | Откуда |
|---|---|---|---|---|
| **G0 (gate)** | T-W0-01, T-W0-02 | 1 | сериал | — |
| **G1 (parallel, post-G0)** | T-W1-01, T-W1-05, T-W1-06, T-W1-08, T-W3-01, T-W4-01 | 6 | параллель | — |
| **G2 (parallel, post-T-W1-04)** | T-W1-02, T-W1-03, T-W1-07, T-W2-01, T-W2-02, T-W2-03, T-W2-04 | 7 | параллель | T-W1-04 |
| **G3 (critical path)** | T-W1-04 | 1 | serial | T-W0-02 |

**Оптимальная team shape:** 4 devs (G0 + G3 + G1[x2] + G2[x1]) — комфортный 6–8 dev-days.
**Сжатая shape:** 6 devs (G0 + G3 + G1[x3] + G2[x2]) — 4–5 dev-days.

### 8.3 Top dependencies (critical path)

```
T-W0-01 → T-W0-02 → T-W1-04 → T-W1-02 / T-W1-03 / T-W1-07 / T-W2-02 / T-W2-03 / T-W2-04
```

Composition root (T-W1-04) — единственный serial bottleneck. Все остальное параллелится.

---

## 9. Риски и меры

### 9.1 Cross-check с BASELINE / pre-existing drift

- **5 uncommitted cycle-1 правок** (T-0.1, T-1.4, T-1.5, T-3.1): **НЕ переписывать**; используются как evidence.
- **`uv.lock` -15 svcs**: cycle 2 НЕ предписывает `uv add`/`uv remove`/`uv lock`; ответственность developer commit step.
- **`tools/cycle-1-preflight.sh`**: верифицировать (T-W0-01), не переписывать.
- **`pip-audit.json` untracked**: не трогать.
- **`.blue_green.state` untracked**: не трогать.
- **`tools/blue_green.sh` modified**: не трогать.
- **`tests/unit/tools/test_blue_green_switch.py` modified**: не трогать.

### 9.2 Test-masking protection (5+ issues из PHASE-2-SUMMARY §5.3)

- 08-P0-005 (LangGraph TypeError) — T-W1-04 + integration test (no mock на runtime-crit).
- 09-P0-002 (RagCachePrewarmer silent no-op) — T-W1-06 + runtime test (no mock).
- 08-P0-003 (hardcoded tenant_id) — T-W1-04 + integration test (assert `AIRequest.tenant_id` явно).
- 02-P0-003 (AuthValidateProcessor) — T-W1-01 + runtime test (no mock на `_load_verifiers`).
- 06-P0-001 (ScanFile fail-open) — оставлено для cycle 3 (нужен source-read для design decision).

### 9.3 `except Exception` без concrete handling

- Wave 1 fix-ы заменяют `except Exception: pass` → `except Exception: await dlq_writer.write(...)` + `logger.error(...)`.
- Pre-existing residual `gateway_adapter.py:128-129` (critic cycle 1) — **НЕ переписывать** (cycle 2 ownership = developer commit step). T-W1-03 создаёт test-фиксацию для cycle 3 visibility.

### 9.4 Docstring markers (security/data-loss)

| Task | Marker | Категория |
|---|---|---|
| T-W0-01 | `B-CC-01` | gate/verify |
| T-W0-02 | `B-CC-02` | gate/verify |
| T-W1-01 | `D-AUDIT-03` | security fix |
| T-W1-02 | `D-AUDIT-04` | data-loss fix |
| T-W1-03 | `D-AUDIT-05` | data-loss fix |
| T-W1-04 | `D-AUDIT-06` | production crash fix |
| T-W1-05 | `D-AUDIT-07` | security fix |
| T-W1-06 | `D-AUDIT-08` | data-loss fix |
| T-W1-07 | `D-AUDIT-09` | security fix |
| T-W1-08 | `D-AUDIT-10` | banking-critical fix |
| T-W2-01 | `B-CC-03` | gate/verify |
| T-W2-02 | `D-AUDIT-11` | architecture fix |
| T-W2-03 | `D-AUDIT-12` | architecture fix |
| T-W2-04 | `D-AUDIT-13` | architecture fix |
| T-W3-01 | `B-CC-04` | library replacement |
| T-W4-01 | `B-CC-05` | organic feature |

Cycle-2 marker: `cycle-2`. Русские docstrings **НЕ переводятся**.

### 9.5 Cyclic recursion guards

- T-W0-02 baseline gate test — idempotent (читает метрики, не мутирует).
- T-W1-04 composition root — singleton, не singleton-per-request.
- T-W3-01 backward-compat alias `retry_async` остаётся public API.

### 9.6 Composition root cache bus & protocol

- T-W1-04 + T-W2-03 используют `core/ai/workflow_protocol.py` Protocol — без runtime registration; только typing hint.
- Per-plugin lifecycle (T-W1-08) — `plugin.toml` capability-check; existing DS-pattern.

---

## 10. Сводная таблица

| ID | Приоритет | Домен | LOC | Parallel | Зависит от | Docstring marker |
|---|---|---|---|---|---|---|
| T-W0-01 | P0 gate | 11 | 0 + 30–50 test | G0 | — | B-CC-01 |
| T-W0-02 | P0 gate | all | 60–80 | G0 | T-W0-01 | B-CC-02 |
| T-W1-01 | P0 sec | 02 | 30–50 + 40–60 test | G1 | — | D-AUDIT-03 |
| T-W1-02 | P0 data-loss | 01 | 25–40 + 40–50 test | G2 | T-W1-04 | D-AUDIT-04 |
| T-W1-03 | P0 data-loss | 04 | 40–60 + 50–70 test | G2 | T-W1-04 | D-AUDIT-05 |
| T-W1-04 | P0 critical | 08 | 80–120 + 60–80 test | G3 | T-W0-02 | D-AUDIT-06 |
| T-W1-05 | P0 sec | 04 | 15–25 + 30–40 test | G1 | — | D-AUDIT-07 |
| T-W1-06 | P0 RAG | 09 | 20–30 + 60–80 test | G1 | — | D-AUDIT-08 |
| T-W1-07 | P0 sec | 04 | 20–30 + 40–50 test | G2 | T-W1-04 | D-AUDIT-09 |
| T-W1-08 | P0 bank | 10 | 15–25 + 30–40 test | G1 | — | D-AUDIT-10 |
| T-W2-01 | P0 gate | all | 30–50 | G2 | T-W0-02 | B-CC-03 |
| T-W2-02 | P1 arch | 02 | 40–60 + 30–40 test | G2 | T-W1-04 | D-AUDIT-11 |
| T-W2-03 | P1 arch | 08 | 20–30 + 30–40 test | G2 | T-W1-04 | D-AUDIT-12 |
| T-W2-04 | P1 arch | 10 | 15–25 + 30–40 test | G2 | T-W1-04 | D-AUDIT-13 |
| T-W3-01 | P3 lib | 03/11 | –50 to –100 | G1 | — | B-CC-04 |
| T-W4-01 | P4 feat | 09 | 80–120 | G1 | — | B-CC-05 |

**Total:** 16 задач (8 fix + 4 layer + 1 library + 1 feature + 2 gate).
**Cycle 2 effort estimate:** 8–12 dev-days (4 devs × 2–3 days; или 6 devs × 1.5–2 days).
**Cycle 2 coverage:** 7 из 12 доменов (01, 02, 03, 04, 08, 09, 10, 11).
**Cycle 2 P0 closed:** 8 из 52 (см. §7.1 для deferred).
**Cycle 2 P1 closed:** 4 из 49 (T-W2-01..04).
**Cycle 2 P3 closed:** 1 из 24 (T-W3-01, lowest-risk).
**Cycle 2 P4 closed:** 1 из 14 (T-W4-01, cycle-1 residual T-4.1).

---

## 11. Финальные рекомендации (для родительского агента)

1. **Critical path:** T-W0-01 → T-W0-02 → T-W1-04 → (W1-B || W2-A). Заблокировать 1 dev на T-W1-04 (composition root).
2. **Max параллелизм:** 6 параллельных devs на G1 + G2 (после composition root).
3. **Не переоткрывать:** T-1.4 / T-1.5 / T-3.1 (cycle-1 mutated).
4. **Cycle-1 RESIDUAL вне cycle 2:** 30+ находок; cycle 3+ по критериям ≥80 readiness.
5. **Pre-existing drift:** ответственность developer commit step (Sprint 36 lockfile debate).
6. **Test-masking 5+ issues:** cycle 3 — отдельный integration workstream без mock.
7. **6 pending unresolved (PHASE-2-SUMMARY §5.7):** Phase 1 cycle 3 source-read.
8. **Источники evidence:** PHASE-2-SUMMARY.md (12 phase-1 отчётов) + BASELINE.md.
9. **Lockfile / allowlist:** НЕ модифицируются cycle 2.
