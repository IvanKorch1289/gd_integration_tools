# ADR-0456 — Engine-wide enforcement capability в DSL-движке

* Статус: Accepted (2026-11-17, волна 34)
* Cycle: 190 (волна 34)
* Связан с: ADR-0449 (декларации процессоров enforced), ADR-0451 (миграция деклараций в vocabulary), ADR-0454 (audit.write), ADR-0366 (runtime-resolver), ADR-0363 (scope `audit:<action>`)
* Затрагивает: `src/backend/dsl/engine/capability_guard.py`, `src/backend/dsl/engine/execution_engine.py`, `src/backend/dsl/engine/processor_pool.py`, `src/backend/dsl/engine/processors/base.py`, `src/backend/dsl/engine/processors/audit.py`, `src/backend/core/security/capabilities/vocabulary/defaults/base.py`, `routes/{jupyter_hub_run,osint_agent}/route.toml`

## Контекст

Capability-контур после волны 33 (ADR-0449/0451/0454):

* декларации процессоров мигрированы в vocabulary — долг декоративных
  деклараций 36 → 0;
* enforcement есть **на уровне процессоров**: `BaseProcessor.auth_check()`
  вызывают 7 процессоров из 64 с непустой `@processor(capabilities=...)`
  (`AuditProcessor`, RPA-процессоры, БД-процессоры);
* **общего пути исполнения шага нет**: шаг, чей процессор декларирует
  capability, выполнялся без проверки — декларация оставалась
  декоративной (открытая позиция №1 роевого отчёта волны 33).

Дополнительно: capability `function.call` не была объявлена в манифестах
роутов с шагом `call_function` (`routes/jupyter_hub_run/`,
`routes/osint_agent/`) — с появлением общего enforcement'а такие шаги
стали бы отклоняться (fail-closed), то есть декларация обязательна.

## Решение

* **Единая точка enforcement** — `src/backend/dsl/engine/capability_guard.py`:
  `enforce_step_capability(processor, exchange, context)` вызывается движком
  **до** `processor.process(...)` в трёх местах:
  `ExecutionEngine._execute_processor` (основной путь),
  `ProcessorPool._execute_one` (параллельный путь),
  `run_sub_processors` (вложенные шаги: choice/flow/resilience/generic).
* **Источник capability** — тот же, что и в рантайме и в CI-гейте
  (ADR-0449/0454): `BaseProcessor._declared_capabilities()` =
  `required_capability` + имена из `@processor(capabilities=...)`, которые
  есть в vocabulary.
* **Шаг без декларации** → enforcement не применяется: обычные вызовы
  процессоров вне capability-контекта не падают (обратная совместимость).
* **Шаг с декларацией** → канонический гейт
  (`BaseProcessor.auth_check` → runtime-resolver, ADR-0366):
  namespace = `route_id` шага, scope = `audit:<action>`-стиля
  (точки в action заменяются на двоеточия).
* **Отказ** → `exchange` переводится в `failed` + `stopped`, шаг **не
  выполняется**, в trace попадает запись со статусом `denied`, пишется
  warning-лог `dsl_capability_denied`.
* **Идемпотентность**: `auth_check()` помечает проверенный шаг флагом
  `capability_verified` — внутренний вызов из `process()` не проверяет
  capability второй раз и не плодит audit-события `capability.check`.
  Перед каждой проверкой движок сбрасывает маркер (иначе повторное
  использование того же экземпляра процессора пропустило бы проверку).
* **Семантика action**: по умолчанию запрос идёт с `action="execute"`.
  Наследник может переопределить через `capability_action`
  (`AuditProcessor` → `"write"`), чтобы scope запроса совпадал с тем,
  который просит сам процессор.
* **`function.call` стала public** в vocabulary (ADR-0451-декларация).
  Публичность снимает **только** declaration-time проверку манифеста
  (`check_capabilities_subset`, ADR-044): плагина-владельца у
  DSL-процессора `call_function` нет. Рантайм-контроль public не читает —
  capability всё равно должна быть объявлена в `route.toml`, иначе шаг
  отклоняется (`no_declaration`). Ограничение на вызываемые модули
  остаётся за whitelist'ом (`call_function_modules`).
  Прецедент — `audit.write` (ADR-0454).

## Проверка

* `tests/unit/dsl/engine/capability/test_engine_wide_capability_adr0456.py` —
  7 тестов с **реальным** гейтом (`REAL_CAPABILITY_GATE = True`; иначе
  autouse-фикстура `tests/unit/dsl/conftest.py` подменяет `auth_check` и
  проверка была бы вакуумной): шаг с capability без декларации → отказ и
  шаг не вызван; шаг с capability и декларацией → выполнение; шаг без
  capability-декларации → поведение не изменилось.
* `tests/unit/dsl/engine/capability/` — 27 passed.
* `tests/unit/dsl` — 5562 passed, 21 skipped, 33 xfailed, 28 xpassed
  (регрессий нет).
* Гейты: `check_decorative_capabilities` — 0 новых;
  `check_route_capabilities` — OK (7 роутов, 12 плагинов);
  `check_docstrings` — 0 missing.

## Последствия

* Декларация capability процессора перестала быть декоративной: любой
  шаг с непустой декларацией проверяется до выполнения.
* Стоимость шага выросла на 1 обращение к capability-гейту (LRU-кэш
  `CapabilityGate`) и 1 audit-событие `capability.check`.
* Все 5 роутов с шагом `audit` уже декларируют `audit.write` со scope
  `audit:*` (ADR-0454) — поведение не изменилось.
* Роуты с шагом `call_function` объявляют `function.call`
  (`routes/jupyter_hub_run/`, `routes/osint_agent/`).
* **Открыто**: `check_route_capabilities` требует декларации только для
  *scope-required* capability — scope-optional capability (в т.ч.
  `function.call`) гейтом не проверяются; проверку scope расширить —
  отдельная задача.
* **Открыто**: engine-wide enforcement работает по namespace'у роута;
  `dsl_capability_core_baseline_enabled` в 4 профилях — `true`, поэтому
  capability из `CORE_CAPABILITIES` выдаётся ядром без декларации в
  роуте (осознанный компромисс ADR-0416).
