# ADR-0433 — Линтер workflow-спецификаций и внутренние activity `reflect`/`checkpoint`

* Статус: Accepted (2026-11-09, волна 28)
* Cycle: 187 (волна 28)
* Связан с: ADR-0398 (activity-имена = зарегистрированные actions ядра), ADR-0403 (SLA/DLQ), ADR-0429 (громкая семантика провала), ADR-0424 (каталог шаблонов)
* Затрагивает:
  - `tools/check_workflow_specs.py` (новый линтер), `.github/workflows/lint.yml`,
  - `src/backend/dsl/workflow/compiler/activity_bridge.py` (activity `memory.reflect`, `workflow.checkpoint.put`),
  - `src/backend/dsl/workflow/compiler/step_compilers/flow.py` (результат checkpoint → warning),
  - `src/backend/plugins/composition/setup_infra/lifecycle.py` (регистрация activity в Worker'е),
  - `tests/unit/tools/test_check_workflow_specs.py` (новый)

---

## Контекст

1. **Спеки workflow проверялись только в рантайме.** Опечатка в имени activity
   или невалидное поле шага обнаруживались при запуске: build-time падал
   Temporal Worker, в dev-режиме — шаг. Пример: шаблон
   `guardrail_cost_budget` падал с `GuardrailValueTypeError` уже при
   выполнении (ADR-0429).
2. **Activity, которые эмитит компилятор, не были зарегистрированы.**
   `memory.reflect` (шаг `reflect`) и `workflow.checkpoint.put` (шаг
   `checkpoint`) не входят ни в action-реестр, ни в `INTERNAL_ACTIVITY_NAMES`
   → Worker их не знает (`ActivityNotRegisteredError` в рантайме), а
   build-time-валидация activity-имён их не видела (их нет в YAML).

---

## Решение

1. **Линтер `tools/check_workflow_specs.py`** (шаг в `lint.yml`): для каждого
   `*.workflow.yaml` — валидация спеки (`WorkflowDeclaration.model_validate`)
   и резолв имён activity (`ActivityBridge.collect_activities(validate=True)`);
   диагностика в формате `file:step.field: текст`. Отдельно проверяется, что
   activity, генерируемые компилятором, зарегистрированы в мосте.
2. **Внутренние activity реализованы:**
   * `memory.reflect` — пишет снимок outputs в LangMem (`episodic`,
     `procedural`; `semantic` требует embedding-вектора и пропускается с
     явной записью в `skipped`);
   * `workflow.checkpoint.put` — best-effort персистенция checkpoint'а;
     несохранение возвращается как `persisted=False`, а компилятор пишет
     warning (durable-состояние в Temporal-пути обеспечивает его history).
   Обе activity зарегистрированы в мосте и в Worker'е.

---

## Последствия

* Опечатки в activity-именах и невалидные поля шагов ловятся на CI, а не в
  рантайме.
* Шаблоны `agent_pipeline` и `checkpoint_continue_as_new` больше не падают с
  `ActivityNotRegisteredError`: activity зарегистрированы и реализованы.
* Персистентность явных checkpoint'ов остаётся best-effort (нужен отдельный
  store) — теперь это видно в логах, а не «тихий успех».
