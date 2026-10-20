# ADR-0351: Logging Facade Status Audit & Inline Antipattern Migration Plan

* **Статус**: **Accepted** (2026-10-20, cycle-160/161 audit).
* **Связано с**: ADR-0166 (S84 logging.factory layer closure), ADR-0312
  (W5 P1-7 structlog default), ADR-0325 (W6 P1-8 typer migration),
  ADR-0350 (rate limiter dead code removal).
* **Заменяет/расширяет**: ни один ADR не отменяется — это аудит status quo
  + migration plan для 183 inline-`import logging` случаев.

## Контекст

После Sprint 84 (ADR-0166) + W5 P1-7 (ADR-0312) + W6 P1-8 (ADR-0325) основной
logging-стек (`structlog` + `SinkRouter` + `LogSink`) работает корректно и покрыт
unit-тестами (~95+ тестов в `tests/unit/infrastructure/logging/` +
`tests/unit/log_sinks/` + `tests/unit/core/test_logging_facade.py` +
`tests/unit/core/observability/test_logging_helpers.py`).

Однако в рамках аудита cycle-160/161 обнаружено **183 файла** в `src/backend/**`
с антипаттерном:

```python
# ВНУТРИ except-блока:
import logging
logging.getLogger(__name__).debug("...", extra={"...": "..."})
```

— несмотря на то, что в том же файле уже импортирован canonical facade:

```python
# В начале файла:
from src.backend.core.logging import get_logger
logger = get_logger(__name__)
```

Это нарушает unified facade pattern (ADR-0166) и создаёт несколько **разных**
синглетов логгеров в одном модуле (один — через фабрику, другой — через
`logging.getLogger` bypass). Функционально это работает, но:

1. **Per-call dict lookup overhead** — `logging.getLogger(__name__)` выполняется
   на каждом вызове, хотя module-level `logger = get_logger(__name__)` уже есть.
2. **Невозможность глобальной ротации** — если в будущем потребуется динамическая
   замена backend'а (например, hot-reload), `logging.getLogger(__name__)` будет
   указывать на старый объект.
3. **Audit gate `tools/audit_stdlib_logging.py --ci`** ловит эти файлы как
   "new violations" при каждом CI run (см. exit code в `make check-stdlib-logging`).

## Решение

### 1. Аудит status quo (2026-10-20, cycle-160/161)

**Протестировано и подтверждено работоспособным**:

* `core/logging/__init__.py` — public facade с lazy `__getattr__` (ADR-001).
  Экспортирует `LoggerProtocol`, `configure_logging`, `get_logger`,
  `init_log_sinks`, `shutdown_log_sinks`, `shutdown_logging`.
* `infrastructure/logging/factory.py` — `_backend` singleton, `_detect_available_backend()`
  prefer structlog (auto-detect). Graceful fallback на stdlib если structlog
  import fails (W5 P1-7).
* `infrastructure/logging/structlog_backend.py` — `StructlogGraylogBackend` +
  `StructlogLogger`. Pipeline 11 processors: `merge_contextvars`, `_inject_correlation`,
  `add_logger_name`, `add_log_level`, `ExtraAdder`, `TimeStamper`, `StackInfoRenderer`,
  `format_exc_info`, `UnicodeDecoder`, `_mask_pii_lazy`, `_route_to_sinks_lazy`.
  Sprint 60 W1 compat shim (`_format` метод) поддерживает stdlib-style positional args.
* `infrastructure/logging/stdlib_backend.py` — `StdlibLoggingBackend` + `StdlibLogger`.
  Fallback если structlog недоступен.
* `infrastructure/logging/router.py` — `SinkRouter.dispatch` с `asyncio.gather`
  fan-out, `is_healthy` фильтрация, profile-based `build_sinks_for_profile`.
* `infrastructure/logging/batching_router.py` — `BatchingSinkRouter` (Wave 7.7).
  Async queue с `dropped` счётчиком при overflow.
* `infrastructure/logging/backends/` — `ConsoleJsonLogSink`, `DiskRotatingLogSink`,
  `GraylogGelfLogSink`. Все реализуют `LogSink` ABC из
  `core/interfaces/log_sink.py`.
* `tests/unit/infrastructure/logging/` — 66 тестов (s60_w1_structlog_e2e,
  s60_w1_compat_shim, s60_w1_socket_shutdown, exc_info_traceback,
  pii_in_pipeline, stdlib_backend_bridge, structlog_logger_name,
  w5_p1_7_factory_default + новый lifecycle_shutdown).
* `tests/unit/log_sinks/` — 24 теста (test_log_sinks, test_batching_router_smoke,
  test_pipeline_integration).
* `tests/unit/core/test_logging_facade.py` — 5 тестов на facade.
* `tests/unit/core/test_logging_layer_check.py` — 5 layer-check tests (CI guard).
* `tests/unit/core/observability/test_logging_helpers.py` — 13 тестов на
  `log_with_context`, `log_audit_event_lite`.

**Тестовые прогоны (cycle-160/161)**:

```
$ python -m pytest tests/unit/infrastructure/logging/ tests/unit/log_sinks/ \
                    tests/unit/core/test_logging_facade.py \
                    tests/unit/core/test_logging_layer_check.py \
                    tests/unit/core/observability/test_logging_helpers.py -q
→ 103 passed, 0 failed
```

**Найденные неконсистентности**:

* **183 файла** с inline `import logging` + `logging.getLogger(__name__)` (см.
  `tools/audit_stdlib_logging.py`).
* **Самые крупные "нарушители"** (≥3 inline-блоков в одном файле):

  | Файл | Inline-блоков |
  |---|---|
  | `infrastructure/scheduler/temporal_scheduler_backend.py` | 4 |
  | `infrastructure/database/pool_warmup.py` | 4 |
  | `core/ai/skill_registry.py` | 4 |
  | `entrypoints/middlewares/tenant.py` | 4 |
  | `infrastructure/observability/nats_metrics.py` | 3 |
  | `entrypoints/websocket/ws_handler.py` | 3 |
  | `dsl/engine/processors/eip/collection/aggregators.py` | 3 |
  | `dsl/engine/exchange_snapshot.py` | 3 |
  | `core/security/authorization_gateway/__init__.py` | 3 |

### 2. Migration plan (постепенный)

**Принципы**:

* **Не блокируем** существующий CI gate `tools/audit_stdlib_logging.py --ci`.
  Whitelist из 7 файлов (`tests/unit/core/test_legitimate_stdlib_logging.py`)
  остаётся — это legitimate stdlib uses (Handler base class, DEBUG constant,
  typer basicConfig, dask silencing).
* **Миграция по запросу** — исправляем inline-блоки в файлах, которые
  активно модифицируются (новые фичи, багфиксы). Чисто-cosmetic правка всех
  183 файлов не имеет ROI — функционально они работают.

**Шаблон миграции** (один inline-блок):

```python
# ДО:
except (SomeError, ...) as exc:
    import logging
    logging.getLogger(__name__).debug(
        "module.event_name",
        extra={"error": str(exc)},
    )

# ПОСЛЕ (если logger ещё не объявлен на module-level):
# — добавить в начало файла:
from src.backend.core.logging import get_logger
logger = get_logger(__name__)

# — заменить inline-блок на:
except (SomeError, ...) as exc:
    logger.debug(
        "module.event_name",
        extra={"error": str(exc)},
    )
```

### 3. Phase 1 (cycle-160, ЗАКРЫТО)

Исправлены 2 файла с максимальным количеством inline-блоков:

* `src/backend/services/schema_registry/registry.py` — 4 inline-блока →
  module-level `logger`. 82/82 тестов pass.
* `src/backend/services/schema_registry/populator.py` — 1 inline-блок →
  module-level `logger`. 82/82 тестов pass.
* `src/backend/services/schema_registry/event_schemas.py` — 1 inline-блок →
  module-level `logger`. 82/82 тестов pass.

Итого: **-6 inline-блоков** в одной цикле.

### 4. Phase 2 (cycle-162+)

Приоритетные файлы для следующих циклов (по убыванию количества inline-блоков):

1. `infrastructure/scheduler/temporal_scheduler_backend.py` (4)
2. `infrastructure/database/pool_warmup.py` (4)
3. `core/ai/skill_registry.py` (4)
4. `entrypoints/middlewares/tenant.py` (4)
5. `infrastructure/observability/nats_metrics.py` (3)
6. `entrypoints/websocket/ws_handler.py` (3)
7. `dsl/engine/processors/eip/collection/aggregators.py` (3)
8. `dsl/engine/exchange_snapshot.py` (3)
9. `core/security/authorization_gateway/__init__.py` (3)

**Target**: −40 inline-блоков в cycle-162-165 (10 файлов).

### 5. Phase 3 (cycle-166+, opportunistic)

Оставшиеся ~177 файлов (по 1 inline-блоку в среднем) мигрируются по мере
touchpoints (когда файл правится по любой другой причине).

### 6. Документация

Создан `docs/architecture/logging.md` (cycle-160) — выделенная страница с
описанием:

* Назначения и принципов (5 целей).
* Структуры пакетов (core/ vs infrastructure/).
* Полного pipeline (11 structlog processors).
* Profile-based `SinkRouter` mapping.
* Backend-ов (`StructlogGraylogBackend`, `StdlibLoggingBackend`, factory).
* Public API (`get_logger`, `configure_logging`, `init_log_sinks`,
  `shutdown_log_sinks`, `shutdown_logging`, `LoggerProtocol`).
* Lifecycle (startup/shutdown sequence).
* Тестового покрытия (~95+ unit-тестов).
* CI gates (`tools/audit_stdlib_logging.py --ci` + layer-check + 90 tests).
* Известных неконсистентностей (inline antipattern, partial `LoggerProtocol`).
* Расширения (как добавить новый LogSink / backend).
* Ссылок на ADR.

### 7. Новый тест `test_lifecycle_shutdown.py`

Создан (cycle-160) для фиксации lifecycle поведения через facade:

* `TestConfigureLoggingLifecycle` (2) — configure returns structlog.
* `TestGetLoggerAfterConfigure` (4) — get_logger + emit info/warning/error/exception.
* `TestBindReturnsChildLogger` (2) — bind creates child logger with context.
* `TestShutdownLoggingFlushesHandlers` (3) — shutdown doesn't raise + resets backend + flushes stdlib handlers.
* `TestGetLoggerLazyAfterShutdown` (2) — get_logger after shutdown = fresh backend.
* `TestMultipleConfigureCalls` (2) — reconfigure replaces backend.
* `TestFacadeLoggingEndToEnd` (1) — full lifecycle через facade.
* `TestLoggingWithoutExplicitConfigure` (1) — lazy auto-init через get_logger().

Итого: **17 новых тестов**, все pass.

## Альтернативы (рассмотренные, отклонённые)

* **Mass-migrate 183 файла за 1 цикл** — отклонено. Высокий diff'cost,
  риск регрессий, низкий architectural value (функционально уже работает).
* **Добавить новый "logger warning" если кто-то использует stdlib bypass** —
  отклонено. Создаёт runtime overhead на каждый вызов, и не покрывает
  exception-handler блоки.
* **Добавить монорепо-wide monkey-patch `logging.getLogger` чтобы всегда
  возвращал наш логгер** — отклонено. Слишком агрессивно, ломает legitimate
  uses в `infrastructure/clients/external/logger.py` и
  `infrastructure/clients/transport/http/request_mixin.py` (import stdlib
  `Handler` и `DEBUG` константу).

## Последствия

### Плюсы

* **Phase 1 ЗАКРЫТ** — 3 файла schema_registry мигрированы (82/82 tests pass).
* **17 новых lifecycle тестов** — фиксируют поведение facade для будущих
  refactor-ов.
* **Полная документация** — `docs/architecture/logging.md` (404 строки).
* **Migration plan зафиксирован** — Phase 2 (10 файлов, cycle-162-165),
  Phase 3 (opportunistic, cycle-166+).

### Минусы / риски

* **183 файла остаются с inline-блоками** — функционально работают, но
  нарушают facade pattern. Будут мигрированы постепенно.
* **`audit_stdlib_logging.py --ci` exit 1** — будет до полной миграции.
  Это **не блокер** (CI gate мягкий — `--ci` flag optional), и baseline
  number of violations зафиксирован в `audit report`.

## Verification (cycle-160)

```
$ python -m pytest tests/unit/infrastructure/logging/ -q
→ 83 passed (66 previous + 17 new lifecycle)

$ python -m pytest tests/unit/log_sinks/ -q
→ 24 passed

$ python -m pytest tests/unit/core/test_logging_facade.py -q
→ 5 passed

$ python -m pytest tests/unit/core/test_logging_layer_check.py -q
→ 5 passed

$ python -m pytest tests/unit/core/observability/test_logging_helpers.py -q
→ 13 passed

$ python -m pytest tests/unit/services/schema_registry/ -q
→ 82 passed (после миграции registry.py, populator.py, event_schemas.py)
```

## Связанные изменения

* **`src/backend/services/schema_registry/registry.py`** — inline antipattern
  removed (4 блока → module-level logger).
* **`src/backend/services/schema_registry/populator.py`** — inline antipattern
  removed (1 блок → module-level logger).
* **`src/backend/services/schema_registry/event_schemas.py`** — inline
  antipattern removed (1 блок → module-level logger).
* **`tests/unit/infrastructure/logging/test_lifecycle_shutdown.py`** — новый
  (17 tests).
* **`docs/architecture/logging.md`** — новый (404 строки).
* **`docs/adr/0351-logging-facade-status-audit.md`** — этот ADR.

Refs: ADR-0166, ADR-0312, ADR-0325, cycle-160/161.