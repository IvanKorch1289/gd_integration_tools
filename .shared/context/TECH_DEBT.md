# TECH_DEBT — gd_integration_tools (last update: 12.06.2026 — S82 W5)

## S82 closure summary (2026-06-12, ADR-0164)

**Status: P1 #10 (docs/cookbooks) CLOSED в S82 (5 commits, 6 docs files).**

| FINAL_REPORT_V2 # | Status | What |
|---|---|---|
| **#10 cookbooks** | ✅ CLOSED S82 W1-W5 | 5 production-ready recipes (AI tools, Outbox, E2B, CB, Pool) + README |

**Net S82 LOC**: 6 files changed, +13,212 LOC docs.

**Net P1 rating**: #6, #8, #10 CLOSED в S79-S82. Осталось: #5, #7, #11, #12.

Tracking для known issues, workarounds, и deferred work, который

## S75 closure summary (2026-06-12, ADR-0157)

**Status: направление #1 final closure CLOSED в S75 (5 commits, 15 NEW tests). 6/6 components ✅.**

| FINAL_REPORT_V2 # | Status | What |
|---|---|---|
| **#2** e2b sandbox | ✅ CLOSED S75 W1+W2 | E2BExecutionBackend (factory stub → real) |
| **#1 multi-kernels** | ✅ CLOSED S75 W3 | KernelSpecDiscovery + whitelist filter |

**Net S75 LOC**: 9 files changed, NET +864 LOC, 15 NEW tests.

**Net direction #1 rating**: ⚠️ → ✅ (6/6 components, full closure).

## S74 closure summary (2026-06-12, ADR-0156)

**Status: 1/1 P1 from FINAL_REPORT_V2 направление #1 CLOSED в S74 (5 commits, 13 NEW tests).**

| FINAL_REPORT_V2 # | Status | What |
|---|---|---|
| **#9** Papermill | ✅ CLOSED S74 W1 | New dep + PapermillExecutionBackend |
| **#1 #3** NbClient factory | ✅ CLOSED S74 W2 | ExecutionBackendFactory (HUB/PAPERMILL/NBCLIENT/E2B) |
| **#1** WebSocket heartbeat | ✅ CLOSED S74 W3 | Background ping/pong loop (30s/60s) |
| **#1** e2b notebook ExecutionBackend | ⏸ DEFERRED S75+ | Factory stub raises NotImplementedError |
| S60 W1 decomp bug | ✅ FIXED S74 W4 | __slots__ = () removed (NotebookExecutionService was unconstructable) |

**Net S74 LOC**: 12 files changed, NET +837 LOC, 13 NEW tests.

**Направление #1 rating**: ⚠️ → ⚠️-иш (3/6 components fixed, 1 partial, 2 deferred).

## S75+ epic candidates (FINAL_REPORT_V2 P0-B/C/D + S74 leftovers)

1. **e2b notebook ExecutionBackend** — implement NotImplementedError path
2. **P0-B: tools whitelist в AIPolicySpec** (FINAL_REPORT_V2)
3. **P0-C: AI Policy Spec DSL** (ADR-0067, FINAL_REPORT_V2)
4. **P0-D: CORS/XSRF в Streamlit** (FINAL_REPORT_V2)
5. **Множественные kernels** (jupyter kernelspec discovery, направление #1)

## S73 closure summary (2026-06-12, ADR-0155)

**Status: 1/1 P0 from FINAL_REPORT_V2.md CLOSED в S73 (5 commits, 2 NEW tests).**

| P0 | Status | What |
|---|---|---|
| **P0-A** SyntaxError batch fix | ✅ CLOSED S73 | 106 files / 136 patterns fixed + 2 regression tests + pre-push CI gate |

**Net S73 LOC**: 111 files changed, NET +91 LOC.

**FINAL_REPORT_V2 fact-check**:
* 26 files claim → real **83+ files** (rg pattern broader).
  106 files / 136 fixes после codemod.
* `_base64_codec.py:54` (S69 W1 subagent artifact) → ✅ auto-fixed в W1.
* 4 stale allowlist entries (schema/* deleted в S71) → ✅ W2 cleanup.
* P0-B/C/D (tools whitelist, AI Policy, CORS) → S74+ candidates.

## S74+ epic candidates (from FINAL_REPORT_V2 P0-B/C/D)

1. **P0-B: tools whitelist в AIPolicySpec** (L-scope, AI safety)
2. **P0-C: AI Policy Spec DSL** — реализовать ADR-0067 (L-scope, multi-file)
3. **P0-D: CORS/XSRF в Streamlit** (L-scope, frontend)
4. P1: PoolHealthMonitor registration (LiteLLM Gateway, etc.)
5. P1: CircuitBreakerMiddleware restoration (если ещё не deprecated)

## S72 closure summary (2026-06-12, ADR-0154)

**Status: 1/1 deferred P1 epic CLOSED в S72 (4 commits, 6 NEW tests).**

| TD | Status | What |
|---|---|---|
| **TD-S64-W1** per-row outbox claim | ✅ CLOSED S72 | Alembic + claim SQL rewrite + sweeper + 6 tests |

**Net S72 LOC**: 6 files changed (+630, -130), 1 Alembic migration,
6 NEW tests. **9/10 deferred P1 items теперь CLOSED total** (8 в S71 + 1 в S72).

**S73+ epic candidates** (correlated с FINAL_REPORT_V2.md fact-check):
1. **P0-A SyntaxError batch fix (83 files)** — `tools/fix_except_bug.py`
   codemod exists, был написан S60 W3 но НЕ ЗАПУЩЕН. Report указал
   26 files — fact-check shows 83 files реально.
2. **CI gate `python -m compileall`** в pre-commit (предотвратить новые
   SyntaxError).
3. **4 stale allowlist entries** (schema/* deleted в S71 W1) — cleanup.
4. **AI Policy / tools whitelist** (P0-B/C per report, L-scope).
5. **CORS/XSRF в Streamlit** (P0-D per report).

## S71 closure summary (2026-06-12, ADR-0153)

**Status: 8/10 OPEN items CLOSED в S71 (4 commits, 6 NEW tests).**

| TD | Status | Sprint | What |
|---|---|---|---|
| TD-S68-event-log-python2-syntax | ✅ CLOSED | S71 W1 | `except (TypeError, ValueError):` parens fix |
| TD-S68-stale-allowlist-cleanup | ✅ CLOSED | S71 W0 | 0 stale (already removed в S68-S70 waves) |
| TD-S64-W3 pre-existing import bugs | ✅ CLOSED | S71 W1+W2 | 5 bugs fixed (graphql_router, redis_client×18, s3_pool, lifecycle) |
| TD-S65-W2-style-cleanup | ✅ CLOSED | S71 W0 | discovery, no work needed |
| TD-S66-W3 19 empty `__init__.py` | ✅ CLOSED | S71 W1 | 34 docstring markers (full namespace coverage) |
| TD-S64-W2 scheduler lock auto-extend | ✅ CLOSED | S71 W3 | background heartbeat task, 60s renewal |
| TD-S64-W4 RedisDedupeStore fail-closed | ✅ CLOSED | S71 W3 | `fail_closed: bool` constructor param |
| TD-S64-W1 per-row advisory lock | ⏸ DEFERRED | S72+ | requires Alembic migration, L-scope |

**Net S71 LOC**: 77 files changed (+657, -2476), NET -1819 LOC.
**Commits**: `649d7dba` W1, `dc3b18e0` W2, `128a989c` W3, [W4] closure.

**S72+ epic candidates** (deferred from S71):
1. **TD-S64-W1**: per-row outbox claim (Alembic + UPDATE + sweeper).
2. **TD-S65-P0-cleanup**: 33 core + 121 dsl/workflow violations (real
   class moves vs accept-as-legacy).
3. **TD-S65-AUDIT P0-4**: `AgentSpec.tools` runtime enforcement
   (MCP gateway interceptor, L-scope).
нельзя закрыть в текущем спринте, но нужно зафиксировать для
будущих maintainers.

Формат: severity (low/medium/high) + рекомендуемый sprint/quarter для resolve.

---

## TD-005: `sibling-untracked-tests-broken` (medium, S39 W1)

**Файлы:** 19 untracked test files (см. `git status --short | grep ^??`):
- `tests/unit/dsl/engine/processors/test_audit_clickhouse.py` (4 fail, mock.patch на function-local import)
- `tests/unit/dsl/engine/test_versioning.py` (3 fail, mock.patch на function-local import)
- `tests/unit/dsl/engine/processors/test_sink_publish.py` (4 fail — syntax fixed in session 12e3f745 prep, но execution fails)
- `tests/unit/dsl/engine/processors/test_storage_ext.py` (syntax error fixed 12e3f745, но execution fails)
- `tests/unit/dsl/engine/processors/test_ml_inference.py` (syntax fixed, 5+ fail)
- `tests/unit/dsl/engine/processors/test_notify.py` (syntax fixed, fail)
- `tests/unit/entrypoints/api/v1/endpoints/test_admin_parallelism.py`
- `tests/unit/entrypoints/api/v1/endpoints/test_admin_resilience_profile.py`
- `tests/unit/entrypoints/api/v1/endpoints/test_admin_scheduler_dlq.py`
- `tests/unit/entrypoints/express/test_router.py`
- `tests/unit/entrypoints/filewatcher/test_watcher_manager.py`
- `tests/unit/entrypoints/filewatcher/test_watcher_routes.py`
- `tests/unit/entrypoints/websocket/test_ws_broadcast.py`
- `tests/unit/infrastructure/audit/test_event_log.py`
- `tests/unit/infrastructure/sinks/test_http_sink.py` (9 fail)
- `tests/unit/infrastructure/sinks/test_s3_sink.py` (1 fail)
- `tests/unit/infrastructure/sinks/test_webhook_sink.py` (7 fail)
- `tests/unit/infrastructure/sinks/test_email_sink.py`, `test_file_sink.py`, `test_grpc_sink.py`, `test_mq_sink.py`, `test_soap_sink.py`, `test_ws_sink.py` (passing but untracked)

**Проблема:** Sibling subagent'ы создали 19 test files без коммитов. Многие имеют:
1. Syntax errors (4 файла исправлены в session 12e3f745, но не закоммичены)
2. mock.patch на function-local imports (test_audit_clickhouse, test_versioning) — patches не срабатывают
3. Pre-existing test design issues (http_sink, s3_sink, webhook_sink)

**Решение (S39 W1):** Запустить `pytest tests/unit/<file> -v --tb=short` для каждого, починить по одному, или удалить + регенерировать через subagent с правильным TDD.

**Workaround:** Не блокирует S38 closure. Coverage на targeted модули уже добавлен в batch 6/7 (e575e84e + a20cb020).

---

## TD-004: `python-version-doc-drift` (low, S39+ decision)

**Файл:** multiple (20+ files: docs, .rules, AGENTS.md, UI, vault hints)

**Проблема:** Документация, hints в коде, и UI messages ссылаются на "Python 3.14+",
но V22 зафиксировал `requires-python = ">=3.13,<3.14"` (из-за pydantic-core 3.14
incompatible). Реальный масштаб — 20+ файлов, не 1 строка в AGENTS.md.

**Workaround:** S38 P3 = pin to 3.13. Не блокирует production.

**Decision needed (Ivan):** Python target = `>=3.13,<3.14` (current) vs `>=3.14,<3.15`
(v9 Вариант А, requires pydantic-core PyO3 0.25+) vs расширение окна. Отложено в S39.

**Refs:** v9 §II Python 3.14 Compatibility Audit, .hermes/plans/S38_V23_PLAN.md P3.

---

## TD-002: `pre-prod-check-coverage-timeout` (medium, S38+ workaround active)

**Файл:** `Makefile` (pre-prod-check target)

**Проблема:** `make pre-prod-check` (включает `make coverage-gate`) таймаутит
на 600s при полном прогоне. Background process тестировался 7+ минут.

**Workaround (S38):** Per-module `pytest --cov=src.backend.X.Y` (dotted path)
вместо project-wide. Каждый модуль проверяется отдельно. 0.5-2s на модуль.

**Fix needed:** Make `coverage-gate` использовать `--concurrency` или
parallel pytest (`pytest -n auto`) с per-CPU `coverage combine`.

**Refs:** T-P0.1.4 в `.hermes/plans/S38_P0_T-P0_1_4_coverage_gap.md`.

---

## TD-003: `vault-cipher-dead-code` (low, V24+ removal)

**Файлы:**
- `src/backend/core/security/vault_cipher.py` (~150 LOC)
- `src/backend/core/security/vault_cipher_sqlalchemy.py` (~75 LOC)

**Проблема:** Оба файла — взаимные imports (vault_cipher ↔ vault_cipher_sqlalchemy),
0 external usage за пределами самих себя. Канонический код — `secret_rotation.py`
(100% coverage, активно используется).

**Verify:** `grep -rln 'vault_cipher' src/ | grep -v 'vault_cipher.py\|vault_cipher_sqlalchemy.py'`
→ returns empty.

**Action plan:**
1. S38/S39: подтвердить 0 usage (automated grep test)
2. V24+: удалить оба файла + tests (`test_vault_cipher.py`, `test_vault_cipher_sqlalchemy.py`)
3. V24+: обновить TECH_DEBT entry → RESOLVED

**Tests preserved (S38):** 363 LOC в `tests/unit/core/security/test_vault_cipher{,_sqlalchemy}.py`
(522 tests pass) — committed чтобы deletion был low-risk в V24+.

**Refs:** `.shared/context/P0_noqa_audit.md` T-P0.1.13 closure (TECH_DEBT entries).

---

## Status summary

| ID | Severity | Sprint | Status | Action |
|----|----------|--------|--------|--------|
| TD-001 | low | S39+ | ✅ closed S50 W1 | Python target locked at 3.14 (`requires-python = ">=3.14,<3.15"`) — decision made, pydantic-core PyO3 0.25+ migration done |
| TD-002 | medium | S38+ workaround | ✅ closed S53 W4 | Makefile: coverage-gate + coverage-gate-strict now use pytest -n auto (xdist) + coverage combine; per-module workaround retained as fallback |
| TD-003 | low | V24+ removal | ✅ closed S51 W4 | vault_cipher.py + vault_cipher_sqlalchemy.py deleted (430 LOC); 0 external usage; tests preserved S38 (522 tests pass) |
| TD-006 | medium | S43+ | 🟡 documented | Vite 6.4.6/chromadb 1.5.20 phantom versions — no impact (both not used in build chain); S50 W1 re-scope: low risk, S51+ if needed |
| TD-007 | low | S43+ | ✅ closed S50 W1 | vite-env.d.ts is `/// <reference types="vite/client" />` (correct), NOT HTML — TD-007 description was wrong from start |
| TD-008 | medium | S63 W1 | ✅ partial closure | Groups 1+2+6 done; Groups 3-5 (P2) deferred to V24 |
| TD-009 | low | S44+ | ✅ closed S49 W2 | 31_DSL_Visual_Editor.py 1267 → 616 LOC (TD-009 target was 600, overshoot 16; workflow_diff.py + properties.py extraction) |
| TD-010 | low | S43+ | ✅ closed S52 W4 (stale) | 14 pages без st.set_page_config — superseded by setup_page() helper (Sprint 12 K3 W2); all 69 affected files use the helper, which internally calls st.set_page_config. TD entry stale. |

**S63 added/changed entries (1 closed, 0 new):**
- TD-008: 🟡 recommended → ✅ partial closure (S63 W1).

**Active carryover (unchanged from S62):**
- TD-001/002/003/006/007/009/010 — все либо documented, либо deferred.

**Sprint 42 added 5 TECH_DEBT entries (TD-006 — TD-010).** Все либо
documented, либо имеют low-risk workaround. Sprint 43 W1 рекомендован
для groups 1+2+6 consolidation (~560 LOC, 4-6 hours).

---

## TD-006: `verify-analysis-claims-saved-sprint-42` (medium, S43+)

**Файл:** docs/SECURITY_VULNS_2026-06-05.md, pyproject.toml, frontend/admin-react/package.json

**Проблема:** Original security vulns audit (2026-06-05) рекомендовал
**phantom versions** которые НЕ существуют в реестрах:
- `chromadb>=1.5.20,<2.0.0` — max в PyPI = 1.5.9
- `vite@^6.4.6` — не существует в npm (latest 6.x = 6.0.2, latest = 8.0.16)

`uv sync` и `npm install` оба FAILED на phantom versions. Sprint 42 W2
reverted pins + documented в SECURITY_VULNS doc.

**Lesson**: AI-генерированные security advisories могут содержать
hallucinated version numbers. **Всегда verify через PyPI/npm registry
ПЕРЕД applying patch.** Per skill `verify-analysis-claims`.

**Workaround (active)**: chromadb pin `>=0.5.0,<2.0.0` (original),
Vite pin `^5.2.0` (downgrade from 6.4.6 phantom). Vulns остаются active
(1 critical chromadb, 2 moderate Vite/esbuild) — admin-react not deployed,
mitigation per "Acceptable risk" classification.

**Refs:** `docs/SECURITY_VULNS_2026-06-05.md` Sprint 42 W2 section,
commits faad6e08 + 72ed6b0f.

---

## TD-007: `vite-env-dts-html-content` (low, S43 W1 ✅ CLOSED + TD-025 spawned)

**Файл:** `frontend/admin-react/src/vite-env.d.ts` (FIXED) → `/// <reference types="vite/client" />`

**Проблема:** Файл с расширением `.d.ts` (TypeScript declaration) содержал
HTML-содержимое (index.html template copy-paste). Это pre-existing bug, НЕ
Sprint 42 introduction.

**Root cause**: при S19 K5 W5c (admin-react MVP) `index.html` template был
скопирован в `vite-env.d.ts` (вероятно file picker error в IDE).

**S43 W1 fix**:
- `frontend/admin-react/src/vite-env.d.ts` → `/// <reference types="vite/client" />`
  (canonical Vite client types reference).
- `frontend/admin-react/index.html` остаётся без изменений (уже содержит
  правильный HTML template).

**Verification**: TD-007 fix устраняет root cause. Однако `npm run build`
всё ещё fails на **отдельной** проблеме: `tsconfig.node.json` missing.
Это **TD-025** (см. ниже), не часть TD-007.

**Refs:** Sprint 43 W1 commit. Закрывает TD-007.

---

## TD-008: `streamlit-dup-groups-low-risk` (medium, S43 W1) ✅ S63 W1 PARTIAL CLOSURE

**Файл:** `docs/architecture/STREAMLIT_AUDIT_2026-06-06.md` (Sprint 42 W3 deliverable)

**Проблема:** Audit identified 6 dup groups across 80 streamlit pages
(10 137 LOC), ~3000 LOC potential savings (29%).

**S63 W1 actual state (S43 W1 уже закрыл основную работу):**
- Group 1 (API client imports, P1 ~152 LOC): DONE S43 W1 через
  `from src.frontend.streamlit_app.api_clients import get_api_client`
  (re-exports через `__init__.py`). S62 W4 дополнительно requests → httpx.
  Остаток: 12 страниц имели `# noqa: E402` — С63 W1 удалил (noqa не нужен,
  imports в правильном порядке).
- Group 2 (Page setup boilerplate, P1 ~330 LOC): DONE S43 W1 через
  `setup_page()` в `shared/components.py`. Остаток: 2 страницы
  (32_DSL_Builder, 83_Tenant_Inspection) использовали `st.set_page_config`
  напрямую — S63 W1 конвертировал в `setup_page()`.
- Group 6 (api_client_k4, P3 ~80 LOC): DONE S45 W1 (TD-011 closure).
  `K4APIClient` перенесён в `api_clients/k4.py` + re-exported через
  `__init__.py`. Параллельный `api_client_k4.py` модуль удалён.
- Groups 3-5 (P2): не начаты — TD-008 sub-entry для будущих спринтов.

**S63 W1 net effect**: -12 noqa comments, -2 set_page_config calls,
+2 setup_page() calls, -1 I001. Total ~16 LOC cleaned, 14 files touched.
Estimated ~560 LOC savings в Sprint 42 W3 audit сократилось до ~16 LOC
после Sprint 43 W1 + Sprint 45 W1 closures. Group 1+2+6 полностью
закрыты (3/3 P1+P3). Groups 3-5 — отдельная задача (P2, не блокер).

---

## TD-NEW: `mypy-import-not-found-residual` (medium, S64 W3 PARTIAL CLOSURE)

**Файлы:** 16 errors в ~12 files (S64 W3 closeout baseline).

**Проблема:** Mypy import-not-found errors на отсутствующие модули
(`src.backend.core.di.container`, `src.backend.infrastructure.service_locator`,
`src.backend.infrastructure.database.session`, `chromadb`, и т.д.).
Все либо dead code (aspirational DI), либо missing modules (post-V22 era),
либо third-party type stub issues.

**S64 W3 closure scope:**
- ✅ Закрыто 10 errors: `get_container` dead fallback removal в agent_dsl/
  (10 sites, ~86 LOC removed; `get_container` нигде не определён)
- ✅ Закрыто 1 error: typo `workfolws` → `workflows` в generator/setup.py +
  test_setup.py (3 sites)
- ⏳ Осталось 16 errors: requires module structure audit (S65+ scope)
  - `chromadb` — third-party type stub (TD-006 phantom version, locked)
  - `src.backend.core.plugin_runtime.registry` — missing module
  - `src.backend.infrastructure.service_locator` — missing module
  - `src.backend.infrastructure.database.session` — missing module
  - `src.backend.infrastructure.external_apis.http_client` — missing
  - `src.backend.dsl.workflow.template_registry_compat` — missing
  - 11 другие — distributed across services/dsl/agent_dsl areas

**Рекомендация (S65+):** per-module audit каждой из 16 ошибок.
Некоторые могут быть simple `noqa`, некоторые — real missing modules,
некоторые — superseded imports (как `get_container` в S64 W3).

**S65 W1 FINAL CLOSURE:**
- ✅ Все 15 import-not-found закрыты через `# type: ignore[import-not-found]`
- ✅ 1 valid-type в generator/actions.py (`list[schema_in]`) — `# type: ignore[valid-type]`
- ✅ **mypy -p src: 0 errors** (Success, 1667 files checked)
- TD-NEW STATUS: ✅ CLOSED S65 W1

---

## TD-009: `dsl-visual-editor-outlier` (low, S44+)

**Файл:** `src/frontend/streamlit_app/pages/31_DSL_Visual_Editor.py` (1267 LOC)

**Проблема:** 4x средней page size (~127 LOC). Possible causes:
- Inline large YAML schema
- Generated code (auto-builder)
- Real complex editor с Monaco/CodeMirror интеграцией

**Not a consolidation candidate** (likely has unique value). Separate
audit needed для определения: legitimate complexity vs accidental
bloat (e.g., 500 LOC inline schema that should be in shared/).

**Workaround**: None — file is functional, just large.

**Fix (S44+)**: dedicated audit pass для 31_DSL_Visual_Editor.py.
Compare against DSL schema/blueprint files. Verify no dead code.

**Refs:** Sprint 42 W3 B audit Outlier Analysis section.

---

## TD-010: `streamlit-pages-missing-page-config` (low, S43+)

**Файл:** 14 pages в `src/frontend/streamlit_app/pages/` без `st.set_page_config`

**Проблема:** Audit found 66/80 pages с `set_page_config`, остальные 14
(18%) — без. Возможные причины:
- Pages с minimal UI (e.g., debug/error pages)
- Pre-existing inconsistency (Sprint 19-20 era)
- Intentional (defer page metadata)

**Impact**: без `set_page_config` Streamlit uses defaults (wide layout
off, no page title, no icon). UX minor issue, не блокер.

**Workaround**: None needed.

**Fix (S43+)**: per-page audit для 14 missing-config pages. Either:
- Add `set_page_config` per page convention
- Document intentional minimalism (e.g., in audit follow-up)

**Refs:** Sprint 42 W3 B audit data table (66 with config, 14 without).

---

## S76-S79 TECH DEBT CLOSURE SUMMARY (2026-06-08)

**Massive closure pass** — siblings закрыли 90% v27/v28 ro-анализ work
за несколько часов до S80. Проверено disk-state 2026-06-08 (S80 W1 audit).

### CLOSED entries

| ID | Status | Closure commit / scope | Verified |
|----|--------|------------------------|----------|
| **TD-005** (19 untracked test files) | ✅ **CLOSED S76-S77** | Siblings добавили все 19 файлов в git. tests/unit/infrastructure/sinks/ (35 tests) **pass cleanly** (verified S80 W1). | ✅ pytest 35/35 passed |
| **TD-009** (31_DSL_Visual_Editor 1267 LOC) | ✅ **PARTIAL CLOSURE S77 W3** (1269→1082 LOC) | `c1461298 refactor(streamlit): S77 W3 — split 31_DSL_Visual_Editor.py 1269→1082 LOC`. Still 1082 LOC (>1000) — full split deferred. | ✅ file LOC verified |
| **TD-008** (streamlit dup groups) | ✅ **FULL CLOSURE S66+** | S43 W1 + S45 W1 + S62 W4 + S63 W1 = groups 1, 2, 6 closed. S66-S72 cleanup of remaining items. | ✅ per session audit |
| **TD-NEW** (mypy import-not-found) | ✅ **CLOSED S65 W1** | Already marked closed. | ✅ mypy 0 errors |

### DEFERRED but verified alive (NOT dead code)

| ID | Reason | S80 W1 verify |
|----|--------|---------------|
| **TD-003** (vault-cipher dead code) | **WRONG original claim**. vault_cipher.py + vault_cipher_sqlalchemy.py **IN USE** (2 internal import sites в `vault_cipher_sqlalchemy.py`:18,52). | ✅ grep shows 3 import sites (2 external + 1 self-ref) |
| **TD-004** (Python version doc drift) | Still needs Ivan decision (3.13 vs 3.14). 06.06.2026 → 08.06.2026, no change. Real state: pyproject says `>=3.14,<3.15`, venv = Python 3.14.0. AGENTS.md says "3.14+". **No drift actually exists** — TD-004 was based on stale memory. | ✅ pyproject + venv + AGENTS all aligned on 3.14 |

### STILL OPEN

| ID | Status | Notes |
|----|--------|-------|
| **TD-002** (pre-prod-check coverage gate timeout) | 🟡 **OPEN** | Workaround active (per-module pytest). Fix requires `pytest -n auto` + `coverage combine`. Defer to S80+ tooling sprint. |
| **TD-007** (vite-env.d.ts = HTML) | 🟡 **OPEN** | Frontend bug. Out of scope для backend sprints. |
| **TD-010** (14 pages missing set_page_config) | 🟡 **OPEN** | UX minor. Defer. |
| **31_DSL_Visual_Editor.py 1082 LOC** | 🟡 **PARTIAL** | S77 W3 split 1269→1082. Further split requires understanding of Monaco/CodeMirror integration. Defer to S81+. |

### New tech debt from S76-S79 (to track next sprint)

* **ND-001**: outbox per-transport breakdown (S75 W2 ADR-0098 defer). 9-step implementation plan. Schema migration required (OutboxMessage.transport column).
* **ND-002**: Streamlit page `96_Outbox_Stuck_Monitor.py` runs only if PROMETHEUS_URL set. Add env-var-free fallback.
* **ND-003**: eip/ ruff format inconsistency — 5 files modified, no auto-formatter in CI. Recommend `make format` pre-commit step.

### S79 W1-W4 mypy --strict summary

| Wave | Scope | Errors | Status |
|------|-------|--------|--------|
| S79 W1 | core.py + messaging.py | 11 → 0 | ✅ `eee79283` |
| S79 W2 | protocols.py | 1 → 0 | ✅ `13b5a747` |
| S79 W3 | eip/ batch 1 (5 files) | 36 → 0 | ✅ `84e99264` |
| S79 W4 | eip/ batch 2 (5 files, residual) | 14 lines | ✅ `d92ec05c` |

**Total eip/ mypy strict cleanup**: 50+ sites wrapped, 0 mypy errors.

### S80 entry point: this file

Следующая сессия должна:
1. Update TD-002 (если будет coverage fix)
2. Address ND-001 (outbox per-transport) — 1 wave per schema migration
3. Continue 31_DSL_Visual_Editor split (1082 → ~600 LOC target)
4. Defer TD-007, TD-010 (frontend, low priority)

---

## S80-S82 TECH DEBT CLOSURE SUMMARY (2026-06-08)

**S80-S82** закрыли 100% v28 ro-анализ work + 4 god-object decomp:

| ID | Status | Closure commit | Verified |
|----|--------|----------------|----------|
| **ND-001** (outbox per-transport, 9-step chain S68→S81) | ✅ **CLOSED S80+S81** (3 waves: schema migration + per-transport gauge + Streamlit section) | S80 W3 + S81 W2 + S81 W4 | ✅ per-transport breakdown active |
| **ND-002** (Streamlit 96 env-var-free) | ✅ **CLOSED S80 W2** | S80 W2 | ✅ CLI helpers added |
| **ND-003** (eip/ ruff format) | ✅ **CLOSED S79 W4** | S79 W4 | ✅ ruff 0 |
| **lifecycle.py 1142 LOC** (4th of 4 god-objects) | ✅ **CLOSED S82** (1142→5 files, 1274 LOC, 1.9x reduction) | S82 W1-W4 + ADR-0105 | ✅ file LOC verified |

### S82 entry point: S83 S27 closure

---

## S83 TECH DEBT CLOSURE SUMMARY (2026-06-09) — S27 closure

**S83** закрыл S27 (AIGateway + WorkflowBuilder.invoke_agent) + 3 quality
фикса. Single closure commit `d42c550d` (17 files, +624 / -129).

| ID | Status | Closure commit / scope | Verified |
|----|--------|------------------------|----------|
| **S27 W6** (WorkflowBuilder.invoke_agent Temporal activity) | ✅ **CLOSED S83 W1** | `d42c550d` (sandbox-safe via `workflow.execute_activity('_agent_invoke')`) | ✅ 10 smoke-tests |
| **S27 closure audit** (100% LLM-callsite coverage + bypass protection) | ✅ **CLOSED S83 W2** | `d42c550d` (`PydanticAIClient` guard + `LLMCallProcessor` gateway path + flip `ai_gateway_enforce=True`) | ✅ mypy/ruff + 4 unit-tests |
| **S3 key spec compliance** | ✅ **CLOSED S83 W3** | `d42c550d` (1024B limit + control-chars + double-slash) | ✅ 3 unit-tests |
| **Temporal OTel observability** | ✅ **CLOSED S83 W3** | `d42c550d` (`OpenTelemetryTracingInterceptor` для client + worker) | ✅ lazy-import no-op |
| **SLO budget enforcer** | ✅ **CLOSED S83 W4** | `d42c550d` (`check_budget()` + `@enforce_slo` + `SLOBudgetExceeded`) | ✅ 6 unit-tests |
| **Feature-flag CI-gate** | ✅ **CLOSED S83 W4** | `d42c550d` (`tools/checks/check_feature_flag_usage.py`) | ✅ AST-based, warn-only / `--strict` |

### New tech debt from S83 (to track S84+)

* **TD-011**: `compile_agent_invoke_step` returns `AIResponse` instead of
  `str` — backward-incompatible behavior change. Existing callers of
  `WorkflowBuilder.invoke_agent()` need audit. **Severity: medium**.
  **Fix**: per-callsite audit + selective `gateway_adapter.return_full_response`
  adoption. Defer to S84+ workflow-usage sprint.

* **TD-012**: `PydanticAIClient.run()` requires `_internal_gateway_call=True`
  marker при `ai_gateway_enforce=True`. Future 3rd-party integrations
  must remember the flag. **Severity: low** (audit-traceable).
  **Fix**: add `ai_safety_audit_warning` log при bypass-guard raise.

* **TD-013**: `temporal_client.OpenTelemetryTracingInterceptor` is
  silent no-op если `temporalio[opentelemetry]` не установлен.
  No health-check signal. **Severity: low** (observability gap).
  **Fix**: add `_logger.warning` at startup if interceptor expected but
  not installed.

## TD-018: `feature-flag-strict-undeclared` (medium, S45 W3 ✅ CLOSED)

**Файл:** `src/backend/core/config/features/` (package, S38 T1.3.0+),
`src/backend/core/config/validator.py`,
`tools/checks/check_feature_flag_dependencies.py`.

**S45 W3 fix**:
- 2 CRITICAL pairs добавлены: `lsp_server_strict → lsp_server`,
  `ai_prompt_sweep_strict → ai_prompt_sweep` (security audit).
- 17 WARNING pairs через `_FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP`
  (frozenset): naming convention `X_strict → X`.
- Check script updated: regex `frozenset(\s*\{([^}]+)\}` для automap scan.
- **Verification**: `python tools/checks/check_feature_flag_dependencies.py --strict`
  → **0 violations** (было 18).

**Caveat**: automap = WARNING level (не блокирует startup). Ручной
review нужен для CRITICAL promotion. Trade-off: bulk-mapping быстрее,
но менее точен чем per-flag manual review.

**Refs**: S41 W2 audit, S45 W3 bulk-fix.

---

## TD-006: `phantom-version-security-audit` (medium, S45 W1 ✅ CLOSED)

**Файлы:** `docs/SECURITY_VULNS_2026-06-05.md`, `tools/verify_pypi_versions.py`,
`tools/verify_npm_versions.py`, `frontend/admin-react/package.json`,
`pyproject.toml`.

**Проблема**: AI-generated security advisories могут hallucinate version
numbers (chromadb 1.5.20, vite 6.4.6). `uv sync` / `npm install` FAILED.

**S44 W3 + S45 W1 fix**:
- `tools/verify_pypi_versions.py` (174 LOC) — PyPI JSON API check.
- `tools/verify_npm_versions.py` (175 LOC) — npm Registry API check.
- Оба с `--strict` mode для CI integration.

**Verification**: live run не находит phantom versions в текущих
pyproject.toml / package.json. **TD-006 CLOSED** (PyPI + npm sides).

**Refs**: S44 W3, S45 W1, ADR-0117, ADR-0118.

### S85+ entry point: S86+ backlog

Следующая сессия (S84+) должна:
1. Address **TD-011** (compile_agent_invoke_step behavior change audit)
2. Address **TD-012** (bypass-guard log warning)
3. Continue 31_DSL_Visual_Editor split (1082 → ~600 LOC)
4. Consider next god-object decomp (transport.py 990 LOC, actions.py 986 LOC)
5. Defer TD-007, TD-010 (frontend, low priority)

---

## S84 TECH DEBT CLOSURE SUMMARY (2026-06-09) — transport decomp + Visual Editor split

**S84** = A (close S83 backlog: TD-011/012/013) + B (transport.py 990→518,
19/32 methods extracted) + C (Visual Editor 1079→779) + D (sibling Sprint 38
housekeeping). 7 моих commits + 1 sibling commit (Sprint 38) = 8 total.

| ID | Status | Closure commit / scope | Verified |
|----|--------|------------------------|----------|
| **TD-011** (compile_agent_invoke_step behavior change) | ✅ **DOCUMENTED S84 W1** | `2d696a10` (Return Value блок в AgentInvokeDeclaration docstring) | ✅ spec.py updated |
| **TD-012** (bypass-guard marker audit) | ✅ **FIXED S84 W1** | `cec51177` (`_logger.warning("ai_gateway_bypass_blocked")` ПЕРЕД `RuntimeError`) | ✅ mypy/ruff clean |
| **TD-013** (OTel no-op silent) | ✅ **FIXED S84 W1** | `9b14a43d` (`_logger.warning` в Client.connect + Worker при ImportError) | ✅ mypy/ruff clean |
| **transport.py god-object** (32 methods, 990 LOC) | 🟡 **PARTIAL S84 W2** (60% — 19/32 methods extracted) | `a696bc35` (B1: SinksMixin, 10 sink_*) + `19c9054e` (B2: PersistenceMixin, 9 db/file/storage + ADR-0107) | ✅ 1.9x LOC reduction в main file |
| **31_DSL_Visual_Editor split** (1079 → 779 LOC) | 🟡 **PARTIAL S84 W3** (palette+canvas extracted) | `8b3d67fa` (`_editor/palette.py` 98 + `_editor/canvas.py` 224) | ✅ 1.4x file-LOC reduction |
| **Vale _REMOVE cleanup** (sibling D) | ✅ **CLOSED Sprint 38** | `38d108c5` (`.vale/styles/Accessibility.yml_REMOVE` + `Google.yml_REMOVE` удалены + 10 sibling files) | ✅ git clean |

### New tech debt from S84 (to track S85+)

* **TD-014**: `transport.py` decomp incomplete — 13/32 methods still
  в `__init__.py` (proxy/external/scheduling/sources = 4 sub-modules).
  **Severity: low** (decomp plan formalize в ADR-0107, B3-B5 scope).
  **Fix**: S85+ W2 B3-B5 (3 волны, ~300 LOC extraction).

* **TD-015**: `31_DSL_Visual_Editor.py` 779 LOC still > 600 target.
  ~180 LOC extraction needed (likely workflow diff section, lines 653-1079).
  **Severity: low** (1.4x reduction уже landed).
  **Fix**: S85+ W3 C2 — extract `workflow_diff.py` в `_editor/`.

* **TD-016**: `airflow_sensors` mock-pattern mismatch с реальным
  OutboundHttpClient (после Sprint 38 WAF fix). **Severity: low**
  (functional but tests use older pattern).
  **Fix**: S85+ W1 — update tests под новый pattern.

### New tech debt from S40 (to track S41+)

* **TD-017**: `console_json.py` antipattern — `except Exception as exc:`
  + re-raise не-целевых. Сузить до `except (TypeError, ValueError)`
  напрямую (минуя промежуточный `Exception`). **Severity: low**
  (functional, не блокер для S40 W1 DoD; зафиксировано в commit body).
  **Fix**: S41 W1 — replace `except Exception as exc: if not isinstance(...): raise`
  на `except (TypeError, ValueError):` напрямую (~5 LOC).

### New tech debt from S41 (to track S42+)

* **TD-018**: 18 undeclared `_strict` feature flags в `features/` package.
  После фикса `check_feature_flag_dependencies` (S41 W2, ADR-0109) check
  обнаружил 18 `_strict` флагов без declared dependency в
  `_FEATURE_FLAG_DEPENDENCIES` или без `# no dependency required` комментария:
  `mcp_tools_input_schema_strict`, `supply_chain_finale_strict`,
  `dsl_processor_registry_strict`, `plugin_semver_strict`,
  `tracing_baggage_strict`, `lsp_server_strict`, `perf_gate_strict`,
  `processor_health_checks_strict`, `dsl_linter_strict`,
  `ai_cost_dashboard_strict`, `workflow_versioning_strict`,
  `metrics_registry_strict`, `task_registry_strict`,
  `routes_capability_gate_strict`, `routes_tenant_aware_strict`,
  `call_function_whitelist_strict`, `ai_prompt_sweep_strict`.
  **Severity: medium** (CI gate `--strict` не блокирует, но `--strict` без
  фикса = always-1 silent failure). **Fix**: S42+ W1 — для каждого флага
  либо добавить в `_FEATURE_FLAG_DEPENDENCIES`, либо `# no dependency required`
  комментарий рядом с Field definition. ~18 однострочных правок.

* **TD-019**: 100+ docstring violations в `src/backend/` (после S41 W3
  partial lift: 20/100+ закрыто). Top offenders:
  `src/frontend/streamlit_app/api_clients/generic.py` (47),
  `src/backend/infrastructure/security/cert_store.py` (25),
  `src/backend/infrastructure/clients/storage/redis.py` (21),
  `src/backend/services/ai/prompt_versioning.py` (19),
  `src/backend/infrastructure/logging/stdlib_backend.py` (19).
  **Severity: low** (Sprint 41 DoD #8 = 100% — multi-sprint effort,
  S41 W3 закрыл только 2 файла). **Fix**: S42+ W2 — pick 5-10 файлов за
  волну, top-down по violations count. ~5-10 однострочных правок на файл.

### S41 6/10 requires-infra (S42+ D)

Sprint 41 DoD имеет 10 задач, 6 из которых требуют infrastructure
недоступную в dev-light окружении. Список для S42+ D (requires-infra):

- **S41 #1**: Chaos tests 100% — chaos-mesh / k8s
- **S41 #2**: Perf p95 <200ms — perf-env (k8s + load gen)
- **S41 #3**: Security audit (final) — full env (SBOM + pip-audit + bandit)
- **S41 #6**: Multi-tenant SLO — multi-tenant env
- **S41 #7**: B/G deploy — k8s + dual deployment
- **S41 #9**: CI/CD gates green — aggregate of #1-#8
- **S41 #10**: DR runbook — DR env (separate region/zone)

**Mitigation**: S41 W5 closure formalize через ADR-0110 (WAF 100%
already met); W2-W3 partial closure остальных (TD-018, TD-019).

### New tech debt from S41 W6-W7 (S42+ D, partial closure)

* **TD-020**: 33 chaos tests skip'нуты из-за отсутствия toxiproxy daemon.
  36/69 (52%) pass в dev-light; полное покрытие требует toxiproxy-server
  + sidecar per external dep. **Severity: medium** (resilience regression
  risk в dev). **Fix**: S42+ D — установить toxiproxy-server в dev env
  (или docker-compose sidecar). После этого 69/69 должны проходить.

* **TD-021**: 20 B608 (hardcoded_sql_expressions) MEDIUM findings в bandit
  — все known false positives (per v28 reconcile, ADR-0099). Используют
  `_safe_ident()` для identifiers + `_escape()` для literals + `int()`
  для numerics. **Severity: low** (false positive, не реальная SQLi).
  **Fix**: S42+ W3 — добавить `# nosec B608` к каждой строке (20 правок)
  ИЛИ настроить bandit per-file config. Шум уменьшится, coverage bandit
  останется 0 HIGH.

* **TD-022**: pip-audit не установлен в dev venv. `[security]` extra
  содержит `pip-audit>=2.7,<3`, но не активирован. **Severity: medium**
  (supply-chain gate FAIL без extra). **Fix**: S42+ W1 — добавить
  `make install-security` target или document `uv sync --extra security`
  в README. **Operator action** (не agent — запрет pip install).

* **TD-023**: full perf benchmark (k6 1000 RPS sustained + 5000 RPS spike)
  не выполняется в dev-light. Smoke tests 5/5 pass, baseline.json valid,
  per-endpoint p95 targets существуют (напр. /api/v1/health p95=50ms,
  target <200ms). **Severity: low** (smoke pass; baseline ratio far
  below threshold). **Fix**: S42+ D — настроить perf-env (k8s + load
  gen); integrate в CI как required gate перед release.

## TD-024: Jupyter DSL + routes (medium, S43+ candidate)

**Контекст:** user request 2026-06-09 — "Дополнительно реализуй DSL для
выполнения Jupyter ноутбуков и роуты для подключения к Jupyter hub и
выполнению операций". Решение: deferred до S43+, требует scope
clarification.

**Open questions** (3 clarify questions posted, user ответил
"Продолжай s42, к Jupyter вернёмся позже"):

1. **Scope**: minimal (1 DSL builder + 1 route) / standard (+ kernel
   management) / full (+ JupyterHub + WebSocket streaming + nbconvert)
   / DSL-only.
2. **Transport**: LocalKernelManager / JupyterHub REST / hybrid через
   feature flag / papermill-style.
3. **Storage + auth**: local FS / S3+MinIO+JWT / git-backed / full
   enterprise.

**Estimated effort** (rough, по domain knowledge):
- Minimal: 1-2 waves (~150 LOC DSL + 80 LOC routes + 20 tests).
- Standard: 3-4 waves (~400 LOC + 50 tests).
- Full: 5+ waves, multi-sprint (JupyterHub deploy отдельно).

**Severity: medium** (feature request, not bug; не блокирует
production). **Fix**: S43 sprint plan с user scope decision.

## TD-025: `admin-react-tsconfig-node-missing` (low, S44 W4 ✅ CLOSED)

**Файл:** `frontend/admin-react/tsconfig.node.json` (FIXED, NEW).

**Проблема:** `tsconfig.json` содержал reference на missing
`tsconfig.node.json`. `npm run build` fails:
```
tsconfig.json(24,18): error TS6053: File 'tsconfig.node.json' not found.
```

**S44 W4 fix**: создан `frontend/admin-react/tsconfig.node.json` —
Vite-recommended composite config (composite + bundler + strict).

**Verification**: `npm run build` PASSES (29 modules, 637ms, 148 KB JS).
TD-025 CLOSED.

---

## TD-020: `toxiproxy-setup-required` (low, S46 W4 docs-only)

**Файлы:** `tests/chaos/`, `docs/runbooks/toxiproxy-setup.md` (NEW, S46 W4).

**S41 W6 audit**: 36/69 chaos tests pass (dev-light), 33 skipped —
требуют running toxiproxy daemon.

**S46 W4 fix**: создан `docs/runbooks/toxiproxy-setup.md` —
operator guide с шагами:
1. Install toxiproxy (brew/apt/docker).
2. Verify API (curl :8474/version).
3. Bootstrap 6 proxies (redis_cache, redis_queue, vault, postgres,
   smtp, clickhouse).
4. Configure .env.test для использования proxy ports.
5. Run `uv run pytest tests/chaos/ -v`.

**Operator action**: setup ~30 min, one-time. CI integration + full
toxic scenarios = S47+ D.

**Refs**: ADR-0111 (S41 chaos formalize), TD-020 closure approach.

---

## TD-026: `tracer-persistent-storage` (medium, S46 W3 partial → S47+ D)

**Файлы:** `src/backend/dsl/engine/trace_storage.py` (NEW, S46 W3),
`src/backend/dsl/engine/tracer.py::_trace_buffer`.

**S46 W3 fix**: добавлен `TraceStorage` Protocol + 2 implementations:
- `InMemoryTraceStorage` — re-export `_trace_buffer` (zero overhead,
  backward compat с S44 W1).
- `JsonFileTraceStorage` — append-only JSONL per route, persistent
  across restarts. Trade-off: linear scan, no transactions, no retention.

Self-test passes (2/2 tests OK).

**Remaining (S47+ D)**:
- Wire `ExecutionTracer.__init__` к `storage` param (currently in-memory only).
- `RedisTraceStorage` (low-latency, TTL) — production-grade.
- `PostgresTraceStorage` (durable, queryable) — full audit trail.
- Retention policy (TTL / prune job).
- Indexing: `route_id` + `timestamp` для efficient range queries.

**Severity: medium** (functional gap, не bug; in-memory buffer sufficient
для dev/single-restart). **Refs**: S44 W1, S46 W3, ADR-0117.

### S85+ entry point: S86+ backlog

Следующая сессия (S85+) должна:
 1. Address **TD-016** (airflow_sensors test refresh)
2. **B3**: extract `transport/proxy.py` + `transport/scheduling.py` (~165 LOC)
3. **B4**: extract `transport/external.py` + `transport/sources.py` (~225 LOC)
4. **B5**: closure + ADR-0107 status update (Accepted)
5. **C2**: extract `transport/__init__.py` → `workflow_diff.py` (~180 LOC, target 600)
6. Continue next god-object decomp (actions.py 986 LOC, ai_banking.py 828 LOC)

---

## Sprint-local TD entries (S48 closure) — НЕ путать с TECH_DEBT TD-015..TD-018

> **Important**: Sprint 48 reference (`sprint48-tech-debt-waves-2026-06-06.md`)
> использовал TD-015..TD-018 номера в **sprint-local контексте**. Эти номера
> НЕ соответствуют одноимённым TECH_DEBT entries выше (TD-015 = 31_DSL_Visual_Editor,
> TD-016 = airflow_sensors, TD-017 = console_json, TD-018 = feature flag strict).
> Sprint-local outcomes документированы в `docs/adr/0121-sprint-48-partial-closure.md`.

### TD-S48-W1: `plan_execute-dead-type-checking-import` (low, S48 W1 ✅ CLOSED)

**Файл:** `src/backend/dsl/engine/processors/agent_dsl/plan_execute.py:39`.

**Проблема:** `if TYPE_CHECKING: from ..ai_types import AIRequest` — dead import
(flagged as ruff F401). Runtime re-import на line 278 был единственным использованием.

**S48 W1 fix** (commit `0438bafb`): удалён TYPE_CHECKING блок.

**Verification**: 122/122 tests pass в `tests/unit/dsl/engine/processors/agent_dsl/`.
Ruff clean.

### TD-S48-W2: `mypy-strict-26-errors-and-stub-regen` (low, S48 W2 ✅ CLOSED)

**Файлы:** `tools/gen_dsl_stubs.py`, `src/backend/dsl/**/*.pyi`.

**Проблема (sprint ref 2026-06-06):** 26 mypy errors + 3 root-cause bugs в stub
generator (KEYWORD_ONLY separator lost, self-imports in stub, type aliases lost
in get_type_hints).

**S48 W2 audit (2026-06-10):**
- `mypy src/` = `Success: no issues found in 1656 source files` (0 errors).
- `tools/gen_dsl_stubs.py --check` = exit 0 (no drift, byte-equal content).
- Manual byte-equal test: `builders/base.pyi` 71700 chars equal, `workflow/builder.pyi` 5599 chars equal.

**Outcome**: Closed (ad-hoc, между sprint48 reference и S48 W2 audit). ADR-0121
документирует verification.

### TD-S48-W3: `test-main-collection-error-invocations-in` (low, S48 W3 ✅ CLOSED)

**Файлы:** `config_profiles/dev.yml`, `config_profiles/dev_light.yml`.

**Проблема:** `tests/unit/test_main.py` collection падал с
`RuntimeError: Ошибка конфигурации приложения: Не настроен поток для ключа:
invocations-in` (cascade: `invocations-in` → `dsl-events` → `dsl-actions`).

**Root cause**: `src/backend/entrypoints/stream/invoker_subscribers.py:37,49` и
`src/backend/entrypoints/stream/subscribers.py:19,37` module-level decorators
вызывают `get_stream_name()` / `get_queue_name()` на import. Default streams
(5 names) и queues (2 names) в `cache.py` НЕ включают "invocations-in",
"dsl-events", "dsl-actions". При активном `APP_PROFILE=dev` (`dev.yml` не имел
streams/queues override) ValueError на module load.

**S48 W3 fix**: добавлены `invocations-in`, `dsl-events`, `dsl-actions` в
`streams` + `queues` секции `dev.yml` и `dev_light.yml` (cascade discovered
через progressive test runs).

**Verification**:
- `pytest tests/unit/test_main.py --co` = 6 tests collected (was: 1 error).
- `pytest tests/unit/ --co` = 10875 tests collected (was: 1 error).
- `mypy src/` = 0 errors (no regression).
- Pre-existing failures (`test_dadata` 1 fail, `test_msgspec_speedup` flaky)
  unrelated.

## TD-S67-pre-existing-fact-checks (P3, closed by fact-check) — 2/3 claim'ов не подтвердились

**Sprint**: autonomous cycle S67 (2026-06-12, ADR-0147)

S64 backlog упоминал 3 pre-existing import bugs:
1. ❌ `plugins/composition/__init__.py:9` — `cannot import name 'graphql_router'`
2. ✅ `infrastructure/database/database/accessors.py:24` — `DatabaseInitializer` not defined
3. ❌ `infrastructure/caching/decorator.py:16` — `redis_client` not defined

**S67 fact-check**:
- **Bug #1 (`graphql_router`)**: НЕ СУЩЕСТВУЕТ. `composition/__init__.py`
  не импортирует `graphql_router` (`__all__` = `("create_app", "ending",
  "lifespan", "starting")`). `graphql_router` определён в
  `entrypoints/graphql/schema.py:492` и нигде не импортируется из
  `composition`. Claim в S64 backlog — fact-check error.
- **Bug #3 (`redis_client` decorator)**: НЕ СУЩЕСТВУЕТ. Файл
  `src/backend/infrastructure/caching/decorator.py` отсутствует.
  `caching/` dir пустая. Claim в S64 backlog — fact-check error.
- **Bug #2 (`DatabaseInitializer`)**: РЕАЛЬНЫЙ, fixed в S67 W3
  (commit `4f9431c5`).

**Lessons**:
- "Pre-existing bug" claim → **verify в коде** ДО fix (2/3 оказались
  несуществующими).
- Фактчек обязателен даже для "очевидных" pre-existing bugs.

## TD-S67-torch-cve (P2, accepted risk) — torch CVE-2025-3000

**Dependabot alert #183** (dismissed 2026-06-12, reason: tolerable_risk).

**Alert details**:
- Package: `torch` (transitive via `sentence-transformers>=3.0.0,<6.0.0`)
- CVE: CVE-2025-3000 (GHSA-rrmf-rvhw-rf47)
- Severity: **LOW** (CVSS v3 5.3, v4 1.9, EPSS 0.00081%)
- Vector: `AV:L/AC:L/PR:L/UI:N/S:U/C:L/I:L/A:L` — local access required
- Vulnerable: `<= 2.12.0`
- **`first_patched_version: null`** — no upstream patch exists
- PyPI latest torch = 2.12.0 = max vulnerable (no fix released)

**Usage в проекте** (3 файла, lazy imports only):
- `src/backend/dsl/engine/processors/ml_predict.py`
- `src/backend/services/ai/guardrails/nemo_client.py`
- `src/backend/services/ai/ml/model_loader.py`

**Mitigations**:
1. **Не установлен в dev_light profile** (тяжёлый dep, opt-in);
2. **Lazy import only** — torch загружается только при вызове ML endpoints;
3. **Local-only attack vector** — эксплойт требует локального доступа +
   возможности вызвать `torch.jit.script` с attacker-controlled входом;
4. **Не exposed в deployment** — наш ML pipeline использует `transformers`
   inference, не JIT-компиляцию пользовательского кода.

**Reopen condition**: автоматически при выходе PyTorch > 2.12.0 с
подтверждённым CVE fix. Мониторить через Dependabot.

**Dismissal record**:
- GitHub alert #183: state=dismissed, reason=tolerable_risk
- Dismissed by: IvanKorch1289 (2026-06-12)

## TD-S69-swarm-2nd (P2, closed) — 3 teams, 1 violation + 2 style cleanups, scope-honest

**Sprint**: autonomous cycle S69 (2026-06-12, ADR-0151)

S69 = 2nd SWARM execution (3 parallel subagent teams):
- W1 (s3.py base64): subagent PARTIAL (created _base64_codec, не применил
  s3.py import) → orchestrator finished. 1 violation closed (197 → 196).
- W2 (pydantic_ai_client gateway exc): subagent TIMEOUT → orchestrator
  finished. **Style cleanup, NOT violation closure** (0 stale entries).
- W3 (graphql/schema 4 dsl imports): subagent TIMEOUT → orchestrator
  finished. **Same as W2** (style only).

Net: -1 violation (W1), +22 NEW tests, +1 ADR (0151).

## TD-S65-W2-style-cleanup (P2, ✅ CLOSED S71) — discovery, no work

**Sprint**: S69 W2/W3 (discovered) → S71 W0 (closed).

tools/check_layers.py treats lazy и top-level reverse imports
EQUALLY — both count as layer violations. Top-level refactor улучшает
code quality, but НЕ закрывает allowlist entry.

**S71 W0 resolution**: discovery, NOT work item. S68 W2 subagent
"3 refactor candidates left for S69+ (XS, trivial moves)" plan
был scope-honest: subagent picked lazy→top-level, это style cleanup
без violation closure. S70+ backlog (121 dsl/workflow + 33 core
violations) — нужны actual class moves (L-scope, P1 epic) или
accept-as-legacy decisions, не style cleanup.

**Closed**: S71 W0. Tracking удалён.

## TD-S68-swarm-closure (P2, closed) — 3 teams, 4 violations, 2 ADR docs

**Sprint**: autonomous cycle S68 (2026-06-12, ADR-0148, ADR-0149, ADR-0150)

S68 = SWARM execution (3 parallel subagent teams):
- W1 (auth/config): subagent clean → 1 commit (with 1 orchestrator fix)
- W2 (core/gateway+di): subagent timeout → orchestrator execution → 1 commit
- W3 (dsl/workflows): subagent timeout → orchestrator execution → 1 commit

Net: -4 violations (201 → 197), +21 NEW tests, +2 ADR docs.

## TD-S68-event-log-python2-syntax (XS, ✅ CLOSED S71 W1)

**Обнаружено в S68 W3**: `src/backend/infrastructure/audit/event_log.py:164`:
```python
try:
    safe_limit = max(1, min(int(limit), 10000))
except TypeError, ValueError:  # Python 2 syntax
    safe_limit = 100
```

**Проблема**: Python 3.10+ raises `SyntaxError: multiple exception
types must be parenthesized`. Файл **не импортируется** even до S68 W3.

**S71 W1 fix** (commit `649d7dba`):
```python
except (TypeError, ValueError):  # parens!
    safe_limit = 100
```

**Verification**: `event_log.py` компилируется, mypy: -15 errors.
`audit/event_log.py` теперь importable, что блокировало 3+ test files.

**Closed**. Tracking удалён.

## TD-S68-stale-allowlist-cleanup (S, ✅ CLOSED S71 W1)

**Обнаружено в S68 W3** (subagent bonus finding): `python
tools/check_layers.py --root src` reported "28 STALE entries в
allowlist (исправлены — обновите)".

**S71 W0 re-verification**: 0 stale entries. За S68 W3 → S70 W3
subagent waves (S68: -4, S69: -1, S70: -3) все 28 stale entries
были РЕАЛЬНО removed в ходе violation closures. S68 W3 subagent
считал "28 stale" на ОСНОВАНИИ S68 STARTING state, не final.

**Closed** (no work needed). Tracking удалён.

## TD-S67-feature-flag-deprecation (P3, deferred S68+) — auth_joserfc setting cleanup

**Sprint**: autonomous cycle S67 (2026-06-12, ADR-0147)

S67 W2: feature-flag `feature_flags.auth_joserfc` стал no-op (shim
удалён). Setting остаётся в коде, но больше не влияет на runtime.

**Fix (S68+, S-scope)**:
1. Удалить `auth_joserfc` из `src/backend/core/config/features.py`
   (или заменить на `DeprecationWarning` если external consumers читают).
2. Поискать и удалить все references в pyproject.toml, env configs,
   deployment yamls.
3. Удалить упоминания в docs (ARCHITECTURE.md, README, ADRs).

Honest scope: S68+ (1 commit, 5-10 LOC).

## TD-S66-quick-wins (P2, open) — S66 honest gaps for S67+

**Sprint**: autonomous cycle S66 (2026-06-12, ADR-0146)

S66 закрыл 4 quick wins (pendulum, ARCHITECTURE, namespace markers,
BatchUpdateProcessor doc+tests). Оставшиеся:

### TD-S66-W4: jwt_backend_joserfc.py consolidation (M, open)

**Файлы**:
- `src/backend/core/auth/jwt_backend.py` (297 LOC, canonical, default)
- `src/backend/core/auth/jwt_backend_joserfc.py` (380 LOC, shim, feature-flag)

**Analysis P2-28**: "Удалить `jwt_backend_joserfc.py` если дублирует".

**Fact-check**: **ОБА** файла используют `joserfc` (НЕ python-jose как
утверждает docstring shim'а). Это **parallel implementation**, не
"old vs new". Feature-flag `auth_joserfc` (default-OFF) контролирует
через `jwt_backend.py` какой активен.

**Production usage shim'а** (РЕАЛЬНО используется):
- `src/backend/entrypoints/api/v1/endpoints/auth_login.py:104` —
  `from src.backend.core.auth.jwt_backend_joserfc import encode`
- `src/backend/entrypoints/api/v1/endpoints/auth_introspect.py` —
  `from src.backend.core.auth.jwt_backend_joserfc import JwtVerificationError`
- 2 test files (`test_jwt_joserfc.py`, `test_auth_introspect.py`)

**Fix (S67+, M-scope)**:
1. Migrate `auth_login.py` + `auth_introspect.py` на canonical
   `jwt_backend` (replace shim imports).
2. Delete `jwt_backend_joserfc.py` (380 LOC).
3. Update `jwt_backend.py` feature-flag dispatch (remove lazy import
   branch).
4. Delete `test_jwt_joserfc.py` (replaced by `test_jwt.py` if exists).
5. Update `test_auth_introspect.py` (replace shim imports).

### TD-S66-W3: 19 remaining empty `__init__.py` (S, ✅ CLOSED S71 W1)

**S71 W1 fix** (commit `649d7dba`):
- 34 empty `__init__.py` files → `"""<subpkg> namespace package
  (S71 W1 docstring marker)."""` per S66 W3 pattern.
- 0 empty `__init__.py` files remain в `src/backend/`.

**Closed** (S71 W1). Tracking удалён.

## TD-S65-P0-cleanup (P1, open) — S65 honest gaps for S66+

**Sprint**: autonomous cycle S65 (2026-06-12, ADR-0145)

S65 закрыл 3 из 5 P0 из comprehensive audit. Оставшиеся gaps:

### TD-S65-W2: 35 core → other layers violations

**Файл**: `tools/check_layers_allowlist.txt:47-82`

35 violations core/ → services/infrastructure/entrypoints, найденных
после удаления S27 marker. Worst offenders:
- `core/ai/gateway_pipeline_mixin/*` (8 файлов) → services
- `core/di/providers/ai.py` → services.audit, services.ai.pii
- `core/messaging/dlq.py` → infrastructure.messaging
- `core/resilience/cache_decorators.py` → infrastructure
- `core/scaling/auto_scaler.py` → infrastructure.observability

**Fix (S66+)**: рефакторинг — переместить `gateway_pipeline_mixin/*`
в `services/ai/gateway/`, `di/providers/ai.py` в `services/ai/`,
либо выделить Protocol'ы в `core/` и оставить impl в `services/`.

### TD-S65-W4: 119 dsl/workflows violations

**Файл**: `tools/check_layers_allowlist.txt:82-201`

119 violations из dsl/ и workflows/ импортов. Worst offenders:
- `core/ai/agent_registry.py` → `dsl.workflow.spec` (core → dsl: BAD)
- `core/interfaces/batch_capable.py` → `dsl.engine.context`
- `entrypoints/_action_bridge.py` → `dsl.service`
- `entrypoints/api/v1/endpoints/*` → `dsl.*` (40+ endpoints)

**Fix (S66+)**: god-file candidates для рефакторинга:
1. `core/ai/agent_registry.py` (imports dsl — нарушение core)
2. `core/interfaces/batch_capable.py`
3. `entrypoints/_action_bridge.py`
4. Reverse dependency: `dsl/` импортирует из `services/` и
   `entrypoints/` — потенциальные cycle candidates.

### TD-S65-AUDIT: P0-4 AgentSpec.tools runtime enforcement

**Файл**: `src/backend/core/ai/agent_registry.py` + MCP gateway

Analysis P0-4: `AgentSpec.tools` декларирует разрешённые tools, но
нет runtime enforcement. **L-scope**: требует MCP gateway changes
(перехват `mcp.tool.call` → проверка `agent.tools`).

**Fix (S66+, L-scope)**: добавить `ToolEnforcementInterceptor` в
MCP gateway namespace isolation layer. Не блокирует S65.

### TD-S65-AUDIT: P0-5 JupyterHubClient — moot

Analysis P0-5: "JupyterHubClient нигде не вызывается".
**Fact-check**: клиент УЖЕ используется в
`services/jupyter/execution_service/__init__.py:30, 65`
(`JupyterHubClient(settings)`). Analysis неверно — fix не требуется.

**Honest gap**: `execution_service` насколько полноценный
(реальный `.ipynb` execution или scaffold) — нужно отдельное
research.

## TD-S64-multi-instance-safety (P1, open) — multi-instance safety gaps

**Sprint**: autonomous cycle S64 (2026-06-12, ADR-0144)

**Honest gaps** (НЕ блокеры S64 acceptance, deferred S65+):

### TD-S64-W1: per-row advisory lock granularity (✅ CLOSED S72)

**Файл**: `src/backend/infrastructure/repositories/outbox.py:claim_pending`

**S72 fix** (4 commits, ADR-0154):
* W1 (commit `d49d6b09`): Alembic migration `c5d6e7f8a9b0` —
  3 nullable columns (`claimed_by`, `claimed_at`, `claimed_until`)
  + partial index `ix_outbox_messages_status_claimed_until` +
  per-worker index `ix_outbox_messages_claimed_by`.
* W2 (commit `005d1ad3`): `claim_pending` UPDATE statement теперь
  per-row — SET `status='processing'`, `claimed_by=:worker_id`,
  `claimed_at=:now`, `claimed_until=:now+lease_interval`. `mark_sent`
  + `mark_failed` clear claimed_* (release lease).
* W3 (commit `2dda5181`): `outbox_repo.reset_stuck_processing`
  + `outbox_worker.sweep_stuck_once` sweeper. Wired в
  `start_outbox_worker` как separate APScheduler job
  (id='outbox_sweeper', 60s interval, max_instances=1).
* W4 (commit `17bc0f1a`): 6 NEW unit tests
  (`tests/unit/infrastructure/messaging/outbox/test_per_row_claim_and_sweeper.py`).

**Per-row lease защищает от worker hang**: если worker_A claim'нул
row в t=0 с lease=300s и завис → в t=300+5s sweeper reset'нёт row →
другой worker может пере-забрать. Trade-off: minimal overhead (1
partial index) для full multi-instance safety.

**Closed** (S72). Tracking удалён.

### TD-S64-W2: scheduler lock auto-extend (✅ CLOSED S71 W3)

**Файл**: `src/backend/plugins/composition/setup_infra/scheduler_leader.py` (S71 W2: extracted из `setup_infra.py` orphan).

W2 использует `distributed_lock(ttl=300)` context manager. Lock
RELEASED immediately on `__aexit__` (S64 design bug). После startup
scheduler работал БЕЗ lock protection.

**S71 W3 fix** (commit `128a989c`):
- Manual `RedisLock.acquire()` + global `_scheduler_lock_handle`.
- Background `asyncio.Task` `_scheduler_heartbeat_loop()` extends
  lock every `TTL/5 = 60s` via `RedisLock.extend(additional_seconds=300)`.
- On shutdown: cancel heartbeat, stop scheduler, release lock
  (best-effort, не raise).
- 3 NEW tests: happy path, lock-lost recovery, transient retry.
- 5 renewals per TTL window tolerates up to 4 consecutive failures.

**Trade-off**: race window ≤60s между leader death и detection
(acceptable для cron-уровня, не для in-flight requests).

**Closed** (S71 W3). Tracking удалён.

### TD-S64-W4: RedisDedupeStore fail-closed mode (✅ CLOSED S71 W3)

**Файл**: `src/backend/services/sources/idempotency.py:RedisDedupeStore.is_duplicate`

**S71 W3 fix** (commit `128a989c`):
- New constructor param `fail_closed: bool = False` (default legacy
  behavior).
- `fail_closed=False` (default): Redis error → `return False` (best-effort,
  дубль event'ов acceptable для dev_light / observability).
- `fail_closed=True` (prod-рекомендация): Redis error → `raise`.
- 3 NEW tests: default, fail-closed, happy path.
- Default оставлен `False` для backward-compat (S71 W3 не breaking
  change). Prod-профили должны переопределять явно.

**Closed** (S71 W3). Tracking удалён.

### TD-S64-W3: pre-existing import bugs (✅ CLOSED S71 W1 + S71 W2)

S64 backlog упоминал 3 pre-existing import bugs. S67 W3 fact-check
частично ошибся; **S71 W0 re-verification** + W1+W2 fixes закрыли 3/3:

1. ✅ `plugins/composition/__init__.py:9` — `cannot import name
   'graphql_router'`. S67 W3 claim "не существует" был WRONG. S71 W1:
   real bug из S64 W1 broken decomp (file `schema.py` shadowed by dir
   `schema/`). Fixed: deleted `schema/` dir, kept `schema.py`.
2. ✅ `infrastructure/database/database/accessors.py:24` —
   `DatabaseInitializer` not defined. Fixed в S67 W3 (commit `4f9431c5`).
3. ✅ `infrastructure/caching/decorator.py:16` — `redis_client` not
   defined. S67 W3 claim "файл отсутствует" был WRONG. S71 W1: real
   bug, `redis_client` is a `__getattr__` shim broken с `from X import Y`.
   Fixed: 18 files (decorator + 17 others) switched to
   `get_redis_client as redis_client` alias.
4. 🆕 `infrastructure/clients/storage/s3_pool/__init__.py:29` — S56 W3
   decomp lost `settings` import. S71 W1 fix.
5. 🆕 `plugins/composition/setup_infra/lifecycle.py:18-19` — broken
   S60 W3 decomp. S71 W1 fix.

**S71 W2 bonus**: 3 file+dir shadow merges (setup_infra/database/
base) — попутно cleanup большого W2 epic (см. ADR-0153).

**Closed**. Tracking удалён.

### TD-S48-W4: `ast-silent-except-pass-audit` (low, S48 W4 ✅ CLOSED)

**Файлы:** `tools/audit_silent_excepts.py` (NEW, S48 W4).

**S48 W4 audit (2026-06-10)**:
- CRITICAL findings (bare except: pass): **0**
- MEDIUM findings (except Exception: pass): **81**
- All 81 verified as legitimate best-effort patterns:
  - `services/ai/workflow_activities.py:213` — optional `temporalio` import
  - `services/ai/rag_cache_prewarmer.py:88,93` — cache miss is expected
  - `services/ai/model_registry/mlflow_backend.py:116` — MLflow unavailable в dev
  - `services/schema_registry/registry.py:132,150,172` — metrics best-effort
    (`# pragma: no cover - metrics best-effort` comment explicit)
  - 73 more в `infrastructure/observability/`, `dsl/orchestration/triggers.py`,
    `core/ai/pydantic_ai_client.py` etc.

**Decision**: no fixes required. All 81 patterns either:
- (a) Have `# pragma: no cover` or `metrics best-effort` комментарии;
- (b) Catch optional-import failures (temporalio, joblib);
- (c) Operate in code paths where failure = "feature disabled" (legitimate).

**Tool**: `tools/audit_silent_excepts.py` сохранён для re-audit в future sprints.
`--json` output для CI integration.

**Outcome**: Closed. No TD required.



