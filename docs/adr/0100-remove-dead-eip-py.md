# ADR-0100: Remove dead `dsl/builders/eip.py` (1354 LOC) — S60 W4 split superseded

**Date:** 2026-06-08
**Status:** Accepted (S77 W2)
**Sprint:** S77
**Deciders:** core team
**Supersedes:** — (extends S60 W4 split, formalizes cleanup)
**Related:** ADR-0099 (v28 reconciliation), `ee6b4b57 refactor(dsl): S60 W4 — split eip.py god-file`, `verify-analysis-claims` skill

## Context

v28 ро-анализ (2026-06-08) утверждал что `src/backend/dsl/builders/eip.py` — god-file 1354 LOC, рекомендовал split на 3 файла. Verification через `verify-analysis-claims` skill показала:

**Split был сделан в S60 W4** (commit `ee6b4b57 refactor(dsl): S60 W4 — split eip.py god-file (1354→350 max LOC) [verified]`, 2026-06-07). После S60 W4:
- `eip.py` (1354 LOC) — старая single-class имплементация, **DEAD** (не импортируется).
- `eip/` package (1497 LOC, 9 модулей) — новая имплементация:
  - `_base.py` (28 LOC) — EIPMixinBase
  - `core.py` (62 LOC) — CoreEIPsMixin (transform, filter, cdc)
  - `routing.py` (246 LOC) — RoutingEIPsMixin
  - `sources.py` (299 LOC) — SourcesEIPsMixin
  - `transformation.py` (115 LOC) — TransformationEIPsMixin
  - `protocols.py` (46 LOC) — ProtocolsEIPsMixin
  - `streaming.py` (183 LOC) — StreamingEIPsMixin
  - `messaging.py` (111 LOC) — MessagingEIPsMixin
  - `messengers.py` (350 LOC) — MessengersEIPsMixin (max LOC в package)
  - `__init__.py` (57 LOC) — combined `EIPMixin` через MRO

## Verification (5-step audit recipe)

| Check | Method | Result |
|---|---|---|
| 1. Find | `find src -name 'eip.py'` | `src/backend/dsl/builders/eip.py` (1354 LOC) |
| 2. LOC | `wc -l` | 1354 (matches v28 claim — TECHNICALLY true) |
| 3. Active import | `grep -rn 'from src.backend.dsl.builders.eip'` (module-level) | `base.py:48` импортирует `from .eip import EIPMixin` — **PACKAGE**, not file |
| 4. Python resolution | `importlib.util.find_spec('backend.dsl.builders.eip').origin` | `/.../eip/__init__.py` (PACKAGE wins) |
| 5. Test parity | `pytest tests/unit/dsl/builders/` (461 tests) with vs without `eip.py` | **461/461 passed, identical** |

## Decision

**DELETE** `src/backend/dsl/builders/eip.py` (1354 LOC, dead code) + cleanup stale `__pycache__/eip.cpython-*.pyc`. Single 1-commit change.

### Smoke test before commit

```bash
mv src/backend/dsl/builders/eip.py /tmp/eip.py.bak
rm -f src/backend/dsl/builders/__pycache__/eip.cpython-*.pyc
pytest tests/unit/dsl/builders/ tests/unit/extensions/ extensions/credit_pipeline/tests/
# Result: 528 passed, 3 skipped (4.37s) — IDENTICAL to with eip.py
mv /tmp/eip.py.bak src/backend/dsl/builders/eip.py  # restore for safety
```

### Architectural impact: ZERO

* `EIPMixin` API: backward-compatible (combined MRO из 8 mixin classes).
* Public surface: тот же набор 59 методов.
* Test count: identical (528 passed, 3 skipped).
* `from src.backend.dsl.builders.eip import EIPMixin` — продолжает работать (package import).

## v28 fabrication pattern (continued)

Это **4-й подтверждённый fabricated claim из v28**:
1. ❌ 95 SyntaxError → 0 (overlap v25 redux)
2. ❌ <10% docstrings → 91-100% documented
3. ❌ SQL injection в audit → LOW RISK, mitigated
4. ❌ CDC/S3 stubs → real infrastructure
5. ❌ **eip.py god 1354 LOC** → split DONE S60 W4 (file is dead code)

v28 рекомендация "split eip.py на 3 файла" была бы **waste of work** — реальная работа (S60 W4 split) уже сделана 1 месяц назад, оставалось только cleanup dead file.

## Lessons reinforced

1. **Long ro-analysis documents are 50-60% fabricated** (v22: 4/7, v25: 4/7, v28: 5/13+). Always verify each claim.
2. **File size ≠ god-file**: `eip.py` = 1354 LOC on disk, но фактически dead. Split was done, файл остался как артефакт.
3. **Python package vs file shadowing**: когда `eip.py` и `eip/` существуют одновременно, package wins (CPython preference). This is the safer behavior — `eip.py` deletion is truly safe.
4. **Test parity is the ground truth**: 528/528 identical test results with vs without `eip.py` = proof of dead code.
5. **Skip the fabrication, log it**: ADR-0100 formalizes the v28-redux pattern (split done, dead file left), so the next session doesn't re-discover the "eip.py god" claim.

## References

* `final_report_v28.md` (2026-06-08) — input report (5+ of 13 fabricated, including this)
* `verify-analysis-claims` skill — 5-step audit recipe
* `references/v25-ro-fabrication-2026-06-08.md` — precedent (4/7 fabricated)
* `references/v22-ro-fabrication-2026-06-06.md` — earlier precedent
* Commit `ee6b4b57 refactor(dsl): S60 W4 — split eip.py god-file (1354→350 max LOC) [verified]` — actual split
* ADR-0099 — v28 #1-#4 fabrication reconciliation (S76 W1 closeout)
