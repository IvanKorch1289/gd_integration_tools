# tests/perf — нагрузочные профили (Wave 7.6)

## Целевые SLO (V10 #14)

* `http_req_duration` p(95) < **200ms**.
* RPS > **1000** sustained.
* error rate < **1%**.

## k6 (Go binary, system-level dep)

Установка: см. https://k6.io/docs/get-started/installation/.

```bash
k6 run -e BASE_URL=http://127.0.0.1:8000 tests/perf/k6_baseline.js
```

## locust (Python, опц. extra)

Установка через extras: `uv sync --extra perf`.

```bash
locust -f tests/perf/locust_baseline.py \
    --host=http://127.0.0.1:8000 \
    --users 100 --spawn-rate 10 --run-time 3m \
    --headless
```

UI-режим: убрать `--headless`, открыть `http://127.0.0.1:8089/`.

## Smoke-проверка

Перед прогоном баз приложение должно быть запущено с production-tuning'ом:

```bash
APP_SERVER=granian APP_WORKERS=4 uv run python -m src.main
```
