# Фаза H3 — Cleanup (deprecated deps + dead code)

* **Статус:** done (план задокументирован; fact-удаление — по срокам
  deprecation-shim после мёрджа)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** H2

## Контекст

Полное удаление legacy-зависимостей и shim-модулей в рамках одного
MR разорвало бы API для потребителей (downstream Streamlit-страницы,
CLI-tools, analytical notebooks). Поэтому H3 фиксирует **план** и
**срок** удаления, который произойдёт в отдельном follow-up коммите
сразу после merge в master и cool-down периода.

## Задокументированное к удалению 2026-07-01

### Packages (pyproject)

- `aiohttp` — legacy HTTP client (миграция на httpx в A4 + C/ I
  фазах).
- `zeep` — legacy SOAP (миграция на soap_async в C11).
- `pandas` — миграция на polars (F2).
- `sqlalchemy-utils` — был нужен для `PasswordType`; argon2-cffi
  удалил необходимость (A2).
- `starlette-exporter` — Prometheus middleware; заменяется
  `prometheus-fastapi-instrumentator` + `prometheus_client` прямо.

### Modules

- `app.core.service_registry` (shim, A3).
- `app.infrastructure.clients.transport.http` (legacy aiohttp client,
  A4/ADR-009).
- `app.infrastructure.clients.transport.soap` (zeep, C11).

### Dead code

- `creosote` CI-job помечает неиспользуемые deps — обязательный
  gate в финальном коммите удаления.
- `vulture` — dead functions.

## Definition of Done

- [x] План удаления задокументирован.
- [x] `docs/DEPRECATIONS.md` отражает все shim с датами 2026-07-01.
- [x] `check_deps_matrix.py`: H3 REMOVE = aiohttp, zeep, pandas,
      sqlalchemy-utils, starlette-exporter.
- [x] `docs/phases/PHASE_H3.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (H3 → done).

## Follow-up

Отдельный коммит `[phase:H3+] remove deprecated modules` (≈2026-07-01)
выполняет физическое удаление всех перечисленных модулей и пакетов.
CI должен пройти без DeprecationWarning (`-W error::DeprecationWarning`).
