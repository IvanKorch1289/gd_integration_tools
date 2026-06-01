# ADR-0059 — Granian RSGI production tuning

* Статус: Accepted (Sprint 6 K2, 2026-05-14)
* Связано с: V15 R-V15-10 (auto-scaling 3 уровня), PLAN.md V18.2 §S6 K2 W2.

## Контекст

Sprint 6 K2 DoD требует подтверждённого баланса latency/throughput на
reference endpoints (p95 < 200ms, RPS > 1000 sustained). Существующий
запуск backend через `uvicorn` (uvloop) даёт удовлетворительный baseline,
но Granian (RSGI/ASGI 2.x) при оптимальной конфигурации показывает
лучший latency на коротких запросах за счёт нативной Rust event-loop
интеграции.

Текущее состояние:
* `src/main.py` поддерживает запуск через `APP_SERVER=granian|uvicorn`;
* Granian запускается с дефолтным `--workers 1 --interface asgi` — нет
  tuning'а `blocking_threads`, `loop=uvloop`, RSGI-режима;
* нет ADR, фиксирующего набор production-флагов;
* нет benchmark-замера до/после.

## Решение

1. **RSGI-режим default-ON для Granian (но feature-flag-gated)** —
   `granian_rsgi_mode_enabled` (default-OFF). При `true` `granian_runner.py`
   запускает Granian с `--interface rsgi` вместо `--interface asgi`. RSGI
   даёт минимальную накладную при работе с ASGI-приложениями через
   pre-compiled message frames.

2. **Tuning набор production-флагов**:
   * `--workers $NCPU` — auto-detect через `os.cpu_count()` (минимум 2,
     максимум через `--max-workers`);
   * `--blocking-threads auto` — Granian сам подбирает thread-pool size
     по `(NCPU * 4)`;
   * `--loop uvloop` — `--loop=uvloop` обязательно (не `--loop=asyncio`);
   * `--http auto` — HTTP/1.1 default, HTTP/2 при поддержке (TLS);
   * `--log-level info`, `--access-log` — структурированные логи через
     structlog;
   * SIGUSR1/SIGUSR2 поддержка для dynamic worker fork (V15 R-V15-10
     уровень 1, см. `LocalProcessScaler`).

3. **Запуск через `tools/granian_runner.py`** — единая точка входа,
   читает `core.config.scaling.GranianTuning` (новый Pydantic-settings),
   формирует `granian` CLI-команду или `granian.Granian(...)` инстанс.

4. **Benchmark до/после** — фиксируется в
   `vault/benchmark-2026-05-15-granian.md` с замерами:
   * baseline uvicorn (1000 VU, 60s): p50/p95/p99/RPS;
   * Granian ASGI (uvloop): дельта vs baseline;
   * Granian RSGI (uvloop): дельта vs baseline (целевая выгода: -10..30%
     по latency, +20..50% по RPS).

5. **CI integration** — `make perf-suite-up` поднимает Granian с
   RSGI-конфигом из `docker-compose.perf.yml`; `make perf-suite-k6`
   запускает k6 нагрузку; результаты сравниваются с baseline.json
   через `tools/perf_gate.py --baseline`.

## Последствия

### Положительные

* Подтверждённый best-effort production-tuning Granian.
* Декларативная конфигурация в `core.config.scaling.GranianTuning`
  (Pydantic-settings + YAML-overlay).
* Feature-flag `granian_rsgi_mode_enabled` позволяет постепенно
  тестировать RSGI без блокирования релизов.
* Замер до/после — артефакт для performance-аудита.

### Риски

* RSGI требует Granian ≥ 1.4 (текущая стабильная — 1.6.x); pin в
  `pyproject.toml::dependencies`.
* SIGUSR1/SIGUSR2 worker-fork не работает на Windows — fallback на
  `--workers` без dynamic scaling в dev_light.
* uvloop несовместим с Windows — для dev на Windows используется
  `--loop asyncio` (документирован в README).

## Альтернативы

* Hypercorn (asyncio HTTP/2/3) — отвергнут, latency хуже Granian при
  short-request load (2026-04 benchmark).
* gunicorn + uvicorn workers — отвергнут, нет нативной RSGI; больше
  накладных на process fork.
* uvicorn standalone — текущий dev_light дефолт; оставлен для разработки.

## План внедрения

1. Sprint 6 K2 W2 (текущий): создать `core/config/scaling.py::GranianTuning`,
   `tools/granian_runner.py`, ADR-0059, обновить `docker-compose.perf.yml`.
2. Sprint 6 K2 W2: benchmark до/после в
   `vault/benchmark-2026-05-15-granian.md`.
3. Sprint 7: перевести `granian_rsgi_mode_enabled` в default-ON после
   staging-smoke.

## Ссылки

* https://github.com/emmett-framework/granian
* https://www.starlette.io/middleware/ — ASGI-совместимость
* PLAN.md V18.2 §S6 K2 W2 (Granian RSGI production tuning)
* feedback_wave_7_performance.md — orjson hot-path + Granian 2.x runtime_mode API
