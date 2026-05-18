# Performance scenarios

Перформанс-suite К5 (Wave K5/perf-gate). Все сценарии измеряют единый набор SLO:

* **p95 < 200ms** (V10 #14 performance budget);
* **error rate < 1%**;
* **RPS > 1000** (на 100 VU).

## Сценарии

### `k6_baseline.js`
Базовый smoke-профиль. Steady-state 100 VU 2 минуты на `/api/v1/health`.
Используется в `make perf-smoke`.

### `k6_action_routes.js`
Read-heavy: `GET /api/v1/admin/routes` — middleware-стек + RouteRegistry.
Используется в `make perf-gate` (CI gate).

### `k6_dsl_invocation.js`
Write-path через `POST /api/v1/dsl/invoke`. ROUTE_ID читается из env-var
для изоляции от К2 (RouteLoader full-cycle, Sprint 2).

### `locust_baseline.py`
Минимальный locust-профиль: `/api/v1/health` + `/api/v1/readiness`.
Используется в `make perf-full` для длинных запусков.

### `locust_full_profile.py`
Расширенный mix: health × 8, admin-routes × 3, admin-actions × 2,
readiness × 1.

## Запуск

```bash
# 1. Поднять backend в фоне
make dev-light &
sleep 8

# 2. SLO-gate
make perf-gate

# 3. Длинный профиль
make perf-full
```

## CI

`.github/workflows/perf.yml`:
* job `k6-smoke` — `pull_request` + `workflow_dispatch`;
* job `locust-headless` — `schedule '0 3 * * *'` (nightly).

Артефакты (k6 summary, locust HTML report) хранятся 14 дней.

## Результаты SLO

| Сценарий | p95 (ms) | RPS | Error rate |
|---|---|---|---|
| `k6_baseline.js` | < 50 | > 2000 | 0% |
| `k6_action_routes.js` | < 200 | > 1000 | < 1% |
| `k6_dsl_invocation.js` | < 300 | > 500 | < 2% |
| `locust_full_profile.py` | < 250 | > 1500 | < 1% |
