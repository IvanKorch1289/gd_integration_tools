# CURRENT_STATUS — Single Source of Truth

> **Generated**: 2026-09-22T10:34:15Z
> **Regenerate**: `python tools/checks/generate_current_status.py`
> **DO NOT EDIT MANUALLY** — auto-generated from real CI artifact values.

---

## Build Identity

| Поле | Значение |
|---|---|
| **SHA** | `13acde80d2ff6789d9d84c134141428c49286d90` |
| **Short SHA** | `13acde80d` |
| **Branch** | `master` |
| **Last verified** | `2026-09-22T10:34:15Z` |
| **Python** | `3.14.0` |

---

## Hard Gates (Required для release)

| # | Gate | Status | Evidence |
|---|---|---|---|
| G1 | G1 AST/compile errors = 0 | ✅ PASS | `` |
| G2 | G2 Python-2 except clause = 0 | ✅ PASS | `` |
| G3 | G3 Ruff lint = 0 | ✅ PASS | `All checks passed!` |
| G4 | G5 Layer violations = 0 new | ✅ PASS | `Нарушений: 0 новых  (файлов: 2462; baseline: 22 legacy)` |
| G5 | G6 Layer check fail-closed on AST parse | ✅ PASS | `verified 2026-09-21 (exit 3 on broken file)` |
| G6 | G7 Bandit HIGH = 0 | ✅ PASS | `Bandit HIGH count (0 = pass)` |
| G7 | G8 SBOM vulnerabilities = 0 | ✅ PASS | `SBOM vulnerabilities count (0 = pass)` |

---

## Isolated Modules (Runtime reachability gate)

Count: **40** isolated core/ modules (zero production callers)

Run `python tools/checks/scan_isolated_modules.py --strict` to see list.
Decision registry: `docs/FEATURE_INVENTORY.md`.

---

## Regeneration

```bash
# Local:
python tools/checks/generate_current_status.py

# In release pipeline (TODO: integrate):
- name: Generate CURRENT_STATUS
  run: python tools/checks/generate_current_status.py
- name: Commit if changed
  run: |
    git diff --quiet docs/CURRENT_STATUS.md || \
      git commit -am 'docs: regenerate CURRENT_STATUS'
```
