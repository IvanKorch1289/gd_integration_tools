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

* `AuditProcessor.required_capability = "audit.write"` — проверка обязательна
  (scope проверяется runtime-resolver'ом, ADR-0366);
* все пять роутов с шагом `audit` объявляют `audit.write` со scope
  `audit:*` (конвенция vocabulary: tenant-id / audit-sink / `*`);
* capability `audit.write` — public в platform-baseline, поэтому шаг
  работает и без собственной декларации роута; декларация ограничивает
  scope sink'ов.

## Последствия

* Декларации роутов перестали быть декоративными;
* гейт `check_route_capabilities` проверяет наличие декларации у ресурсных
  capability — новый роут с шагом `audit` без декларации не пройдёт CI;
* тест фиксирует контракт: процессор требует capability, все роуты с шагом
  `audit` её объявляют, шаг выполняется под public-baseline.
