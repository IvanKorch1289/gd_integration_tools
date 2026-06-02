# T-P0.1.2 — Noqa + ruff audit (02.06.2026)

> **P0 (тесты) контекст.** Definition of Production Ready (v9 §VI): noqa <500 / <100.
> **Baseline:** 1677 noqa-директив (v9 говорил 1502 — занижено на 175).
> **Ruff errors:** 396 (269 fixable).

## Noqa breakdown (топ)

| # | Rule | Кол-во | Что значит | Auto-fixable? |
|:-:|------|:------:|------------|:-------------:|
| 1 | `BLE001` | **1109** | `except Exception:` (blind except) | 🟡 manual |
| 2 | `PLC0415` | 111 | `import` not at top of file | 🟡 manual |
| 3 | `F401` | 34 | unused import | ✅ ruff auto-fix |
| 4 | `E402` | 30 | module-level import not at top | 🟡 manual |
| 5 | `BLE001, S110` | 30 | blind except + try-except-pass | 🟡 manual |
| 6 | `S608` | 35 | hardcoded SQL expression | 🟡 manual (need parameterized) |
| 7 | `S311` | 11 | suspicious random | 🟡 manual |
| 8 | `PLW0603` | 10 | global statement | 🟡 manual |
| 9 | `SLF001` | 17 | private attribute access | 🟡 manual |
| 10 | `PLR2004` | 9 | magic value comparison | 🟡 manual |

**Top-10 = 1396 (83% всех noqa).** Top-1 (`BLE001`) = 66%.

## Ruff errors breakdown (396 total, 269 fixable)

| Rule | Кол-во | Auto-fixable? |
|------|:------:|:-------------:|
| `I001` unsorted-imports | 138 | ✅ |
| `F401` unused-import | 119 | ✅ |
| `S603` subprocess | 24 | ❌ (need shell=False with list) |
| `S110` try-except-pass | 18 | ❌ (manual) |
| `F841` unused-variable | 17 | ❌ (auto in unsafe mode) |
| `S108` hardcoded-temp-file | 16 | ❌ (manual) |
| `F821` undefined-name | 15 | ❌ (auto in unsafe mode) |
| `S608` hardcoded-SQL | 12 | ❌ (manual, parameterized) |
| Other | 37 | varies |

## Plan to reduce noqa (v9 target <500)

**Phase 1 (mechanical, 1-2 days):**
- `ruff check --fix` для I001 (138) + F401 (119): **-257 noqa candidates** (но не все unused imports — нужно проверить)
- `ruff check --unsafe-fixes`: ещё −50 candidates

**Phase 2 (semi-manual, 1-2 weeks):**
- BLE001 audit: **1109 → ~300** (заменить `except Exception:` на конкретные типы где возможно)
- E402 + PLC0415: 141 → 50 (реорганизация imports)

**Phase 3 (manual, 2-3 weeks):**
- S608 SQL: 35 → 0 (parameterize queries, hard work)
- S311 random: 11 → 0 (use `secrets` instead of `random`)
- SLF001 + PLR2004: 26 → 10 (extract constants, encapsulate)

**Realistic target S38: 1677 → 800 (50% reduction).** Target v9 <500 — V24+ (post-V23).

## Что НЕ делаем в S38

- ❌ Не фиксим BLE001 wholesale (1109 ручных правок, риск regression)
- ❌ Не фиксим S608 wholesale (security-critical, нужны unit-tests)
- ❌ Не auto-fix F401 wholesale (могут быть re-exports, side effects)

## Что можем сделать (low-risk, S38)

- ✅ `ruff check --fix` для I001 (138 mechanical) → отдельный PR
- ✅ Удалить unused F401 imports (manual check) → отдельный PR
- ✅ Audit каждой BLE001 в **критических** модулях (auth, resilience) — не все 1109

## Следующий шаг

**T-P0.1.3** — `ruff check --fix --unsafe-fixes` (механические правки I001 + F401).
~30-50 LOC diff, отдельный PR, no behavior changes.

После: `T-P0.1.4` — coverage gap analysis (когда pytest --cov завершится в background).
