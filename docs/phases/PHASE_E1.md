# Фаза E1 — DSL utils max (banking + datetime + strings + regex presets)

* **Статус:** done
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** B1

## Выполнено

`src/dsl/helpers/`:

- `banking.py` — ИНН/КПП/БИК/ИБАН/SWIFT validators; `business_day`,
  `money` (Decimal).
- `datetime_utils.py` — now/add_days/to_iso8601 с zoneinfo.
- `strings.py` — slugify / mask / redact_pii (email/phone/inn).
- `regex_presets.py` — inn10/inn12/kpp/bic/swift/iban/ru_phone/email.
- `__init__.py` — каталог.

Fluent API / macros (`when().otherwise()`, `macro()`, shortcuts) —
будущее расширение builder (follow-up), публичные хуки уже в
`AIMixin` / `BankingMixin` через B1.

## Definition of Done

- [x] 4 подмодуля helpers.
- [x] ИНН 10/12 валидация с checksum (ФНС-совместимая).
- [x] IBAN MOD-97.
- [x] `docs/phases/PHASE_E1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (E1 → done).
