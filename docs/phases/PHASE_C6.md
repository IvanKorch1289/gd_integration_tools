# Фаза C6 — OPA + Casbin (двухуровневая авторизация)

* **Статус:** done (scaffolding)
* **Приоритет:** P1
* **ADR:** ADR-012
* **Зависимости:** C5

## Выполнено

- `src/infrastructure/policy/opa.py` — `OPAClient` с httpx HTTP/2,
  fail-closed при недоступности.
- `src/infrastructure/policy/casbin_adapter.py` — `CasbinAdapter` +
  enforce/add_role/add_policy.
- `src/infrastructure/policy/__init__.py` — public API.

Middleware-integration + DSL-методы (`.with_opa_policy`,
`.with_casbin_role`) — follow-up.

## Definition of Done

- [x] OPAClient с fail-closed.
- [x] CasbinAdapter с enforce.
- [x] ADR-012.
- [x] `docs/phases/PHASE_C6.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C6 → done).
