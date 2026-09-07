# ADR-0296: Gate 15 (feature-flags audit) — infra-deferral

**Дата**: 2026-09-05. **Статус**: accepted (interim — ждёт подтверждения пользователя)
**Контекст**: PROGRESS_LEDGER.md, M6-#1 / финальная карта pre-prod-check.

## Контекст и проблема

Gate 15 (`feature-flags audit`) требует живой Vault: чекер резолвит
feature-flags через secrets-цепочку (`vault.lookup-self` при старте).
В текущем окружении Vault недоступен (`127.0.0.1:8200` connection refused —
docker API также permission denied, поднять compose-стек невозможно):
`uv run python tools/checks/pre_prod_check.py` → gate 15 FAIL.

## Решение

1. Gate 15 помечен **infra-deferral** — окружение без Vault не может
   выполнить проверку by design (это не дефект кода).
2. При деплое в prod-окружение (Vault поднят) — прогон обязательен,
   gate снимается с deferral.
3. Альтернатива для Vault-less сред (если потребуется): env-only профиль
   feature-flags + отдельный gейт без Vault-резолва — post-план.

## Последствия

- Pre-prod-check: FAILED 3 → с этим ADR фактически 2 блокера
  (gate 01 coverage — T3, gate 19 startup — MARGINAL/флак shared-box).
- Позитивные JWT/брокерные сценарии M6-#3 — аналогично BLOCKED(infra)
  (docker permission denied, verified 2026-09-05).

## Related

- `docs/roadmap/PROGRESS_LEDGER.md` (M6-#1, M6-#3)
- `docs/adr/0287-diskcache-pyssec-2447-deferral.md` (прецедент deferral)
