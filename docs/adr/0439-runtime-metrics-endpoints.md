# ADR-0439 — Runtime-метрики: пулы соединений и процессы workflow

* Статус: Accepted (2026-11-10, волна 29)
* Cycle: 188 (волна 29)
* Связан с: ADR-0425 (контракт путей портала)
* Затрагивает: `src/backend/entrypoints/api/v1/endpoints/admin_runtime_metrics.py`, `src/backend/infrastructure/workflow/pg_runner_internals/instance_store.py`, `src/frontend/streamlit_app/pages/55_Монитор_пула.py`, `56_Процессы.py`

## Контекст

Панели «Монитор пула» и «Процессы» были выключены: эндпоинтов не
существовало. Для очередей общей capability «метрики брокера» в кодовой базе
нет (есть только NATS-специфичный `GET /api/v1/admin/nats/consumers`).

## Решение

* `GET /api/v1/admin/pools/snapshot` — метрики unified pool manager.
* `GET /api/v1/admin/processes/active` — инстансы workflow'а, готовые к обработке.
* `GET /api/v1/admin/processes/stats` — счётчики по статусам
  (`InstanceStore.count_by_status`).
* Сводка очередей **не поднята**: нет capability — панель остаётся выключенной
  (owner-задача).

## Последствия

* Две панели портала работают; третья честно сообщает об отсутствии эндпоинта.
