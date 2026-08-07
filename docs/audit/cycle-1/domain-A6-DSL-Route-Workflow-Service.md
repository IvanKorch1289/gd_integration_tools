# Cycle 1 — Phase 1 — Audit of Domain A6-DSL-Route-Workflow-Service

**Дата:** 2026-08-06
**HEAD:** `7f3d94a3`
**Аудитор:** A6-агент (cycle 1, read-only)

---

## 1. Сводка готовности по 5 категориям

| Категория | % | Обоснование |
|---|---|---|
| **RouteBuilder fluent API** | 85% | 17+ методов, dual-mode (Python + YAML), Camel-style. Verified через `dsl/route/builder/`. |
| **DSL dual-mode (Python ↔ YAML)** | 80% | YAML-импорт через `RouteLoader`, экспорт через `dsl_export_schemas.py`. Главный gap: workflow YAML compile path incomplete (см. A8 — `_bootstrap_default_declarations` imports missing modules). |
| **WorkflowBuilder + Temporal steps** | 70% | См. A8 cross-reference — 6 P0 блокеров. Сам DSL declarative layer OK, runtime fragile. |
| **YAML/TOML 80% декларативность** | 75% | `extensions/*/routes/*.dsl.yaml` покрытие высокое; `extensions/*/workflows/*.workflow.yaml` — 4 файла из 11 имеют broken `call_function` refs (см. A10). |
| **Отсутствие императивного control-flow** | 90% | В `dsl/engine/processors/` и `dsl/route/` императивные `if/else/for` встречаются только в helper-функциях, не в route composition. |

**Итоговая готовность**: **80%**

---

## 2. Таблица находок

| ID | Prior | Файл:строка | Описание | Фикс |
|---|---|---|---|---|
| **D-A6-01** | **P0** | `extensions/core_entities/orders/workflows/orders_dsl.py:241,250,305,316,326,336` | Использует несуществующий `.then()` метод WorkflowBuilder (6 мест). Production extension broken. | Добавить `.then()` alias в WorkflowBuilder (D-A8-06 fix) |
| **D-A6-02** | **P1** | `plugins/composition/workflow_setup.py:76-83` | `_bootstrap_default_declarations` импортирует несуществующие `orders_saga.py`/`payments_saga.py`. Startup crash при opt-in flag. | Удалить функцию (saga-демо удалены commit `9164a59`) |
| **D-A6-03** | **P1** | `dsl/route/builder/__init__.py` (chain_methods) | `RouteBuilder.proxy()/call_function()` поддерживают только 1 аргумент; YAML supports multi-step chains | Add `.proxy(src, dst).proxy(src2, dst2)` chaining helper |
| **D-A6-04** | **P1** | `dsl/workflow/compiler/activity_bridge.py:288-305` | `ActivityBridge.decorate()` ни разу не вызывается (cross-ref A8 D-A8-03) | Wire в production worker |
| **D-A6-05** | **P2** | `dsl/service/registry.py:35-72` | `@service_dsl(crud=True)` / `@register_action` — defined but **0 usage** в `extensions/` (cross-ref A3 D-A3-06) | Migrate `extensions/core_entities/services/*` к декораторам |
| **D-A6-06** | **P2** | `extensions/*/routes/*.dsl.yaml` (4 файла) | Broken `call_function: extensions.X.Y` refs — см. A10 B-101/102/103 | Restore или удалить broken refs |
| **D-A6-07** | **P2** | `dsl/workflow/spec/advanced_declarations.py:33-37` | Sensor `timeout_s=None` документирован как "бесконечно" — misleading (cross-ref A8 D-A8-20) | Document explicit cap |
| **D-A6-08** | **P3** | `dsl/workflow/versioning.py:295` | `WorkflowVersionRegistry` без RLock — race condition | Add `threading.RLock` |
| **D-A6-09** | **P3** | `dsl/blueprints/` (10 patterns R2) | 2 blueprints ссылаются на deprecated processors (S162 W5 removed) | Update blueprints |
| **D-A6-10** | **P4** | `dsl/cli/` | DSL CLI не имеет tab-completion для processor names | Add dynamic completer |

---

## 3. Эталонные соответствия (verified)

- `RouteBuilder.proxy().call_function().crud_create().validate_response()` chain — fully verified ✅
- YAML↔Python dual-mode — round-trip tests pass ✅
- 17+ mixins в WorkflowBuilder — production-ready ✅
- Pydantic discriminated union в `WorkflowStep` — 12 declaration-типов ✅

---

## 4. Готовность домена: **80%**

**Главный риск:** broken `orders_dsl.py` extension (D-A6-01) + missing workflow bootstrap imports
(D-A6-02) — production extension broken в `extensions/core_entities/orders/`.

**Минимальная рекомендация:**
1. `.then()` alias в WorkflowBuilder (D-A6-01) — ~+5 LOC, fixes 6 broken call sites
2. Удалить `_bootstrap_default_declarations` (D-A6-02) — −30 LOC
3. Migrate 4 broken YAML call_function refs (cross-ref A10 B-101/102/103) — fix imports
