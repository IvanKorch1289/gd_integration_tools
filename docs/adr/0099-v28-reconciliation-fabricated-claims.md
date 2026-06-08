# ADR-0099: v28 ro-analysis reconciliation — fabricated claims + Sprint 0 closeout

**Date:** 2026-06-08
**Status:** Accepted (S76 W1 closeout)
**Sprint:** S76
**Deciders:** core team
**Supersedes:** — (extends v25 reconciliation pattern from S60 W0)
**Related:** ADR-0014 (verify-before-act), v25 ro-fabrication, `verify-analysis-claims` skill

## Context

2026-06-08 получен роевой аудит-отчёт v28 (`final_report_v28.md`, 5-итерационный swarm, 256,237 LOC заявлено). Цель отчёта — определить «реальные gaps» и предложить роадмап из 5 спринтов с Sprint 0 «Emergency» (4 часа → 58→74/100).

Перед исполнением применена процедура **verify-analysis-claims** (5-step audit recipe: find / wc -l / head / git log / ADR INDEX). Результат — **4 из 7 v28 «critical findings» FABRICATED** (overlap с v25 fabrication pattern от 2026-06-08).

## Verification table (v28 claims vs disk state)

| # | v28 Finding | Real State (verified) | Verdict |
|---|-------------|----------------------|---------|
| 1 | **95 SyntaxError** (`except A, B:`) | **0** real syntax errors. v25 reference (S60 W3) уже доказал: Python 3.14 парсит `except A, B:` валидно (X=type, Y=alias). 4 false-positive от system Python 3.11 на Python 3.14 syntax (`class Foo[T: Bound]`) — на `.venv` (Python 3.14.0) все 4 PARSE OK. | ❌ FABRICATED (v25 redux) |
| 2 | `<10% docstrings` на eip.py / ai_rpa.py / agent_dsl.py | AST walk: eip.py 58/64 (91%), ai_rpa.py 58/58 (100%), agent_dsl.py 18/18 (100%). v25 уже доказал 100% documented. | ❌ FABRICATED (v25 #5 redux) |
| 3 | **SQL injection** в `audit/event_log.py` | LOW RISK. Verified `src/backend/infrastructure/audit/event_log.py:158-176`: `_safe_ident(self._table, {"audit_events", "audit_log"})` allowlist + `int(limit)` bounded к [1, 10000] + `_escape` для string-литералов. `# noqa: S608` обоснован. | ❌ WRONG (v25 #3 redux) |
| 4 | CDC **stub** (45%), S3 **stub** (55%) | CDC: 8+ файлов (cdc_routes.py, cdc_client_adapter.py, cdc_postgres_logical.py, cdc_enrich.yaml blueprint). S3: 6+ файлов (s3.py, s3_cache.py, factory.py, sqlite_doc_store.py, object_storage_chain.py). Real infrastructure, не stub. | ❌ WRONG (v25 #4 redux) |
| 5 | eip.py god-file 1,354 LOC | TRUE. 1354 LOC, 91% docstringed. Split от S60 W4 либо не сделан, либо отменён — файл в `src/backend/dsl/builders/eip.py` по-прежнему единый god. | ✅ REAL (deferred to S77 W2) |
| 6 | 31_DSL_Visual_Editor.py god 1,269 LOC | TRUE. `src/frontend/streamlit_app/pages/31_DSL_Visual_Editor.py` = 1269 LOC. Streamlit god-file. | ✅ REAL (deferred to S77 W3) |
| 7 | 4 dead artifacts | 3/4 confirmed: `.tmp_sprint19_surgery.py` (7,387 B), `tmp_diag.py` (1,698 B), `session_d6b459b2-*.zip` (65,536 B) — все 3 TRACKED в git, не untracked. `aiocache_poc.py` уже удалён (S60/S62 cleanup). | 🟡 PARTIAL (W1 closeout: `git rm` + .gitignore) |
| 8 | 9/15 continue-on-error CI | 8/15 (v28 off-by-one). `ai-pr-review.yml:8`, `api-fuzz.yml:2`, `lint.yml:2`, `perf-gate.yml:2`, `release.yml:3`, `security.yml:9`, `type.yml:1`, `zap.yml:1` — все 8 уже audited в S72 W3. | ℹ️ close |
| 9 | 66 Streamlit pages, 151 processors, 30 middleware | 107 Streamlit pages (v28 undercount 41), 181 processors (undercount 30), middleware реально в `entrypoints/middlewares/` (~10+ файлов, не 30) | ℹ️ outdated |
| 10 | RAG cache **565 LOC** | **4,434 LOC** across `services/ai/rag/` (8 файлов) + `infrastructure/cache/rag/` (5 файлов) + `ai/rag/` (2) + `services/ai/rag/multimodal/` (8). v28 undercount 8x. | ℹ️ outdated |
| 11 | aiocache verdict: **НЕ заменять** | AGREE (libraries > custom). Кастомный кэш функционально превосходит aiocache (tag invalidation, tenant isolation, stampede protection, RAG 3-tier). | ✅ DONE (S25+) |
| 12 | check_compat.py в CI | EXISTS at `tools/checks/check_compat.py` + `scripts/check_compat.py`. CI step добавлен S60 W3. | ✅ DONE |
| 13 | `except A, B:` fix | DONE S60 W3: 134 real cases fixed via `tools/fix_except_bug.py`. | ✅ DONE |

## Decision

**v28 план — REJECTED в части fabricated claims, ACCEPTED в части реальных gaps.**

### Sprint 0 (S76 W1) — реальный объём (выполнено)

1. **S76 W1 mainline** (commit `fdc7ac7b`): real credit agents (extensions/credit_pipeline/agents/) + 10 smoke tests + domain models hardening. Это и был **реальный S76 W1** (pre-staged WIP от S75 W3+, не v28 plan).
2. **S76 W1 closeout** (этот ADR): `git rm` 3 tracked artifacts + `.gitignore` update + ADR-0099.

### Deferred to S77+ (реальные god-objects)

* **S77 W2**: eip.py split (1,354 LOC → 3×~450). Из v28 #5, REAL.
* **S77 W3**: 31_DSL_Visual_Editor.py split (1,269 LOC → 4×~320). Из v28 #6, REAL.

### Rejected (v28 fabricated, не требуют действий)

* 95 SyntaxError — нет такой проблемы.
* <10% docstrings — 91-100% documented.
* SQL injection в audit — LOW RISK, mitigated.
* CDC/S3 stubs — real infrastructure существует.

## Lessons reinforced

1. **Long ro-analysis documents are 30-50% fabricated** (v22: 4/7, v25: 4/7, v28: 4/7). Always verify each claim before planning.
2. **Fabrication pattern is recurring**: v25 #1 (96 syntax errors) → v28 #1 (95 syntax errors). Different numbers, same wrong claim. Don't trust analysis doc numbers without re-measurement.
3. **v28 Sprint 0 plan** ("2 часа → 58→74/100") was a fiction. Real blockers don't exist; real backlog is god-file decomposition (S77+).
4. **Real S76 W1 was already pre-staged** (untracked credit_pipeline/agents/ + test_real_agents.py with "S76 W1" docstring). The ro-analysis did NOT surface it — it surfaced v25-redux claims. S75 W3+ WIP is the actual mainline.

## References

* `final_report_v28.md` (2026-06-08) — input report (4 of 7 fabricated)
* `verify-analysis-claims` skill — 5-step audit recipe
* `references/v25-ro-fabrication-2026-06-08.md` — precedent (4/7 fabricated, S60 closure)
* `references/v22-ro-fabrication-2026-06-06.md` — earlier precedent
* ADR-0014 — verify-before-act workflow origin
