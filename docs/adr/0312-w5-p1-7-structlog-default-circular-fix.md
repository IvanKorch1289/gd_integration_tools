# ADR-0312 — W5 P1-7: structlog как default backend (factory auto-detect + circular import fix)

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W5 P1-7 (structlog default per ADR-0084);
  Sprint 60 W1 (Sprint 38: factory + compat shim); Sprint 38 (factory origin).
* Заменяет: Sprint 60 W1 legacy default ``stdlib`` → ``auto`` detection.

## Контекст

MINIMAX baseline зафиксировал: **806 файлов** используют `get_logger()`
фабрику, но factory явно инициализирует stdlib backend в fallback (Sprint 38).
Structlog 26.1.0 (последний release) уже в `pyproject.toml` (`>=24.4.0,<27.0.0`),
а `StructloggraylogBackend` реализован (16 KB) — но **cold-start (без явного
`configure_logging()`) идёт через stdlib**, не structlog.

Это означает: ~800 call sites логируют через stdlib, не используя
structlog's structured key-value logging, PII redaction, correlation
context binding и Graylog JSON-formatted output.

Sprint 60 W1 изменил `configure_logging(backend="structlog")` на default,
но `get_logger()` fallback (line 108) остался явный `"stdlib"`. Это
discrepancy: формально structlog default, на практике — stdlib.

Дополнительно обнаружен **circular import bug** при structlog cold-start:

```
core.interfaces.__init__:50 → get_logger(__name__)
  → factory.get_logger() → _backend is None
  → _create_backend("structlog") → StructlogGraylogBackend().configure()
  → from router import route_to_sinks  ← EAGER
  → router.py:31 → from core.interfaces.log_sink import LogSink
  → core.interfaces.__init__ ← DEADLOCK (partially initialized module)
```

## Решение

### 1. Factory auto-detect (cold-start path)

**`infrastructure/logging/factory.py:get_logger()`** (line 107-110) заменён:

```python
# До (Sprint 60 W1 legacy):
if _backend is None:
    _backend = _create_backend("stdlib")
    _backend.configure()

# После (W5 P1-7, cycle 152):
if _backend is None:
    _backend = _create_backend(_detect_available_backend())
    _backend.configure()

def _detect_available_backend() -> str:
    """Return 'structlog' if installed, else 'stdlib'."""
    try:
        import structlog  # noqa: F401
        return "structlog"
    except ImportError:
        return "stdlib"
```

После этого fix:
- structlog в deps (default в этом проекте) → factory автоматически
  выбирает `StructlogGraylogBackend`.
- Stdlib остаётся fallback только если structlog import fails (graceful
  degradation).

### 2. Circular import fix в structlog_backend

**`infrastructure/logging/structlog_backend.py:configure()`** — eager imports
`route_to_sinks` + `mask_pii` обёрнуты в lazy-processor wrappers:

```python
def _route_to_sinks_lazy(logger, method_name, event_dict):
    from src.backend.infrastructure.logging.router import route_to_sinks
    return route_to_sinks(logger, method_name, event_dict)

def _mask_pii_lazy(logger, method_name, event_dict):
    from src.backend.infrastructure.observability.pii_filter import mask_pii
    return mask_pii(logger, method_name, event_dict)

shared_processors: list[Any] = [
    ...
    _mask_pii_lazy,    # was: mask_pii (eager import → circular)
    _route_to_sinks_lazy,  # was: route_to_sinks (eager import → circular)
]
```

Eager imports удалены из `configure()`. Lazy wrappers импортируют только
когда structlog processor выполняется (т.e. на каждый log call), но не
на module-level — это разрывает circular dependency.

### 3. Тесты

**`tests/unit/infrastructure/logging/test_w5_p1_7_factory_default.py`**
(новый, 8 тестов):

- `TestFactoryAutoDetectBackend` (2): auto-detect returns structlog /
  fallback stdlib.
- `TestGetLoggerUsesStructlogByDefault` (3): cold-start get_logger →
  StructlogLogger; kwargs API; positional args formatting.
- `TestGetLoggerFallbackWhenStructlogUnavailable` (1): graceful stdlib fallback.
- `TestStructlogBackendLazyImport` (2): configure uses lazy processor;
  cold-start works end-to-end.

**Verification**:

```
uv run python -m pytest tests/unit/infrastructure/logging/ -q
  → 52 passed, 1 skipped (psutil integration test)
uv run python -c "from src.backend.core.logging import get_logger; \
                  log = get_logger('test'); log.info('msg', k='v')"
  → JSON output: {'event': 'msg', 'k': 'v', 'logger': 'test', 'level': 'info', ...}
```

## Альтернативы (рассмотренные, отклонённые)

* **Mass-migrate 800+ call sites на structlog явный API**: отклонено —
  ~800 LOC изменений без architectural value (structlog API = kwargs, уже
  совместим со stdlib через compat shim).
* **Force `configure_logging("structlog")` при module load**: отклонено —
  создаёт ещё одну circular import проблему при cold-start, и нарушает
  lazy-init pattern.
* **Заменить `core.interfaces.__init__.py:50` на deferred logger**:
  отклонено — `logger = get_logger(__name__)` это intentional pattern для
  module-level self-logging. Structlog fix (lazy processors) достаточно.

## Последствия

**Плюсы**:

* Structlog теперь default для cold-start — **~800 call sites** автоматически
  переключаются на structured logging без изменения их кода.
* PII redaction (`mask_pii`) применяется ко всем логам.
* Correlation/trace/tenant context binding (`structlog.contextvars`)
  работает out-of-the-box.
* JSON-formatted output готов к ingestion в Graylog через GELF pipeline.
* Stdlib fallback сохранён (graceful degradation).

**Минусы / риски**:

* Существующий код, который полагался на конкретный формат stdlib output
  (e.g. log scraping regex), может сломаться. Mitigated: Sprint 60 W1
  compat shim поддерживает stdlib-style API (`logger.warning("msg %s", arg)`).
* PII filter может медленнее на каждом log call (lazy import overhead).
  Mitigated: lazy imports cached в module dict после первого вызова.

## Verification

```
compileall -q src/ extensions/ scripts/ tools/ tests/  → exit 0
pytest tests/unit/infrastructure/logging/             → 52 passed, 1 skipped
ruff check --select F401,F841,F811,E9                  → All checks passed!
tools/gen_dsl_stubs.py --check                         → exit 0
```

## Связанные изменения

* **`src/backend/infrastructure/logging/factory.py`** — `_detect_available_backend()` +
  `get_logger()` fallback изменён на auto-detect.
* **`src/backend/infrastructure/logging/structlog_backend.py`** — `configure()`
  imports `route_to_sinks` + `mask_pii` обёрнуты в lazy-processor wrappers
  (circular import fix).
* **`tests/unit/infrastructure/logging/test_w5_p1_7_factory_default.py`** —
  новый focused tests (8 tests).
* **`docs/adr/0312-w5-p1-7-structlog-default-circular-fix.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0312 зарегистрирован (105 ADRs total).
* **`CHANGELOG.md`** + **`docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W5 P1-7 (structlog default), ADR-0084 (libraries > custom),
Sprint 60 W1 (compat shim), Sprint 38 (factory origin), ADR-0312 (this),
cycle 152.