# ADR-0392 — Логирование: ReDoS в PII-регексе, доставка audit-событий, structlog-стек, дефолты конфигурации

* Статус: Accepted (2026-10-29, волна 18 повторного аудита, кластер G3 — логирование)
* Cycle: 178
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/core/security/pii_patterns.py` (EMAIL-регекс, fast-path `sub_email`)
  - `src/backend/entrypoints/middlewares/data_masking.py` (быстрый путь маскирования)
  - `src/backend/core/audit/facade/_base.py` (sync-доставка audit-событий)
  - `src/backend/entrypoints/middlewares/request_log.py` (structlog-стек + маскирование тел)
  - `src/backend/core/di/providers/workflow/_loggers.py` (документация legacy-провайдера)
  - `src/backend/infrastructure/logging/factory.py` (`level`/`environment`/`log_filename`)
  - `src/backend/infrastructure/logging/structlog_backend.py` (окружение по умолчанию)
  - `src/backend/infrastructure/logging/router.py` (один writer-поток вместо потока на вызов)
  - `tests/unit/core/security/test_pii_patterns_redos.py` (новый)
  - `tests/unit/core/audit/test_emit_audit_sync_delivery.py` (новый)
  - `tests/unit/entrypoints/middlewares/test_request_log_structlog.py` (новый)
  - `tests/unit/infrastructure/logging/test_factory_level_environment.py` (новый)
  - `tests/unit/infrastructure/logging/test_router_sync_writer.py` (новый)
- **Связан с**:
  - ADR-0351 (централизованная инициализация logging-стека), ADR-0312 (lazy structlog-backend)
  - ADR-0364 (мёртвая конфигурация = ложь в конфиге) — п. 7
  - ADR-0190 / ADR-0187 (канонический audit-facade), ADR-0393 (audit-доставка)
  - ADR-0384 (S221/S222 — shared PII-паттерны как single source of truth)
- **Вне зоны (нужны чужие файлы)**:
  - `src/backend/core/security/pii_masker.py` и `src/backend/infrastructure/observability/pii_filter.py`
    — вызывают `EMAIL.sub()` напрямую; fast-path к ним не применён (вне кластера),
    но сам регекс теперь линеен, поэтому ReDoS там устранён;
  - `src/backend/entrypoints/middlewares/audit_log.py`, `timeout.py` — используют legacy
    `get_app_logger_provider()`; перевод на structlog вне кластера;
  - `src/backend/infrastructure/external_apis/logging_service.py` — legacy `LoggerManager`
    (единственное место, где `log.conf_loggers` реально применяется);
  - `src/backend/infrastructure/logging/batching_router.py` — батчер-паттерн переиспользован
    как образец, но сам не менялся.

---

## Контекст

Волна 18 повторного аудита вех нашла 7 дефектов в кластере G3 (логирование):

1. **[high] ReDoS в EMAIL-регексе.** `core/security/pii_patterns.py`:
   `EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")`. `re.sub` перебирал каждую
   стартовую позицию, а `[\w.+-]+` жадно съедал остаток строки и откатывался
   по одному символу — квадратичный рост: 10 KB → 238 мс, 50 KB → 6.1 с,
   100 KB → 27 с. Тот же паттерн в `entrypoints/middlewares/data_masking.py`
   давал stall на каждом ответе с длинными строками → блокировка event loop.
2. **[high] Audit-события терялись в sync-контексте.** `core/audit/facade/_base.py`:
   при отсутствии running event loop корутина закрывалась (`coro.close()`),
   событие уничтожалось (`audit.emit.dropped_no_event_loop`). Страдали FastAPI
   sync-эндпоинты (threadpool), `asyncio.to_thread`, CLI.
3. **[high] Логи запросов/ответов шли мимо structlog-стека.** `request_log.py`
   брал логгер через `get_app_logger_provider()` → legacy
   `external_apis.logging_service.app_logger` (`propagate=False` + `QueueHandler`):
   запись не доходила до root-handler'а, вывод был plain-text (без JSON,
   `correlation_id`, PII-маскирования), а тела запроса/ответа писались
   **незамаскированными** (в dev `log_requests: true`) → утечка PII.
4. **[medium] Явный `level=` игнорировался.** `infrastructure/logging/factory.py`:
   sentinel `if level == "INFO"` подменял явно переданный `"INFO"` значением из
   settings (`init_application_logging(level="INFO")` → root level DEBUG).
5. **[medium] `environment="production"` в lazy-пути.** `structlog_backend.py`:
   `get_logger()` без `init_application_logging` (CLI, воркеры) всегда писал
   `environment=production` независимо от профиля.
6. **[medium] Thread-per-log-call.** `infrastructure/logging/router.py`:
   каждый sync-вызов `route_to_sinks` порождал свой поток (50 вызовов → 50 потоков).
7. **[low] Мёртвый конфиг.** `log.conf_loggers` и `log.name_log_file` не
   применялись новым стеком; имя файла disk-sink'а было захардкожено `app.jsonl`.

---

## Решение

### 1. EMAIL-регекс: ограниченные квантификаторы + possessiv-группы + fast-path

`EMAIL = re.compile(r"[\w.+-]{1,64}+@[\w-]{1,255}+(?:\.[\w-]{1,63}+)+")`

* квантификаторы ограничены по RFC 5321: local-part ≤ 64, домен ≤ 255, label ≤ 63;
* possessiv-группы (`{n,m}+`) запрещают бэктрекинг внутри группы — при неудаче
  движок переходит к следующей стартовой позиции, а не перебирает длины;
* домен разложен на label'ы, поэтому длинный хвост не съедается целиком.

Скан стал линейным: 100 KB ≈ 30 мс (было 27 с). Дополнительно в
`pii_patterns.py` добавлен публичный helper `sub_email(repl, value)` с
fast-path `if "@" not in value: return value` — без `@` email невозможен,
regex не запускается вовсе. `data_masking.py` переведён на этот helper.

### 2. Sync-контекст: доставка audit-события вместо потери

`core/audit/facade/_base.py` получил выделенный фоновый event loop
(daemon-поток `audit-sync-dispatch` + `asyncio.run_coroutine_threadsafe`).
Корутина больше не закрывается; событие **доставляется** в unified
audit-service. Вызывающий поток не блокируется, `contextvars`
(`correlation_id`/`tenant_id`) пропагаются в фоновую доставку, а невозможность
доставки фиксируется явной ошибкой `audit.emit.dropped_sync_delivery_failed`
(не тишиной). Реестр фонового loop'а закрывается через `atexit`.

### 3. Request-логирование: structlog-стек + маскирование тел

`request_log.py` переведён на `src.backend.core.logging.get_logger` и
структурированные события (`http.request`, `http.response`,
`http.request_body`, `http.response_body`) с полями `method`/`path`/`status`/
`duration_ms`. Тела запроса и ответа проходят через канонический маскер
`core.security.pii_masker.default_masker` — тот же, что в
`pii_masking_response.py`. Провайдер `get_app_logger_provider()` помечен
в docstring как legacy (его ещё используют `audit_log.py` и `timeout.py` —
вне кластера).

### 4–5. Дефолты `level` / `environment` — из настроек

* `init_application_logging(level: str | None = None, environment: str | None = None)`:
  дефолт определяется **только** через `None`; явное значение всегда уважается.
* `StructlogGraylogBackend.configure(environment: str | None = None)`:
  при `None` окружение берётся из `settings.app.environment` (ленивый импорт
  в `try/except` + фоллбэк на `app_base_settings` — без цикла импорта при
  cold-start; при полной недоступности настроек — `"production"`).

### 6. Один writer-поток вместо потока на вызов

`router.py`: sync-диспатчер переведён на bounded-очередь (`queue.Queue`,
maxsize 10 000) и единственный фоновый writer-поток `log-sink-writer`
(по образцу `batching_router.py`). Переполнение очереди → drop со счётчиком
и предупреждением; логгер никогда не блокируется.

### 7. `log.name_log_file` — применён; `log.conf_loggers` — задокументирован

* `init_application_logging` получил параметр `log_filename`; при `None`
  берётся `settings.logging.name_log_file` (вместо захардкоженного `app.jsonl`).
* `log.conf_loggers` применяется **только** legacy-`LoggerManager`
  (`external_apis/logging_service.py`): это карта Graylog-facility'ов
  (`name`/`facility`) для удалённого транспорта. Новый structlog-стек её не
  использует и не может использовать без дублирования legacy-обработчиков,
  поэтому ключ оставлен как есть и явно описан в этом ADR (а не «мёртвый»
  молча). Снятие ключа из конфигурации — вне кластера.

---

## Альтернативы (отклонённые)

1. **Оставить EMAIL как был, добавить только fast-path.** Отклонено: fast-path
   не спасает строки, где `@` есть, но домен неполный (например, длинный
   текст с одним e-mail в середине) — бэктрекинг остаётся.
2. **Ограничить квантификаторы без possessiv-групп.** Отклонено: без
   possessiv-групп движок всё ещё перебирает длины при неудаче (линейно, но
   с большим константным множителем); possessiv даёт гарантию «один проход».
3. **В sync-контексте блокировать вызывающий поток (`asyncio.run(coro)`).**
   Отклонено: FastAPI sync-эндпоинт ждал бы записи в ClickHouse на каждом
   audit-событии —latency-риск в threadpool.
4. **Синхронный backend записи вместо фонового loop'а.** Отклонено: audit
   backend (`ClickHouseAuditService`) асинхронный; синхронный путь потребовал
   бы дублирования клиента.
5. **Оставить `emit_audit` возвращающим `None` в sync-контексте, но писать
   ошибку.** Отклонено: это тишина с другой подписью — событие всё равно
   терялось бы.
6. **Перевести `audit_log.py`/`timeout.py` на structlog в этом же кластере.**
   Отклонено: файлы вне зоны кластера (G3) — правка требует отдельного
   кластера, чтобы не смешивать ревью.
7. **Применить `conf_loggers` как `logger_names` в structlog-бэкенде.**
   Отклонено: `StructlogGraylogBackend.configure(logger_names=...)` ставит
   `propagate=False` и заменяет handlers'ы — это конфликтует с legacy
   `LoggerManager` (который сбрасывает handlers'ы при создании) и оставляет
   именованные логгеры вообще без вывода.

---

## Последствия

* **Позитивные:** маскирование PII больше не блокирует event loop (100 KB →
  30 мс вместо 27 с); audit-события из sync-контекста не теряются; логи
  запросов/ответов идут в JSON-стек с `correlation_id` и маскированием PII;
  явный `level=`/`environment=` уважаются; CLI и воркеры пишут окружение
  профиля; число потоков на 50 sync-логов — 1 вместо 50; имя файла логов
  берётся из конфигурации.
* **Негативные / breaking:** `emit_audit()` в sync-контексте теперь возвращает
  `concurrent.futures.Future` доставки (вместо `None`) — сигнатура
  документирована, `await`-вызовы (в async-контексте) не изменились;
  формат request-логов структурированный (поиск по старым plain-text
  сообщениям в дашбордах требует обновления запросов);
  `log.name_log_file` теперь реально применяется — имя файла меняется с
  `app.jsonl` на значение конфигурации (`app.log` в base-профиле).
* **Ограничение (ponytail):** fast-path `sub_email` применён только там, где
  файл в зоне кластера; остальные потребители `EMAIL` получают линейный
  (но не fast-path) скан. Writer-поток логов — один на процесс; при
  переполнении очереди (10 000 записей) записи отбрасываются со счётчиком.

---

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/core/security/test_pii_patterns_redos.py -q
.venv/bin/python -m pytest tests/unit/core/audit/test_emit_audit_sync_delivery.py -q
.venv/bin/python -m pytest tests/unit/entrypoints/middlewares/test_request_log_structlog.py -q
.venv/bin/python -m pytest tests/unit/infrastructure/logging/test_factory_level_environment.py -q
.venv/bin/python -m pytest tests/unit/infrastructure/logging/test_router_sync_writer.py -q
.venv/bin/python -m pytest tests/unit/core/security tests/unit/infrastructure/logging \
    tests/unit/entrypoints/middlewares tests/unit/core/audit -q -p no:randomly
.venv/bin/python -m ruff check <файлы кластера>
.venv/bin/python tools/config_audit.py --scope orphans       # 0
.venv/bin/python tools/check_layers.py --strict               # 41 (baseline, без новых)
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

---

## Связи с другими ADR

* **ADR-0351** — централизованная инициализация logging-стека: пункты 4–5
  делают её параметры действительно управляемыми (явный `level`/`environment`).
* **ADR-0312** — lazy structlog-backend: пункт 5 задаёт корректный дефолт
  окружения именно для lazy-пути.
* **ADR-0364** — мёртвая конфигурация = ложь в конфиге: пункт 7 применяет
  `log.name_log_file` и честно описывает судьбу `log.conf_loggers`.
* **ADR-0190 / ADR-0187** — канонический audit-facade: пункт 2 сохраняет
  единую точку emit и убирает потерю событий.
* **ADR-0384** — S221/S222: `core/security/pii_patterns.py` остаётся
  single source of truth для PII-паттернов; изменена только форма
  квантификаторов.
