# structlog batching wrapper — benchmark и rationale

> Wave: `[wave:s6/k2-structlog-batching]`. Дата: 2026-05-14.
> Файлы: `src/backend/infrastructure/observability/structlog_batching.py`.
> Связь: feedback_wave_7_performance.md, ADR-0059 (Granian RSGI).

## Цель

Замерить выгоду batching-wrapper (50 events / 100ms timeout) над прямым
structlog dispatch для high-RPS hot-path (>1000 RPS, средняя нагрузка
банковского API).

## Конфигурация замера

* Python 3.14, structlog 25.x, orjson 3.10.x (hot-path JSON).
* CPU: Linux 6.17, NCPU=8, RAM 16 GB.
* Workload: имитация 10 000 событий `logger.info("event", **kwargs)` где
  `kwargs` — 5 полей (correlation_id, tenant_id, action, duration_ms,
  status_code).

## Прогноз ожидаемых результатов

| Метрика | structlog direct (baseline) | batching wrapper (flag-ON) | Дельта |
|---|---:|---:|---:|
| p50 latency per log | ~12 мкс | ~2 мкс | **-83%** |
| p95 latency per log | ~25 мкс | ~5 мкс | **-80%** |
| total throughput | ~80 K events/s | **~500 K events/s** | **×6.2** |
| memory overhead | n/a | ~5 KB / batch | минимально |

> NOTE: фактический выигрыш зависит от формат-pipeline (количество
> processor'ов) и backend'а (Graylog GELF / stdout JSON / disk-rotating).
> Если backend — disk-rotating с локальной записью, выгода меньше; если
> Graylog GELF через сеть — выгода ×8..×10.

## Стратегия flush

* `batch_size=50` — компромисс между throughput и latency-SLO (50 событий
  занимают <100ms в pipeline).
* `flush_interval_ms=100` — соответствует p95 banking endpoint SLO (200ms).
  Buffered events флэшатся максимум за 100ms даже без новых событий.
* `max_buffer_size=5000` — leak prevention (V15 R-V15-11): при переполнении
  старые события дропаются с counter в `stats()`.

## Trade-offs

### Плюсы

* Снижение overhead per log call в hot-path до 80%.
* Меньше системных вызовов (write/sendto) → лучше throughput Graylog.
* TaskRegistry-совместимый: фоновый flush-task регистрируется в shutdown.

### Минусы

* Crash-loss: события в буфере (до 5000) теряются при kill -9.
  **Mitigation**: critical/exception-events можно опционально форвардить
  напрямую (TODO в Sprint 7).
* Order: события из разных logger'ов могут переупорядочиваться внутри
  flush batch. **Mitigation**: structlog уже добавляет timestamp в
  processor pipeline — order восстанавливается по timestamp при анализе.
* Sync-контекст: при отсутствии running event loop sync-trigger flush
  не работает — буфер накапливается до следующего асинхронного entry.
  **Mitigation**: все production endpoint'ы — async (Granian/uvicorn).

## Решение

* **Default-OFF** через feature-flag `structlog_batching_enabled`.
* После Sprint 6 staging-smoke с зафиксированным benchmark — перевод
  default-ON в Sprint 7.

## Команды воспроизведения

```bash
# Unit-тесты wrapper'а
uv run pytest tests/unit/infrastructure/observability/test_structlog_batching.py -v

# Микро-benchmark (TODO в Sprint 7 после staging-smoke):
uv run python -m timeit -s "
from src.backend.infrastructure.observability.structlog_batching import (
    get_batching_wrapper,
)
import structlog
w = get_batching_wrapper()
w.bind_inner(structlog.get_logger())
" "w.info('event', correlation_id='abc', tenant_id='t1', action='read', duration_ms=12, status_code=200)"
```

## Связанные документы

* `src/backend/infrastructure/observability/structlog_batching.py` —
  реализация (BatchingStructlogWrapper + get_batching_wrapper).
* `src/backend/infrastructure/logging/batching_router.py` — отдельный
  batching на уровне SinkRouter (Wave 7.7, не дублируется).
* feedback_wave_7_performance.md — orjson hot-path + Granian 2.x.
* PLAN.md V18.2 §S6 K2 W4 (structlog batching).
