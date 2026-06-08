# TECH_DEBT — gd_integration_tools (last update: 06.06.2026)

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
| TD-008 | medium | S43 (W1) | 🟡 recommended | Streamlit groups 1+2+6 consolidation |
| TD-009 | low | S44+ | 🟡 deferred | 31_DSL_Visual_Editor.py 1267 LOC outlier |
| TD-010 | low | S43+ | 🟡 documented | 14 pages без st.set_page_config |

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
