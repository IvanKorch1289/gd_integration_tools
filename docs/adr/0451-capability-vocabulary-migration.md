# ADR-0451 — Миграция capability-деклараций в vocabulary (план + рэтчет)

* Статус: Accepted (2026-11-17, волна 33)
* Cycle: 189 (волна 33)
* Связан с: ADR-0436 (capability-контур), ADR-0449 (enforcement деклараций процессоров), ADR-0078 (грамматика capability)
* Затрагивает: `src/backend/core/security/capabilities/vocabulary/defaults/base.py`, `tools/check_decorative_capabilities_allowlist.txt`, `src/backend/dsl/engine/processors/**`

## Контекст

После ADR-0449 capability из декоратора `@processor(capabilities=(...))`
проверяются в рантайме, **если** их имя есть в vocabulary. Оставшиеся 36
деклараций используют 3-сегментную форму (`net.outbound.compliance.api`,
`net.outbound.ldap:external`) — в vocabulary таких имён нет (грамматика
`<resource>.<verb>`, ADR-0078), и **scope** у них не задан → проверять их
по имени нельзя (блокировался бы вызов в никуда).

## Решение

Миграция выполнена **одним атомарным шагом** (2026-11-17):

1. Собраны все декларации `@processor(capabilities=(...))` из allowlist'а (36
   записей / 38 мест / 37 уникальных имён).
2. В **vocabulary** добавлено 35 capability (scope не требуется:
   `scope_required=False` — декларация описывает *вид* ресурса, конкретный
   scope задаёт роут).
3. Декларации процессоров переведены на vocabulary-имена (суффиксы `.*` и
   `:kind` убраны — они не являются частью имени capability, ADR-0078).
4. Имена внесены в `CORE_CAPABILITIES` (список «что принадлежит ядру») и в
   `RESOURCE_SCOPED_CAPABILITIES` (scope объявляет владелец ресурса — роут
   или плагин, как и для остальных resource-scoped capability).
5. Allowlist гейта очищен: **долг декоративных деклараций 36 → 0**.

## Последствия

* Декларации процессоров **enforced** (ADR-0449): runtime-резолвер проверяет
  наличие capability у namespace'а роута/владельца.
* `check_decorative_capabilities --ci` — 0 в долге; новые декларации вне
  vocabulary блокируются.
* Ресурсные capability объявляются роутом/плагином с конкретным scope — при
  включённом capability-гейте (`dsl_capability_gate_enabled`) роут обязан
  объявить используемые capability; это отдельная работа (ADR-0451, follow-up).
