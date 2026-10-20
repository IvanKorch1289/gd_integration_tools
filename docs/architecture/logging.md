# Архитектура логирования (Logging Architecture)

> **Версия документа**: V1 (синхронизирована с `ARCHITECTURE.md` от 2026-10-20).
> Актуальное состояние по итогам аудита cycle-160/161.
> Связанные ADR: 0166 (S84 facade closure), 0312 (W5 P1-7 structlog default), 0325 (W6 P1-8 typer migration).

---

## Назначение

`gd_integration_tools` использует **единый стек структурированного логирования** на базе `structlog` + Graylog (GELF). Цели:

1. **Единая точка входа для всех логгеров** — `from src.backend.core.logging import get_logger`. Никаких прямых `import logging` + `logging.getLogger(...)` в бизнес-коде (см. `tools/audit_stdlib_logging.py`).
2. **Структурированные события** — каждое сообщение — это JSON-словарь с фиксированным набором полей (`event`, `level`, `timestamp`, `logger`, `correlation_id`, `request_id`, `tenant_id`, …).
3. **PII-redaction by default** — `mask_pii` processor применяется ко всем логам, маскируя email/phone/passport/snils/inn/card.
4. **Correlation/trace/tenant binding** — `structlog.contextvars.merge_contextvars` + correlation injector (`_inject_correlation` в `structlog_backend.py`).
5. **Ротация и агрегация** — `SinkRouter` направляет каждый `event_dict` в один или несколько активных `LogSink`-ов (Console / Disk / Graylog) с fan-out через `asyncio.gather`.
6. **Graceful degradation** — fallback на stdlib logging, если structlog не установлен (`_detect_available_backend` в `factory.py`).

---

## Структура пакетов

```
src/backend/core/logging/                  ← public facade (lazy re-exports)
├── __init__.py                            ← get_logger, configure_logging,
│                                             init_log_sinks, shutdown_log_sinks,
│                                             shutdown_logging, LoggerProtocol
src/backend/infrastructure/logging/          ← implementation
├── __init__.py                            ← package-level re-exports
├── base.py                                ← BaseLoggerBackend, LoggerProtocol (ABC)
├── factory.py                             ← _backend singleton, _detect_available_backend,
│                                             configure_logging, get_logger,
│                                             init_log_sinks, shutdown_log_sinks,
│                                             shutdown_logging
├── structlog_backend.py                   ← StructlogGraylogBackend + StructlogLogger
├── stdlib_backend.py                      ← StdlibLoggingBackend + StdlibLogger
├── router.py                              ← SinkRouter + build_sinks_for_profile +
│                                             route_to_sinks (structlog processor)
├── batching_router.py                     ← BatchingSinkRouter (Wave 7.7)
└── backends/                              ← LogSink implementations
    ├── console_json.py                    ← ConsoleJsonLogSink (orjson → stdout)
    ├── disk_rotating.py                   ← DiskRotatingLogSink (RotatingFileHandler)
    └── graylog_gelf.py                    ← GraylogGelfLogSink (UDP/TCP GELF +
                                             persistent connection + queue +
                                             circuit-breaker)
```

### Слой core/ vs infrastructure/

| Слой | Назначение |
|---|---|
| `core/logging/` | Public API. **Единственная** точка импорта для всего `src/backend/`, `extensions/`, `routes/`. Реализует lazy `__getattr__` для предотвращения import-time circular deadlock (S84 W1, ADR-001). |
| `core/interfaces/log_sink.py` | Контракт `LogSink` (ABC). Чистый интерфейс без I/O. |
| `infrastructure/logging/` | Реализация: factory, backends, router. **Только `infrastructure/*` может импортировать этот пакет напрямую** — остальные слои идут через facade. |

Layer boundary check — `tests/unit/core/test_logging_layer_check.py` (5 tests) гарантирует,
что `core/`, `services/`, `entrypoints/`, `dsl/`, `plugins/` не импортируют
`src.backend.infrastructure.logging.factory` напрямую (CI gate).

---

## Поток события (Pipeline)

```
┌──────────────────────────────────────────────────────────────────┐
│ logger = get_logger(__name__)                (core.logging facade)   │
│ logger.info("order.created", order_id=123)                         │
└─────────────────┬────────────────────────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────────────────────────┐
│ StructlogLogger (structlog_backend.py)                              │
│   .info(msg, **kwargs) → _format(msg, args, kwargs) → structlog    │
└─────────────────┬────────────────────────────────────────────────┘
                  │
                  ▼ structlog pipeline (config в structlog_backend.py:341)
┌──────────────────────────────────────────────────────────────────┐
│ 1. structlog.contextvars.merge_contextvars     (correlation, trace)│
│ 2. _inject_correlation                          (cid/rid/tid)      │
│ 3. structlog.stdlib.add_logger_name                               │
│ 4. structlog.stdlib.add_log_level                                 │
│ 5. structlog.stdlib.ExtraAdder()                                  │
│ 6. structlog.processors.TimeStamper(fmt="iso")                    │
│ 7. structlog.processors.StackInfoRenderer()                       │
│ 8. structlog.processors.format_exc_info                           │
│ 9. structlog.processors.UnicodeDecoder()                          │
│ 10. _mask_pii_lazy                             (PII redaction)     │
│ 11. _route_to_sinks_lazy                       (fan-out)           │
└─────────────────┬──────────────────────────────────────────────────────────────────┘
                  │
                  ▼ ProcessorFormatter (wrap_for_formatter)
┌──────────────────────────────────────────────────────────────────┐
│ stdlib logging handlers (Graylog GELF + console + disk-rotating)  │
│ Formatter: ProcessorFormatter([remove_processors_meta, renderer]) │
└─────────────────┬──────────────────────────────────────────────────────────────────┘
                  │
                  ▼ route_to_sinks (parallel asyncio.gather)
┌──────────────────────────────────────────────────────────────────┐
│ SinkRouter.dispatch(record) → [Sink1.write(), Sink2.write(), …]   │
│   • ConsoleJsonLogSink — orjson.dumps → sys.stdout                │
│   • DiskRotatingLogSink — RotatingFileHandler (50 MiB × 7)       │
│   • GraylogGelfLogSink — GELF UDP/TCP via async queue             │
└──────────────────────────────────────────────────────────────────┘
```

---

## Профили запуска (build_sinks_for_profile)

| Профиль | Sink-и |
|---|---|
| `dev_light` | `ConsoleJsonLogSink` |
| `dev` | `ConsoleJsonLogSink`, `DiskRotatingLogSink` |
| `staging` / `prod` | `GraylogGelfLogSink`, `DiskRotatingLogSink` (с BatchingSinkRouter) |

`BatchingSinkRouter` (Wave 7.7) включается автоматически для `staging`/`prod`. Очередь
накапливает до `batch_size=100` records или `flush_interval_ms=200`, затем flush'ит
в inner `SinkRouter` параллельно. При переполнении — `dropped` счётчик.

---

## Backend-ы

### `StructlogGraylogBackend` (default)

* structlog 24.4-27.0 (pyproject.toml: `structlog>=24.4.0,<27.0.0`).
* Pipeline processor-ов — 11 штук, включая lazy-imported `_mask_pii_lazy` и
  `_route_to_sinks_lazy` (W5 P1-7 fix, ADR-0312) для устранения circular import
  при cold-start.
* Per-name loggers: можно передать `logger_names=[...]` в `configure()` — для
  каждого имени будет отдельный stdlib logger с собственными handlers
  (`propagate=False`).
* `get_logger(name)` кэширует `StructlogLogger` в `self._loggers: dict[str, StructlogLogger]`.

### `StdlibLoggingBackend` (fallback)

* Используется если structlog не установлен или явно выбран
  (`configure_logging(backend="stdlib")`).
* `StdlibLogger` оборачивает stdlib `logging.Logger` + добавляет `.bind(**kwargs)`
  через `logging.LoggerAdapter`.
* Lifecycle: `configure()` помечает `_configured=True`, `shutdown()` flush'ит
  handlers через `_handler.flush() + _handler.close()` (см.
  `stdlib_backend.py:StdlibLoggingBackend.shutdown`).

### Factory auto-detection

```python
# factory.py:118
def _detect_available_backend() -> str:
    """Return available backend name (structlog if installed, stdlib otherwise)."""
    try:
        import structlog  # noqa: F401
        return "structlog"
    except ImportError:
        return "stdlib"
```

`_create_backend("auto")` → `_detect_available_backend()` → prefer structlog.
После `Sprint 60 W1` (legacy default `"stdlib"`) исправлено на auto-detect в
**W5 P1-7 cycle 152** (ADR-0312).

---

## Public API

### `core.logging.get_logger(name: str) -> LoggerProtocol`

Возвращает логгер. Если backend не сконфигурирован — lazy auto-init:

```python
# factory.py:get_logger()
if _backend is None:
    _backend = _create_backend(_detect_available_backend())
    _backend.configure()
return _backend.get_logger(name)
```

Поддерживает **kwargs-only** стиль (`logger.info("msg", key=val)`) и **stdlib-style**
позиционные args (`logger.warning("msg %s", arg)`) — последнее через compat shim в
`StructlogLogger._format` (Sprint 60 W1).

### `core.logging.configure_logging(backend="structlog", **settings)`

Полная настройка. Параметры: `host`, `port`, `use_tls`, `ca_bundle`, `level`,
`environment`, `log_file`, `log_dir`, `debug`, `logger_names`. Если `_backend`
уже создан — старый shutdown'ится перед новой инициализацией.

### `core.logging.init_log_sinks(profile=None, **kwargs)`

Создаёт profile-based `SinkRouter`. Идемпотентно (повторный вызов заменяет набор).
Принимает: `disk_path`, `graylog_host`, `graylog_port`, `graylog_protocol`.

### `core.logging.shutdown_log_sinks()`

Async! Должен вызываться в lifespan shutdown **до** остальной инфраструктуры.
Дренажит `BatchingSinkRouter` (timeout 5.0s), затем flush + close всех sink-ов.

### `core.logging.shutdown_logging()`

Sync. Flush + close stdlib handlers + sync-close GELF sink-ов (для
`atexit`/signal-handler). Вызывает `_handler.flush() + _handler.close()` для
всех handlers в `logging.root.handlers[:]`.

### `core.logging.LoggerProtocol`

ABC — минимальный интерфейс для type hints. Реализуют `StructlogLogger` и
`StdlibLogger`. Методы: `debug/info/warning/error/critical/exception/log/bind/isEnabledFor`.

---

## Lifecycle: startup/shutdown

### Startup (lifespan)

**Cycle 161 audit (recommended)**: используйте `init_application_logging()`
для централизованной инициализации. Это новый high-level entry point (cycle
161) который делает оба шага с правильным порядком + failure-tolerant startup.

**Cycle 162 fix — settings являются источником истины**. Все параметры
автоматически читаются из settings если caller не передаёт явные override:

| Параметр | Default из settings |
|---|---|
| `level` | `settings.logging.level` (LogStorageSettings) |
| `environment` | `settings.app.environment` (AppBaseSettings) |
| `profile` | `get_active_profile()` (env `APP_PROFILE`) |
| `log_dir` | `settings.logging.dir_log_name` |
| `graylog_host` | `settings.logging.host` |
| `graylog_port` | `settings.logging.port` |
| `graylog_protocol` | `"tcp"` если `settings.logging.use_tls` else `"udp"` |

```python
# manage.py или create_app() lifespan (src/backend/plugins/composition/app_factory.py)
from src.backend.core.logging import init_application_logging as init_app_logging
from src.backend.core.config.profile import get_active_profile

try:
    init_app_logging(
        # Все параметры автоматически из settings (use_settings=True default).
        # Можно override любой через kwargs (см. таблицу выше).
        level=settings.logging.level,
        environment=settings.app.environment,
        profile=get_active_profile(),
        log_dir=settings.logging.dir_log_name,
        graylog_host=settings.logging.host,
        graylog_port=settings.logging.port,
        graylog_protocol="tcp" if settings.logging.use_tls else "udp",
    )
except Exception as exc:  # pragma: no cover — failure-tolerant startup
    get_logger("app_factory").warning(
        "init_application_logging failed: %s", startup_logging_warning_msg, exc
    )

# Или ещё короче — все default из settings, ничего не передавать:
init_app_logging()
```

**Env variables для centralized config**:

| Env variable | Settings field | Назначение |
|---|---|---|
| `APP_PROFILE` | `get_active_profile()` → `AppProfileChoices` | dev_light/dev/staging/prod |
| `LOG_LEVEL` | `settings.logging.level` | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `LOG_HOST` | `settings.logging.host` | Graylog GELF host |
| `LOG_PORT` | `settings.logging.port` | Graylog GELF TCP port |
| `LOG_UDP_PORT` | `settings.logging.udp_port` | Graylog GELF UDP port |
| `LOG_USE_TLS` | `settings.logging.use_tls` | bool — TLS для GELF |
| `LOG_NAME_LOG_FILE` | `settings.logging.name_log_file` | path для DiskRotating |
| `LOG_DIR_LOG_NAME` | `settings.logging.dir_log_name` | directory для DiskRotating |

Этот вызов делает две вещи:

1. `configure_logging(backend="auto", level=..., environment=...)` — инициализирует
   structlog backend (или stdlib fallback) с переданными настройками.
2. `init_log_sinks(profile=..., **kwargs)` — активирует profile-based
   `SinkRouter`, через который fan-out в ConsoleJson / DiskRotating / GraylogGelf.

**Low-level API (legacy, не рекомендуется для нового кода)**:

```python
# Раздельный вызов (до cycle 161)
configure_logging(backend="auto", level="INFO", environment="production")
await init_log_sinks(profile=AppProfileChoices.prod)
# теперь route_to_sinks processor работает (lazy в structlog pipeline)
```

### Shutdown (lifespan)

```python
# shutdown sequence (порядок важен)
await shutdown_log_sinks()      # 1) drain sinks
shutdown_logging()               # 2) flush stdlib handlers + sync-close GELF
```

`structlog_backend.shutdown()` дополнительно вызывает
`GraylogGelfLogSink.close_sync()` для всех sink-ов в router (S60 W1 fix S-L7-3,
GELF FD leak prevention).

---

## Тестовое покрытие

| Тест | Назначение | Файл |
|---|---|---|
| `test_logging_facade.py` (5) | Public API facade, lazy load, backward-compat | `tests/unit/core/` |
| `test_logging_layer_check.py` (5) | Layer boundary CI guard (git grep) | `tests/unit/core/` |
| `test_logging_helpers.py` (13) | `log_with_context`, `log_audit_event_lite` | `tests/unit/core/observability/` |
| `test_log_sinks.py` (13) | ConsoleJson / DiskRotating / GraylogGelf + SinkRouter | `tests/unit/log_sinks/` |
| `test_batching_router_smoke.py` (3) | BatchingSinkRouter smoke | `tests/unit/log_sinks/` |
| `test_pipeline_integration.py` (8) | E2E pipeline integration | `tests/unit/log_sinks/` |
| `test_s60_w1_structlog_e2e.py` (6) | Full structlog → Graylog GELF E2E | `tests/unit/infrastructure/logging/` |
| `test_s60_w1_compat_shim.py` | Sprint 60 W1 compat shim (positional args) | `tests/unit/infrastructure/logging/` |
| `test_s60_w1_socket_shutdown.py` | S60 W1 socket shutdown fix (GELF FD leak) | `tests/unit/infrastructure/logging/` |
| `test_exc_info_traceback.py` | format_exc_info processor (traceback в JSON) | `tests/unit/infrastructure/logging/` |
| `test_pii_in_pipeline.py` | PII redaction в pipeline | `tests/unit/infrastructure/logging/` |
| `test_stdlib_backend_bridge.py` | Stdlib backend bridge tests | `tests/unit/infrastructure/logging/` |
| `test_structlog_logger_name.py` | `logger.name` корректно возвращает имя | `tests/unit/infrastructure/logging/` |
| `test_w5_p1_7_factory_default.py` (8) | Factory auto-detect structlog default | `tests/unit/infrastructure/logging/` |

**Итого: ~95+ unit-тестов покрывают logging stack**. Все проходят на текущий момент
(проверено 2026-10-20, cycle-160/161 audit).

---

## CI gates

1. **`tools/audit_stdlib_logging.py --ci`** — exit 1 если есть новые файлы,
   использующие `import logging` (вне legitimate whitelist из 7 файлов).
   Whitelist: `tests/unit/core/test_legitimate_stdlib_logging.py`.
2. **`tests/unit/core/test_logging_layer_check.py`** — `git grep` на прямые импорты
   `infrastructure.logging.factory` в core/services/entrypoints/dsl/plugins.
3. **`tests/unit/infrastructure/logging/`** — 66 тестов на structlog + sinks + router.
5. **`tests/unit/log_sinks/`** — 24 теста на LogSink implementations.

---

## Известные неконсистентности (status: cycle-160/161 audit)

### Inline `import logging` антипаттерн

`tools/audit_stdlib_logging.py` обнаруживает **183 файла** с inline
`import logging` + `logging.getLogger(__name__).debug(...)` в коде, который
**уже импортирует** canonical facade `from src.backend.core.logging import get_logger`.

Это не нарушает функциональность (оба пути дают рабочий логгер), но нарушает
**unified facade pattern**:

* повторные `import logging` блокируют startup time review
* `logging.getLogger(__name__)` создаёт **отдельный** stdlib-объект логгера,
  отличающийся от того, что вернул бы `get_logger(__name__)` (другой singleton)
* per-call dict lookup overhead

Миграция: **постепенная** (ADR-0330). Уже исправлены: `services/schema_registry/registry.py`
(4 inline-блока → `logger.debug(...)`). Приоритет — файлы с ≥3 inline-блоками.

### Не полностью реализованные методы `LoggerProtocol`

* `addFilter` / `removeFilter` — не в ABC. Если потребуется — расширение
  `LoggerProtocol` в ADR.
* `setLevel` — есть только в `StdlibLogger`, не в `StructlogLogger` (structlog
  не имеет аналога; level задаётся в `configure()`).

### Optional dependency gap

`graypy` (для stdlib graypy fallback в `StructlogGraylogBackend`) — опциональна.
Если отсутствует, GELF отправляется только через собственные raw-socket реализации
в `GraylogGelfLogSink` (см. `backends/graylog_gelf.py`). Не блокирует работу.

---

## Расширение (для разработчиков)

### Добавить новый `LogSink`

1. Создать класс в `src/backend/infrastructure/logging/backends/<name>.py`,
   наследник `core.interfaces.log_sink.LogSink`.
2. Реализовать `async write / flush / close`.
3. Добавить в `build_sinks_for_profile` в `router.py:73-75`.
4. Добавить экспорт в `backends/__init__.py` и `infrastructure/logging/__init__.py`.
5. Написать unit-тесты в `tests/unit/log_sinks/`.

### Добавить новый backend (например, Loki)

1. Создать класс в `src/backend/infrastructure/logging/<name>_backend.py`,
   наследник `BaseLoggerBackend`.
2. Реализовать `configure(**settings)` / `get_logger(name) -> LoggerProtocol` /
   `shutdown()`.
3. Зарегистрировать в `factory._create_backend(name)`.
4. Обновить `LoggerProtocol` если новый backend требует дополнительных методов.

---

## Ссылки

* **ADR-001** — Original core/logging facade design (S27).
* **ADR-0084** — Libraries > custom (structlog dependency declaration).
* **ADR-0166** — Sprint 84 logging.factory Layer Violations Closure.
* **ADR-0312** — W5 P1-7 structlog default circular fix.
* **ADR-0325** — W6 P1-8 typer migration for `tools/migrate_to_structlog.py`.
* **Sprint 60 W1** — Compat shim (`StructlogLogger._format` поддерживает
  stdlib-style positional args).
* **Wave 2.5 (V10)** — LogSink abstraction + SinkRouter + profile-based dispatch.
* **Wave 7.7** — `BatchingSinkRouter` для high-RPS сценариев.

---

## Changelog

| Дата | Изменение |
|---|---|
| 2026-06-12 | ADR-0166 (S84): 274 layer violations закрыты, codemod 253 files |
| 2026-09-23 | ADR-0312 (W5 P1-7): structlog default + circular import fix |
| 2026-10-15 | Re-audit 2026-10-15: console_json.py Python 2 syntax fix (43a9dbcb0) |
| 2026-10-20 | Cycle-160/161 audit: документ создан, schema_registry/registry.py мигрирован |