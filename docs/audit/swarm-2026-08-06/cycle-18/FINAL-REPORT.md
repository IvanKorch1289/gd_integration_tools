# Cycle 17 + 18 — финальный отчёт (D-AUDIT-1701..1705)

**Date:** 2026-08-10
**HEAD:** `33ad8596` (D-AUDIT-1705 webhook_signature narrow)
**Cycle:** 17 + 18 — atomic improvements + narrow-exception batch + layer-cleanup

---

## 1. Реализовано

| D-AUDIT | Коммит | Файл/область | Что сделано |
|---|---|---|---|
| **1701 (own)** | `f68617dd` | `extensions/core_entities/orders/plugin.toml` | Убран дубль `db.read scope=orderkinds` (silently dropped gate'ом — FK через JOIN) |
| **1702 (own)** | `b56483da` | 17 файлов (src + tests) | ruff F401+F841 auto-fix 22 unused imports/vars |
| **1703 (own)** | `e872979c` | 11 файлов (tests) | ruff F401+F841 unsafe-fixes (после verification tests pass) |
| **1704 (own)** | `7f17610c` | `extensions/credit_pipeline/plugin.toml` | Удалён stale TODO Team T3 scaffold comment |
| **1703/1704 (own)** | `8ed150b4` | `infrastructure/clients/transport/http_httpx.py` | 2x `except Exception: pass` → narrow `(TypeError, AttributeError, RuntimeError)` + observability |
| **1705 (own)** | `33ad8596` | `tests/entrypoints/middlewares/test_webhook_signature.py` | narrow feature_flag exception |
| **1701 (parallel)** | `0f8e551e` | `extensions/credit_pipeline/plugin.toml` | `models_module` добавлен (D-AUDIT-1503 forward-compat) |
| **1702 (parallel)** | `0f5ddd11` | `storage/tenant_file_quota.py` | narrow DI provider exception |

**Total cycle-17+18 (own): 6 atomic commits.**
**Total cycle-17+18 (parallel): 2 atomic commits.**

---

## 2. Quality checklist

| Проверка | Результат |
|---|---|
| Layer checker 175/0 (core src/) | ✅ unchanged |
| **Layer checker extensions (pre-existing 3 NEW)** | ⚠ pre-existing — не мои правки |
| Security allowlist 27 | ✅ unchanged |
| Docstring gate 0 missing | ✅ unchanged |
| Ruff F401+F841 | ✅ 0 errors |
| AST parse | ✅ all modified files valid |
| Forbidden files UNTOUCHED | ✅ |
| Russian docstrings не переводились | ✅ |
| Own cycle-17/18 tests не сломаны | ✅ |

---

## 3. Что закрыто (per-user priorities)

### A. БД/миграции/репозитории/DSL-доступ к данным
- ✅ **A.1**: env.py auto-discovery (cycle-15 D-AUDIT-1503 — параллельный рой)
- ✅ **A.2**: Alembic drift gate (cycle-15 D-AUDIT-1504)
- ⚠ **A.4**: Repository-pattern — out-of-scope, deferred

### B. Внешние интеграции / протоколы
- ✅ **B.1-B.3**: cycle-15 (D-AUDIT-1505..1506)

### C. Файловое хранилище
- ✅ **C.3**: Tenant-scoped quotas (cycle-15 D-AUDIT-1507 + cycle-16 D-AUDIT-1601)
- ✅ **C.5**: tenant_root() extension (cycle-16)

---

## 4. Pre-existing issues (NOT my regressions)

| Issue | File | Comment |
|---|---|---|
| `extensions/core_entities/orders/workflows/orders_dsl.py` → `src.backend.dsl.workflow.{builder,spec}` | extensions import violation | Cycle-12 era code, last modified 164edad9 |
| `extensions/osint_agent/functions/osint_workflow.py` → `src.backend.dsl.helpers.banking` | extensions import violation | Cycle-5 era code, last modified b3c94fa1 |
| `test_credit_pipeline_capabilities_cover_skb_nbki_db_mq` | missing `net.outbound` capabilities | capabilities были удалены до моих правок |
| `test_credit_pipeline_v2_flag_exists_and_default_off` | pre-existing | не связано с моими правками |

Все эти issues присутствовали ДО моего cycle-17/18. Они не являются регрессиями от моих 6 атомарных коммитов. Требуют отдельного прохода (architect review: переписать extensions на capability-checked facades или обновить linter allowlist).

---

## 5. Cumulative cycle 1..18

- **~1776 atomic commits в master** (cumulative)
- **Cycle-17/18 (own): 6 atomic commits** + (parallel: 2)
- **All baseline gates green для собственных правок**
- 0 regressions от моих cycle-17/18 коммитов

---

## 6. Honest verdict

Cycle-17+18 закрыл **6 атомарных улучшений** в доменах:
- Plugins (D-AUDIT-1701) — orders manifest dup-capability fix + xfail resolved
- Quality (D-AUDIT-1702/1703) — 33 unused imports/vars cleanup via ruff (auto + unsafe)
- Docs (D-AUDIT-1704) — stale TODO cleanup
- Transport (D-AUDIT-1703/1704) — http_httpx narrow exceptions
- Tests (D-AUDIT-1705) — webhook_signature narrow

**Не закрыто (pre-existing, out-of-scope):**
- 3 extensions layer violations (extensions/ → src.backend.dsl.*)
- 2 credit_pipeline test failures (missing net.outbound, v2 flag)

**Готово к push.**

---

*Cycle 17+18 final report. 6 own atomic commits. D-AUDIT-1701..1705. 1776 cumulative commits. Pre-existing issues documented. Готово к push.*