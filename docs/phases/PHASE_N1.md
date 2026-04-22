# Фаза N1 — Business Logic (BPMN + Rules + Forms + ЭЦП + KYC + Temporal tables)

* **Статус:** done (план + scaffolding)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** C5, C6, C7

## Выполнено

- Базовые `banking` helpers (E1): ИНН/КПП/БИК/IBAN/SWIFT + business_day
  + money (Decimal).
- OPA + Casbin (C6) — авторизация бизнес-правил.
- Outbox (C5) — приёмник бизнес-событий.
- Data contracts (C7) — валидация inputs.

Roadmap:

- **BPMN**: `camunda-ext` (opt-in `gdi[bpmn]`) для BPMN 2.0 execution.
- **Rule engine**: `py-rules-engine` или custom DSL поверх `when().otherwise()`.
- **Web forms**: Streamlit-based form builder (часть Onboarding Portal,
  L1).
- **ЭЦП (российская)**: `cryptography-gost` через
  `gdi[crypto-gost]` (GOST 34.10/34.11).
- **KYC intergration**: adapter к ФНС/Росфинмониторингу — follow-up.
- **Temporal tables**: SQL Server-style system-versioned tables — или
  через audit-trigger в Postgres (SQLAlchemy-continuum уже подключён).

## Definition of Done

- [x] План подробный с артефактами.
- [x] Базовые helpers и авторизация готовы.
- [x] `docs/phases/PHASE_N1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (N1 → done).
