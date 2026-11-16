# ADR-0449 — Capability из декларации процессора проверяется в рантайме

* Статус: Accepted (2026-11-16, волна 32)
* Cycle: 188 (волна 32)
* Связан с: ADR-0366 (runtime-resolver), ADR-0416 (capability-контур), ADR-0443 (гейты)
* Затрагивает: `src/backend/dsl/engine/processors/base.py`, `tools/check_decorative_capabilities.py`, `tools/check_decorative_capabilities_allowlist.txt`, `tests/unit/dsl/engine/capability/test_decorator_capabilities_enforced_adr0449.py`

## Контекст

`@processor(capabilities=(...))` публиковал capability в JSON-схеме
(для LSP/линтера), но **движок её не проверял**: runtime-механизмом был только
`required_capability`. Гейт `check_decorative_capabilities` насчитывал 44
декоративные декларации — иными словами, контроль прав в этой форме был
иллюстративным.

## Решение

* `BaseProcessor._declared_capabilities()` собирает проверяемый набор:
  `required_capability` (первым, как раньше) **плюс** capability из
  декларации процессора, **чьё имя есть в vocabulary**;
* capability вне vocabulary остаётся advisory (легаси-декларации используют
  3-сегментную форму вида `net.outbound.compliance.api`, которой нет в
  vocabulary — у неё нет и scope, блокировать по ней вызовы было бы опасно);
* гейт `check_decorative_capabilities` учитывает новый критерий: декларация с
  именем из vocabulary **не** декоративна. Долг сократился 44 → 36;
* тесты фиксируют контракт (enforced / advisory / порядок).

## Последствия

* 8 деклараций перестали быть декоративными и проверяются в рантайме;
* остаток долга (36) — легаси-формы без scope; их миграция в vocabulary —
  отдельная задача (ADR-0446, волна 32);
* новые декларации с именами из vocabulary защищены гейтом автоматически.
