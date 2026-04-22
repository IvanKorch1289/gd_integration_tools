# Фаза C11 — SOAP / IMAP async-миграция

* **Статус:** done
* **Приоритет:** P1
* **ADR:** ADR-009 (httpx)
* **Зависимости:** C10

## Выполнено

- `src/infrastructure/clients/transport/soap.py` — помечен
  `DeprecationWarning`; план удаления в H3.
- `src/infrastructure/clients/transport/soap_async.py` — новый
  `AsyncSoapClient` на httpx HTTP/2 + lxml для parse envelope.
- IMAP async миграция выполнена в A2 (imap_monitor.py →
  `aioimaplib`).
- `docs/DEPRECATIONS.md` обновлён (запись для `zeep`).
- `tools/check_deps_matrix.py`: `zeep` перемещён в H3 REMOVE.

## Definition of Done

- [x] AsyncSoapClient scaffold работает (POST envelope, parse response).
- [x] zeep помечен deprecated.
- [x] IMAP уже async (A2).
- [x] `docs/phases/PHASE_C11.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C11 → done).
