# ADR-0435 — Строгая проверка ресурсных capability и персистентность checkpoint'ов

* Статус: Accepted (2026-11-10, волна 29)
* Cycle: 188 (волна 29)
* Связан с: ADR-0416 (capability-контур), ADR-0424 (шаблоны), ADR-0429 (громкий провал)
* Затрагивает: `tools/check_route_capabilities.py`, `src/backend/dsl/cli/lint.py`, `routes/*/route.toml`, `src/backend/infrastructure/workflow/pg_runner_internals/instance_store.py`, `src/backend/dsl/workflow/compiler/activity_bridge.py`

## Контекст

1. Проверка ресурсных capability в гейте была только WARN-сообщением → роут мог
   использовать `http_call`/`s3_*` без декларации capability.
2. Activity `workflow.checkpoint.put` была best-effort: без хранилища возвращала
   `persisted=False`, checkpoint не сохранялся.

## Решение

1. Гейт использует единый маппинг `PROCESSOR_CAPABILITIES` (из линтера DSL-YAML)
   и **блокирует** недекларированные ресурсные capability. Легаси-манифесты —
   в baseline `.security/route-capabilities-baseline.txt` (рэтчет).
   Миграция: 4 роута получили `net.inbound` (baseline сжат 8 → 4 записи).
2. `InstanceStore.update_snapshot(workflow_id, snapshot)` + activity сохраняет
   checkpoint в снимок инстанса; компилятор передаёт `workflow_id`; несохранение
   возвращается явным `persisted=False` с причиной (ADR-0429).

## Последствия

* Новый роут без декларации ресурсной capability не проходит CI.
* Checkpoint workflow сохраняется в БД и переживает рестарт процесса.
