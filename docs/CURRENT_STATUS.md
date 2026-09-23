# CURRENT_STATUS — Single Source of Truth

> **Generated**: 2026-09-23T11:40:11Z
> **Regenerate**: `python tools/checks/generate_current_status.py`
> **DO NOT EDIT MANUALLY** — auto-generated from real CI artifact values.

---

## Build Identity

| Поле | Значение |
|---|---|
| **SHA** | `64933d516b04afaafa518db76c744599ac978773` |
| **Short SHA** | `64933d516` |
| **Branch** | `master` |
| **Last verified** | `2026-09-23T11:40:11Z` |
| **Python** | `3.14.0` |

---

## Hard Gates (Required для release)

| # | Gate | Status | Evidence |
|---|---|---|---|
| G1 | G1 AST/compile errors = 0 | ✅ PASS | `` |
| G2 | G2 Python-2 except clause = 0 | ✅ PASS | `` |
| G3 | G3 Ruff lint = 0 | ❌ FAIL | `I001 [*] Import block is un-sorted or un-formatted   --> src/backend/dsl/builder` |
| G4 | G5 Layer violations = 0 new | ✅ PASS | `Нарушений: 0 новых  (файлов: 2530; baseline: 22 legacy)` |
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
