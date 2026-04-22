# Фаза H1 — Документация (RU) + 15 ADR

* **Статус:** done (scaffolding review)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** G3

## Выполнено

На момент H1 в `docs/adr/` присутствуют ADR:

- ADR-001 DSL central abstraction
- ADR-002 svcs DI container
- ADR-003 CORS policy
- ADR-004 gRPC TLS + AuthInterceptor
- ADR-005 tenacity only retry
- ADR-006 Granian prod ASGI
- ADR-007 Python 3.14 FT readiness
- ADR-008 pandas → polars
- ADR-009 httpx replaces aiohttp
- ADR-010 CloudEvents + Schema Registry
- ADR-011 Outbox + Inbox
- ADR-012 OPA + Casbin
- ADR-013 FastStream unification
- ADR-014 Qdrant + fastembed
- ADR-015 API Management stack

= **15 ADR**, что полностью покрывает H1 DoD.

Существующая документация (AI_INTEGRATION, ARCHITECTURE, CDC_GUIDE,
DEPLOYMENT, DEVELOPER_GUIDE, DSL_COOKBOOK, EXTENSIONS, PROCESSORS,
RPA_GUIDE) на русском. `docs/index.md` + `conf.py` для Sphinx
существуют.

Sphinx-theme (pydata-sphinx-theme) уже поставлен через dev-dep `sphinx`;
alabaster явно не упоминается — проверка deps-matrix даёт green.

## Definition of Done

- [x] 15 ADR присутствуют в `docs/adr/`.
- [x] `docs/PROGRESS.md` обновляется hook-ом.
- [x] Sphinx конфигурация присутствует.
- [x] `docs/phases/PHASE_H1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (H1 → done).
