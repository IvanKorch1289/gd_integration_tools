# ADR-0368 — Отказоустойчивость RPA: cleanup-финализаторы, живой circuit breaker, таймауты внешних вызовов

* Статус: Accepted (2026-10-28, cycle 172)
* **Cycle**: 172 (Wave 14, кластер C3 — отказоустойчивость RPA)
* **Связан с**:
  - ADR-0305 (circuit-breaker consolidation на purgatory; narrow-timeout + admission-control)
  - ADR-0354 (services → DSL зависимости; DSL не импортирует `services.*` напрямую)
  - ADR-0361 (семантика `required_capability`)
  - ADR-0366 (capability-гейт DSL, cycle 172)
  - ADR-0369 (достижимость RPA-шагов из YAML, cycle 172)
* **Затрагивает**:
  - `src/backend/dsl/engine/execution_engine.py`
  - `src/backend/services/rpa/desktop_session_pool.py`
  - `src/backend/services/rpa/ocr_processor.py`
  - `src/backend/core/resilience/rpa_policy.py`
  - `src/backend/dsl/engine/processors/rpa/system.py`
  - `src/backend/dsl/engine/processors/rpa/operations/filewatchprocessor.py`

## Контекст

Ревью RPA (cycle 172, Wave 14) нашло восемь отказов, каждый из которых
приводит к «зависшему» или «мёртвому» ресурсу:

1. **Финализаторы Exchange не выполнялись движком.** `Exchange.add_finalizer`
   существовал, но `ExecutionEngine.execute/execute_parallel` никогда не
   вызывали `run_finalizers()`. Browser/desktop-контексты не возвращались в
   пул → семафор пула исчерпывался навсегда (проба: `sem 2→1→0`, третий
   `acquire` — TIMEOUT).
2. **Circuit Breaker пула desktop-RPA был мёртв.** `acquire()` вручную вызывал
   `breaker_guard.__aenter__()` / `__aexit__(None, None, None)` — исключение
   терялось, purgatory видел «успех», failure-counter сбрасывался. 7
   `ConnectError` подряд → breaker оставался `closed`.
3. **`ShellExecProcessor` не убивал потомка по таймауту.** `sleep 987654`
   продолжал жить после `exchange.fail(...)` (zombie-процессы RPA-агента).
4. **Whitelist shell-команд не был fail-closed.** `allowed_commands=None`
   означал «проверок нет», хотя docstring обещал «только команды из
   whitelist».
5. **`EmailReadProcessor` читал IMAP без socket-timeout и без внешнего
   `wait_for`** — поток executor'а висел навсегда.
6. **`RPACallPolicy` глотал `asyncio.CancelledError`** (`except BaseException`):
   отмена задачи превращалась в `RPACallExhausted` + ложную запись в DLQ.
7. **`FileWatchProcessor` (RPA) всегда ждал полный `timeout`** (файл @0.3s →
   возврат 5.01s), дублировал пути (create + modify) и падал необработанным
   `FileNotFoundError` на несуществующей папке.
8. **OCR без таймаута.** `pytesseract.image_to_string` вызывался без
   `timeout` и без внешнего `wait_for` — зависший tesseract блокировал вызов.

Решения владельца зафиксированы в
`artifacts/current_audit/RPA_REVIEW_DECISIONS_2026-10-28.md` (D2 — fail-closed
whitelist; D4 — `filewatchprocessor.py` и `ocr_processor.py` остаются и
чинятся). Этот ADR фиксирует техническую реализацию.

## Решение

1. **Финализаторы выполняются движком.** В `ExecutionEngine.execute` и
   `execute_parallel` тело маршрута обёрнуто в `try/finally` с вызовом
   `_run_finalizers(exchange)`:
   `await asyncio.wait_for(asyncio.shield(exchange.run_finalizers()),
   timeout=5.0)`. `shield` гарантирует, что отмена маршрута не прервёт
   освобождение ресурса; таймаут 5 с не даёт «зависшему» finalizer'у
   держать маршрут. Финализаторы выполняются и после падения процессора.
2. **Circuit Breaker пула — живой.** `acquire()` использует штатный
   `async with breaker.guard():` — исключение из тела проходит через
   purgatory и считается отказом; при `open` следующий `acquire` получает
   `CircuitOpen`. (Реестр breaker'ов — синглтон: в тестах обязателен сброс
   `get_breaker_registry()`.)
3. **`ShellExecProcessor` убивает потомка по таймауту** —
   `proc.kill(); await proc.wait()` (как в `TerminalExecProcessor`), затем
   `exchange.fail(...)`.
4. **Whitelist shell — fail-closed (решение D2).** Без `allowed_commands`
   команда не выполняется, exchange получает понятную ошибку. Проверка
   стоит **после** deadline-admission-блока, чтобы сохранить диагностику
   «deadline budget exhausted» (ADR-0305) и не сломать существующие тесты
   deadline-контроля.
5. **`EmailReadProcessor` ограничен по времени.** `IMAP4_SSL(host, port,
   timeout=...)` + `asyncio.wait_for(asyncio.to_thread(_fetch),
   timeout=...)`; по таймауту — `exchange.fail(...)`.
6. **`RPACallPolicy` не глотает отмену.** `except asyncio.CancelledError:
   raise` перед `except BaseException` — отмена проходит наверх, retry/DLQ
   не выполняются.
7. **`FileWatchProcessor` (RPA) — ранний выход + дедуп + ошибки.**
   `asyncio.Event` + `loop.call_soon_threadsafe` в хендлере watchdog'а,
   `await asyncio.wait_for(first_change.wait(), timeout=...)`, дедуп путей в
   `_ChangeCollector.add`, проверка существования каталога
   (`os.path.isdir` через `to_thread`) и `observer.start()` в
   `try/except OSError` → `exchange.fail(...)`. Файл не удаляется (D4).
8. **OCR ограничен по времени.** `pytesseract.image_to_string(..., timeout=)`
   + внешний `asyncio.wait_for`; по таймауту — пустая строка и warning.

## Альтернативы (отклонённые)

- **(а) Вызывать `run_finalizers()` без `shield`/таймаута** — отклонено:
  отмена задачи прервала бы cleanup, а «висящий» finalizer блокировал бы
  маршрут навсегда.
- **(б) Считать отказом только `httpx.ConnectError` вручную (без purgatory)** —
  отклонено: дублирование state-machine circuit breaker'а (ADR-0305).
- **(в) Fail-open для shell без whitelist** (как было) — отклонено: это
  прямое расхождение с docstring'ом и безопасностью (решение D2 владельца).
- **(г) Удалить `FileWatchProcessor`/`ocr_processor.py` как дубли** — отклонено
  владельцем (D4): watchdog-watch с ранним выходом полезен, OCR чинится
  таймаутом.
- **(д) Убивать IMAP/OCR-потоки принудительно** — отклонено: поток
  executor'а не прерывается (известный потолок `wait_for`).

## Последствия

- **Позитивные:** конечные ресурсы пула возвращаются; breaker desktop-RPA
  реально размыкает поток; RPA-процессы не остаются зомби; отмена задач
  больше не маскируется под «исчерпанные попытки»; watch/IMAP/OCR имеют
  конечное время ожидания.
- **Семантика DSL (осознанное изменение):** `.shell(...)` без
  `allowed_commands` перестаёт выполнять команду и возвращает ошибку
  «whitelist is not configured (fail-closed)». Прод-роутов с `.shell(...)` в
  репозитории нет (grep), потребителям DSL нужно явно задать whitelist.
- **Потолок:** `asyncio.wait_for(asyncio.to_thread(...))` не прерывает поток
  executor'а. Для IMAP ограничение обеспечивает socket-timeout, для OCR —
  process-timeout tesseract'а; поток освобождается позже, но вызов больше не
  висит бесконечно. Устранение потолка — отдельная задача (переход на
  async-клиенты).
- **Совместимость:** публичные сигнатуры затронуты в двух местах —
  добавлен `timeout` в `EmailReadProcessor.__init__` и в
  `OCRProcessor.recognize` (keyword-only, с дефолтом 30 с); оба параметра
  опциональны.

## Проверка

- `pytest tests/unit/dsl/engine/test_execution_engine_finalizers.py
  tests/unit/services/rpa/test_desktop_session_pool_breaker.py
  tests/unit/dsl/engine/processors/rpa/test_system_fault_tolerance.py
  tests/unit/core/resilience/test_rpa_policy_cancellation.py
  tests/unit/dsl/engine/processors/rpa/operations/test_filewatch_fault_tolerance.py
  tests/unit/services/rpa/test_ocr_processor_timeout.py` — 18 passed.
- `ruff check` по изменённым файлам — 0 ошибок.
- `tools/check_layers.py --strict` — 41 (baseline, новых нарушений нет).
- `tools/check_docstrings.py src --max-allowed 0` — 0 missing.
- `tools/config_audit.py --scope orphans` — 0 (новых конфиг-ключей нет).

## Связи с другими ADR

- ADR-0305 — narrow-timeout + admission-control в RPA-процессорах; этот ADR
  сохраняет порядок «admission → whitelist».
- ADR-0354 — DSL не импортирует `services.*` напрямую: правки ограничены
  processor'ами и engine'ом, связь с пулом остаётся через DI.
- ADR-0361 / ADR-0366 — семантика capability-гейта RPA (отдельный кластер).
- ADR-0369 — достижимость RPA-шагов из YAML; whitelist shell — часть
  публичной поверхности `.shell(...)`.
