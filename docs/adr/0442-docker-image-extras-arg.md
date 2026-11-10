# ADR-0442 — Набор extras образа задаётся build-ARG'ом (`UV_EXTRAS`)

* Статус: Accepted (2026-11-10, волна 31)
* Cycle: 188 (волна 31)
* Связан с: ADR-0267 (fail-closed worker), ADR-0381 (extra sources-cdc), ADR-0441 (инфра-чек-лист)
* Затрагивает: `ops/compose/Dockerfile`, `docs/ops/infra-release-checklist.md`

## Контекст

Dockerfile жёстко задавал extras: `uv sync … --extra dev-light --extra sources-cdc`.
В prod-образе из-за этого **не было `temporalio`** → Temporal-воркер не мог
стартовать. Код при этом fail-closed (ADR-0267 F-AT1: пустой воркер больше не
рапортует `STARTED`), то есть деплой падал явно — но причина выглядела как
«воркер не поднялся», а не «в образе нет SDK».

## Решение

* `ARG UV_EXTRAS="dev-light sources-cdc"` — набор extras задаётся при сборке;
* prod-сборка: `--build-arg UV_EXTRAS="dev-light sources-cdc workflow"`
  (extra `workflow` содержит `temporalio`);
* light-сборка (локальный стенд) — дефолт без `workflow` (LiteTemporalBackend).

## Последствия

* Причина «не стартует workflow-воркер» устранена на уровне сборки;
* набор extras виден в Dockerfile и в чек-листе инфраструктуры (ADR-0441).
