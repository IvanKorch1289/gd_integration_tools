# Фаза G2 — API Management + Developer Portal

* **Статус:** done (scaffolding)
* **Приоритет:** P2
* **ADR:** ADR-015
* **Зависимости:** G1

## Выполнено

- `src/infrastructure/api_management/api_key_auth.py` — hash-only
  storage (OWASP).
- `quotas.py` — `QuotaTracker` с Redis token-bucket.
- `versioning.py` — `APIVersion` с Deprecation/Sunset headers.
- `__init__.py` — public API.
- ADR-015.

Developer portal — Streamlit page scaffold; try-it-out + SDK-download
в L1.

## Definition of Done

- [x] Hash-only API keys.
- [x] QuotaTracker.consume().
- [x] APIVersion headers (RFC 8594).
- [x] ADR-015.
- [x] `docs/phases/PHASE_G2.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (G2 → done).
