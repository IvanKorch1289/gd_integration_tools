# Granian RSGI vs ASGI vs uvicorn — production tuning benchmark

> Wave: `[wave:s6/k2-granian-uvloop-tuning]`. Дата планирования: 2026-05-14.
> ADR: `docs/adr/0059-granian-rsgi-production.md`.
> Файлы: `src/backend/core/scaling/granian_tuning.py`, `tools/granian_runner.py`.

## Цель

Sprint 6 K2 DoD требует p95 < 200ms / RPS > 1000 на reference endpoints.
Текущий запуск backend через `uvicorn` без production tuning — baseline
для замера выгоды Granian (RSGI/ASGI 2.x) с uvloop + auto-detected workers.

## Конфигурация замера

* **Машина**: Linux 6.17, NCPU=8, RAM 16 GB, локальный docker-compose.perf.yml
  (postgres + redis + temporal на той же машине).
* **Tooling**:
  * k6 0.50.0 — `tests/perf/k6_baseline.js` MODE=sustained (1000 RPS / 60s).
  * locust 2.29.0 — `tests/perf/locust_baseline.py` (200 VU / 90s).
* **App**: `src.main:app` (FastAPI + Starlette middleware-стек).
* **Endpoints**: 3 reference (60% health / 30% admin_users / 10% credit_check).

## Сценарии

1. **Baseline — uvicorn (uvloop)**:
   ```
   uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4 --loop uvloop
   ```

2. **Granian ASGI (uvloop, default tuning)**:
   ```
   GRANIAN_INTERFACE=asgi \
   FEATURE_GRANIAN_RSGI_MODE_ENABLED=false \
   uv run python tools/granian_runner.py --app src.main:app --port 8000
   ```
   Резолвится в: `granian --interface asgi --workers 8 --loop uvloop --threads 32 ...`

3. **Granian RSGI (uvloop, recommended production tuning)**:
   ```
   FEATURE_GRANIAN_RSGI_MODE_ENABLED=true \
   uv run python tools/granian_runner.py --app src.main:app --port 8000
   ```
   Резолвится в: `granian --interface rsgi --workers 8 --loop uvloop --threads 32 ...`

## Прогноз ожидаемых результатов

Замеры будут выполнены после staging-smoke; ниже — целевые показатели
из ADR-0059 (Sprint 6 K2 DoD: -10..30% latency, +20..50% RPS).

| Метрика | uvicorn (baseline) | Granian ASGI | Granian RSGI |
|---|---:|---:|---:|
| p50 latency (ms) | ~12 | ~9 (-25%) | ~7 (-40%) |
| p95 latency (ms) | ~85 | ~70 (-18%) | ~55 (-35%) |
| p99 latency (ms) | ~180 | ~150 (-17%) | ~110 (-39%) |
| RPS sustained | ~1200 | ~1500 (+25%) | ~1800 (+50%) |
| CPU usage % | ~75 | ~70 (-7%) | ~65 (-13%) |
| Memory RSS (MB) | ~280 | ~260 (-7%) | ~250 (-11%) |

> NOTE: фактические замеры зависят от железа CI runner'а. Локальный
> baseline на NCPU=8 / 16 GB RAM — справочный. После staging-smoke
> обновить эту таблицу с реальными цифрами + ссылкой на k6-summary.json.

## Команды воспроизведения

```bash
# 1. Поднять стек
make perf-suite-up

# 2. Прогнать k6 sustained
K6_MODE=sustained make perf-suite-k6

# 3. Прогнать k6 spike (5000 RPS / 10s)
K6_MODE=spike make perf-suite-k6

# 4. Сравнить с baseline
uv run python tools/perf_gate.py \
  --scenario tests/perf/locust_baseline.py \
  --baseline tests/perf/baseline.json \
  --host http://127.0.0.1:8000 \
  --report dist/perf-report.json

# 5. Дамп Granian-конфига
uv run python tools/granian_runner.py --app src.main:app --dry-run
```

## Решение

* **RSGI default-ON через feature_flag** — `granian_rsgi_mode_enabled`
  активирует RSGI. Перевод в default-ON отдельным PR после Sprint 7
  staging-smoke с зафиксированными показателями.
* **uvloop обязательно** на Linux/macOS — стабильный +15..25% RPS vs
  asyncio.
* **`--workers auto`** — NCPU с min=2, max=16. Для dev_light
  переопределение через `GRANIAN_WORKERS=2`.

## Связанные документы

* ADR-0059 — `docs/adr/0059-granian-rsgi-production.md`
* PLAN.md V18.2 §S6 K2 W2
* `src/backend/core/scaling/granian_tuning.py` — Pydantic-settings класс
* `tools/granian_runner.py` — CLI runner
* feedback_wave_7_performance.md — Granian 2.x runtime_mode API
