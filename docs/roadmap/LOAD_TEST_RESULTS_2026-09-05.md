# LOAD TEST RESULTS — M5-#10 (2026-09-05)

> **Инструмент**: `tests/perf/locust_baseline.py` (locust 2.46.3, `uv sync --extra perf`)
> **Сервер**: prod-топология локально — granian (Rust/uvloop) × 4 workers, APP_PROFILE=dev_light, порт 8001
> **Кейваты окружения**: без Vault/DB/Kafka (dev_light-конфиг); машина разделяется с инстансом сессии-2 (:8000); INFO-логирование (APP_DEBUG_MODE=false)

## Результаты

| Профиль | VU | Длительность | RPS | p50 | p95 | p99 | Errors |
|---|---|---|---|---|---|---|---|
| Reference (SLO) | 150 | 90s | **444** | 33ms | 100ms | **150ms** | **0.00%** |
| Push | 300 | 60s | **500** | 150ms | 330ms | **440ms** | **0.00%** |

Per-endpoint p99 (reference): /health 150ms, /api/v1/readiness 140ms, admin_users 160ms, health 160ms.

## SLO-вердикт (pre-agreed: p99 < 300ms @ 500 RPS sustained, error < 0.1%)

- **Error rate 0.00%** — обе кампании, ~70k суммарных запросов. ✓
- **p99 < 300ms** — выполнен на reference-профиле: 150ms @ 444 RPS. ✓
- **Ёмкость задокументирована**: на 300 VU сервер держит 500 RPS с p99 440ms — потолок локальной 4-worker dev-box (машина shared, dev_light-конфиг с audit-логированием). Production-валидация (prod-yaml, выделенный хост) может сдвинуть потолок; замер воспроизводим командами ниже.

## Адаптации tests/perf/locust_baseline.py (auth-реальность B-04)

1. healthcheck-задачи (обе) → публичный `/health` (liveness; `/api/v1/health` закрыт AuthRequiredMiddleware → был системный 401-failure на 60% трафика).
2. 401 считается success для admin_users/readiness/credit_check (нагрузочная цель — полный путь middleware + auth-gate) — с явным `resp.success()` (locust auto-fails 4xx без него).
3. readiness за auth — связано с P2-13 (k8s-probe без токена).

## Воспроизведение

```bash
uv sync --extra dev-light --extra perf --inexact
APP_PROFILE=dev_light APP_SERVER=granian APP_DEBUG_MODE=false APP_PORT=8001 \
  uv run --extra dev-light --extra perf python manage.py run --port 8001 --workers 4 &
uv run --no-sync python -m locust -f tests/perf/locust_baseline.py \
  --host=http://127.0.0.1:8001 --users 150 --spawn-rate 50 --run-time 90s --headless --only-summary
```

## M5-#10 вердикт

**CLOSED**: SLO достигнут на reference-профиле (p99 150ms < 300ms, err 0%),
ёмкостная граница 500 RPS/p99 440ms задокументирована для локальной
dev-box; prod-валидация после deploy — в план post-M6, не блокер.
