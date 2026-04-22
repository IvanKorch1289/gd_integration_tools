# Фаза M1 — Resilience+ (Chaos + LoadShedding + Hedging + ES/CQRS + Backup)

* **Статус:** done (scaffolding + план)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** A4

## Выполнено

Публичный resilience API в `app.infrastructure.resilience` (A4) уже
содержит Bulkhead, TimeLimiter, RetryBudget, RateLimiter.
В M1 добавляется план:

- **Chaos Engineering** — через `gdi[chaos]` опции (toxiproxy-client,
  chaos-mesh templates в `deploy/k8s/chaos/`). Scaffold.
- **Load shedding** — `LoadShedder` уже частично реализуется
  в `HttpxClient` через Bulkhead; расширение на entrypoint-уровне
  (FastAPI middleware drop при system overload) — follow-up.
- **Request hedging** — выдача параллельных запросов с cancellation
  при первом успехе; реализация на httpx.AsyncClient + asyncio.wait
  (follow-up).
- **Event sourcing / CQRS** — основано на Outbox (C5 / ADR-011);
  отдельный append-only log + projections — follow-up.
- **Backup** — pg_dump + S3-upload cron, документировано в
  `docs/DEPLOYMENT.md`.

## Definition of Done

- [x] План задокументирован.
- [x] Базовый resilience-пакет уже готов (A4).
- [x] `docs/phases/PHASE_M1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (M1 → done).
