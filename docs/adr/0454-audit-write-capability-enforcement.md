# ADR-0454 — Capability `audit.write`: enforcement процессора + декларации роутов

* Статус: Accepted (2026-11-17, волна 33)
* Cycle: 189 (волна 33)
* Связан с: ADR-0414 (step-level audit), ADR-0366 (runtime-resolver), ADR-0430 (caller-aware capability), ADR-0449 (декларации процессоров enforced)
* Затрагивает: `src/backend/dsl/engine/processors/audit.py`, `routes/{composition_demo,health_proxy_demo,hello_route,jupyter_hub_run,test_route_w1}/route.toml`, `tests/unit/dsl/engine/capability/test_audit_write_capability_adr0454.py`

## Контекст

Capability `audit.write` была в vocabulary с 2026-10-06, но:

* процессор `AuditProcessor` **не объявлял** `required_capability` → шаг `audit`
  писал в audit-sink без проверки прав;
* часть роутов (`hello_route`, `jupyter_hub_run`, `test_route_w1`) объявляла
  capability в `route.toml`, но объявление ни на что не влияло
  (декоративная декларация — см. ADR-0449);
* два роута (`composition_demo`, `health_proxy_demo`) не объявляли её вовсе.

Решение владельца (2026-11-10, п.5): объявить `audit.write` в роутах,
использующих шаг `audit`, и включить enforcement.

## Решение

* `AuditProcessor.required_capability = "audit.write"` — декларация обязательна;
* **enforcement — в самом процессоре**: `AuditProcessor.process()` вызывает
  `auth_check()` до обращения к sink'у (тот же контракт, что у БД- и
  RPA-процессоров, ADR-0393/ADR-0401). Отказ = `failed` + `stopped`, запись
  в audit-sink не выполняется;
* scope запроса — `audit:<action>` (точки в action заменяются на двоеточия:
  matcher `audit.write` — dot-glob, `.` — разделитель сегментов, поэтому
  `audit:order.created` не совпал бы с декларацией `audit:*`);
* все пять роутов с шагом `audit` объявляют `audit.write` со scope
  `audit:*` (конвенция vocabulary: tenant-id / audit-sink / `*`);
* capability `audit.write` — public в vocabulary: это снимает только
  declaration-time проверку манифеста (`check_capabilities_subset`).
  **Рантайм-контроль public не отменяет**: без декларации в `route.toml`
  шаг отклоняется fail-closed (namespace = route_id → нет декларации →
  DENY), если только явно не включён `dsl_capability_core_baseline_enabled`.

## Проверка

Тест `tests/unit/dsl/engine/capability/test_audit_write_capability_adr0454.py`
работает с **реальным** гейтом (модуль помечен `REAL_CAPABILITY_GATE = True`,
иначе autouse-фикстура `tests/unit/dsl/conftest.py` подменяет `auth_check`
на «всегда разрешено» и проверка была бы вакуумной):

* роут без декларации → шаг отклонён, sink не вызван;
* роут с декларацией `audit.write` / `audit:*` → шаг выполнен, sink вызван;
* декларация с другим scope → отказ (scope проверяется);
* все роуты с шагом `audit` объявляют `audit.write`.

## Последствия

* Декларации роутов перестали быть декоративными: capability реально
  проверяется на каждом шаге `audit`;
* гейт `check_route_capabilities` **видит** шаг `audit` (волна 33): capability
  берётся из того же источника, что и рантайм (`required_capability` +
  `@processor(capabilities=...)`), проверяются все scope-required capability
  из vocabulary → роут с шагом `audit` без декларации `audit.write` падает
  в CI (негативный тест в `tests/unit/tools/test_check_route_capabilities.py`);
* scope `audit:*` — «любой audit-sink»; более узкие декларации
  (`audit:<action>`) ограничивают набор событий роута.
