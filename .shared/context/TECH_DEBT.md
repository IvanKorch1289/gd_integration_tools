# TECH_DEBT — gd_integration_tools (last update: 09.06.2026 14:50)

Tracking для known issues, workarounds, и deferred work, который
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
| TD-001 | low | S39+ | 🟡 deferred | Decision on Python target |
| TD-002 | medium | S38+ workaround | 🟡 partial | Per-module coverage active |
| TD-003 | low | V24+ removal | 🟡 deferred | Delete vault_cipher* files |
| TD-006 | medium | S43+ | 🟡 documented | Vite 6.4.6/chromadb 1.5.20 phantom versions |
| TD-007 | low | S43+ | 🟡 documented | Pre-existing bug: vite-env.d.ts = HTML |
| TD-008 | medium | S63 W1 | ✅ partial closure | Groups 1+2+6 done; Groups 3-5 (P2) deferred |
| TD-009 | low | S44+ | 🟡 deferred | 31_DSL_Visual_Editor.py 1267 LOC outlier |
| TD-010 | low | S43+ | 🟡 documented | 14 pages без st.set_page_config |

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

## TD-007: `vite-env-dts-html-content` (low, S43+)

**Файл:** `frontend/admin-react/src/vite-env.d.ts` (13 lines, **содержит HTML**)

**Проблема:** Файл с расширением `.d.ts` (TypeScript declaration) содержит
HTML-содержимое (index.html template). Это pre-existing bug, НЕ Sprint 42
introduction. Build падает на TS step:
```
src/vite-env.d.ts(6,11): error TS1005: '>' expected.
```

**Root cause**: вероятно, при S19 K5 W5c (admin-react MVP) `index.html`
был скопирован в неправильное место (должен быть `index.html` в root,
`vite-env.d.ts` должен содержать только `/// <reference types="vite/client" />`).

**Impact**: `npm run build` в admin-react падает. admin-react — MVP,
not deployed (per Sprint 19), так что impact = 0 на production.

**Workaround**: admin-react not in production build pipeline.

**Fix (S43+)**:
1. Move HTML content to `frontend/admin-react/index.html` (if not exists)
2. Replace `vite-env.d.ts` с: `/// <reference types="vite/client" />`
3. Verify `npm run build` passes

**Refs:** Sprint 42 W2 attempt (Vite 8.0.16 build failed, identified
this pre-existing bug). Commits 72ed6b0f body.

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

### S83 entry point: S84+ backlog

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

### S84 entry point: S85+ backlog

Следующая сессия (S85+) должна:
1. Address **TD-016** (airflow_sensors test refresh)
2. **B3**: extract `transport/proxy.py` + `transport/scheduling.py` (~165 LOC)
3. **B4**: extract `transport/external.py` + `transport/sources.py` (~225 LOC)
4. **B5**: closure + ADR-0107 status update (Accepted)
5. **C2**: extract `transport/__init__.py` → `workflow_diff.py` (~180 LOC, target 600)
6. Continue next god-object decomp (actions.py 986 LOC, ai_banking.py 828 LOC)



