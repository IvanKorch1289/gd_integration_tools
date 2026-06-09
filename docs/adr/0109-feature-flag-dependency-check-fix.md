# ADR-0109 — Feature Flag Dependency Check: package-aware + Sprint 41 audit

* Статус: Accepted (Sprint 41 W2, 2026-06-09)
* Связано с: PLAN.md §5 (Sprint 41 #5 — Feature flags); TD-018.

## Контекст

В Sprint 38 T1.3.0 monolithic `src/backend/core/config/features.py` был
разделён в `features/` package с 24 per-domain sub-modules (`ai.py`,
`billing.py`, `dsl.py`, `experimental.py`, `infrastructure.py`, ...).

Check-скрипт `tools/checks/check_feature_flag_dependencies.py` (S31 w1 Фаза D)
продолжал искать **`features.py`** (file) — не находил и возвращал:

```
[ERROR] features.py не найден: src/backend/core/config/features.py
```

→ CI gate **молча падал** в `--strict` режиме, но **не выполнял реальную
проверку** зависимостей `_strict` feature flags.

Параллельно `check_feature_flag_usage.py` (sibling check) **PASSED** —
238 flags defined, all referenced. Это создавало **ложное чувство
безопасности**: "usage check зелёный, значит всё OK".

## Решение

### 1. Package-aware check (W2 main deliverable)

`tools/checks/check_feature_flag_dependencies.py` обновлён:
- Поддерживает оба layout'а: legacy `features.py` (file) + modern
  `features/` (package).
- При package layout сканирует **все** `.py` файлы в `features/`,
  конкатенирует source с file-level comments.
- AST анализ уточнён: ищет `ast.AnnAssign` (аннотированные присваивания
  = реальные `Field(...)` definitions), а не любой `ast.Name`.
  Это устраняет false-positives от imports и references.

### 2. Audit: 18 undeclared `_strict` flags

После фикса check обнаружил **18** `_strict` flags без declared dependency:

| Flag | Sub-module | Notes |
|---|---|---|
| `mcp_tools_input_schema_strict` | ai.py | — |
| `supply_chain_finale_strict` | billing.py | — |
| `dsl_processor_registry_strict` | dsl.py | — |
| `plugin_semver_strict` | experimental.py | — |
| `tracing_baggage_strict` | infra | K1 — Tracing |
| `lsp_server_strict` | — | — |
| `outbound_metering_strict` | — | **CRITICAL** (уже задекларирован в `_FEATURE_FLAG_DEPENDENCIES_CRITICAL`) |
| `perf_gate_strict` | — | — |
| `processor_health_checks_strict` | — | — |
| `dsl_linter_strict` | — | — |
| `ai_cost_dashboard_strict` | — | — |
| `workflow_versioning_strict` | ai_rag.py | — |
| `metrics_registry_strict` | — | — |
| `task_registry_strict` | — | — |
| `routes_capability_gate_strict` | — | — |
| `routes_tenant_aware_strict` | — | — |
| `call_function_whitelist_strict` | — | — |
| `ai_prompt_sweep_strict` | — | — |

**Анализ**: большинство — standalone flags (не требуют base dependency).
Правильный фикс для каждого: добавить комментарий
`# no dependency required` рядом с Field definition.

**Out of scope для S41 W2**: добавление 18 комментариев и/или
dependency declarations. Зафиксировано как **TD-018** (S42+ W1).

### 3. `--strict` mode теперь meaningful

До фикса `--strict` mode падал с `[ERROR] features.py не найден` →
exit 1, **но не из-за нарушений**. CI был в "always-1" состоянии.

После фикса `--strict` exit 1 = реальные нарушения, exit 0 = всё ОК.

## Альтернативы

| Альтернатива | За | Против | Решение |
|---|---|---|---|
| Backport `features/` → monolithic `features.py` | Check сразу работает | Теряем per-domain split; 24 files объединятся в 2000+ LOC файл | Отклонено |
| Удалить check целиком | Убирает шум | Теряем S31 w1 protection against `_strict` without declared dep | Отклонено |
| Заменить на runtime check в ConfigValidator | Всегда актуален | Vendor-specific логика; тяжело тестировать | Отклонено |
| **Package-aware check + deferred audit (TD-018)** | Сохраняет protection, реалистичный scope | 18 flags ждут formal audit в S42+ | **Принято** |

## Последствия

* **Позитивные**:
  * CI gate `check_feature_flag_dependencies` снова meaningful.
  * `--strict` mode различает "ok" и "fail" (раньше всегда 1).
  * Foundation для S42+ W1 formal audit 18 undeclared flags.
* **Риски**:
  * Sprint 41 W5 closure (CI gate check) может обнаружить другие
    package-vs-file расхождения в check-скриптах. **Митигация**:
    grep всех `tools/checks/*.py` на `_ROOT / "src/...features..."`
    (S42+ D).

## Ссылки

* Код: `tools/checks/check_feature_flag_dependencies.py` (W2 fix).
* Flags: `src/backend/core/config/features/*.py` (24 sub-modules).
* Validator: `src/backend/core/config/validator.py`
  (`_FEATURE_FLAG_DEPENDENCIES`, `_FEATURE_FLAG_DEPENDENCIES_CRITICAL`).
* Sibling check: `tools/checks/check_feature_flag_usage.py`
  (passes — 238 flags, all referenced).
* TD-018: 18 undeclared `_strict` flags → S42+ W1.
