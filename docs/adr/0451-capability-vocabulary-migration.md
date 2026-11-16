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

1. **Рэтчет:** текущие 36 записей — в allowlist'е гейта; новые декларации вне
   vocabulary блокируются (`check_decorative_capabilities --ci`).
2. **План миграции** (по одному capability за волну, атомарно):
   * выбрать реальный scope (host:port / bucket / table / action-kind);
   * добавить в vocabulary capability с этим scope (dot_glob или exact);
   * перевести декларацию процессора на новое имя;
   * снять запись из allowlist'а; гейт подтверждает, что декларация enforced.
3. Пока миграция не завершена, легаси-декларации остаются **advisory**
   (не блокируют вызов) — это осознанный компромисс: блокировать по
   невалидному имени опаснее, чем не проверять.

## Последствия

* Enforcement работает для vocabulary-имён уже сейчас (ADR-0449).
* Долг 36 уменьшается инкрементально; allowlist — единственный источник
  правды о том, что ещё не мигрировано.
* Порядок миграции — по убыванию числа использований (сначала `net.outbound.*`,
  затем `storage.*`/`db.*`).
