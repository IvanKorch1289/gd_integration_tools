# ADR-041: Унификация FS-watcher на `watchfiles`

- **Статус:** accepted
- **Дата:** 2026-05-04
- **Фаза:** Wave B (gap-closure)
- **Автор:** wave-b-coordinator

## Контекст

В проекте параллельно жили **три** механизма наблюдения за файловой системой:

1. `src/dsl/yaml_watcher.py` (`DSLYamlWatcher`) — watchdog `Observer` в
   отдельном threading-потоке + `loop.call_soon_threadsafe` + asyncio.Queue
   с собственной debounce-логикой; ~298 LOC.
2. `src/entrypoints/filewatcher/watcher_manager.py` (`WatcherManager`) —
   ручной `os.scandir` polling-цикл на `asyncio.sleep(poll_interval)`
   (~194 LOC).
3. `src/infrastructure/sources/file_watcher.py` (`FileWatcherSource`) —
   тонкая обёртка над `watchfiles.awatch` (~114 LOC), уже используется
   в DSL-source pipeline.

Последствия:

- Три кодовые базы для одной задачи → дрейф поведения (debounce-семантика
  не совпадала: watchdog-cyclus считал «window of silence», polling
  игнорировал любое окно, а awatch использует rust-`notify` с явным
  `debounce`-параметром).
- `watchdog` — единственный потребитель блокировки потока + cross-thread
  marshalling — даёт постоянный фон в profile/trace.
- Различная политика для FSEvents/inotify/PollObserver делает
  поведение CI/локального запуска расхождимым.

## Рассмотренные варианты

- **Вариант 1 — оставить как есть, исправить только баги.** Плюсы:
  ноль миграционного объёма. Минусы: продолжение технического долга,
  проседание перформанса от threading-моста, тройной maintenance.
- **Вариант 2 — мигрировать всё на `watchdog`.** Плюсы: knownness в
  Python-экосистеме. Минусы: блокирующий API, threading-мост обязателен,
  нет async-first интерфейса, всё ещё дублирующая инфраструктура.
- **Вариант 3 — мигрировать всё на `watchfiles.awatch`.** Плюсы:
  rust-based `notify`, async-нативный, единый debounce-параметр,
  минимальный code-footprint, уже в зависимостях, эталонная реализация
  в `FileWatcherSource`. Минусы: потеряны watchdog-специфичные
  callback-методы (нерелевантно для нашего use-case).

## Решение

Принят вариант 3. Переписываем `DSLYamlWatcher` и `WatcherManager`
поверх `watchfiles.awatch`. Public API обоих классов сохраняется
(включая `WatcherSpec.poll_interval` — теперь интерпретируется как
`debounce_ms = poll_interval * 1000`). Зависимость `watchdog`
удалена из `pyproject.toml` и `uv.lock`.

Дебаунс делегирован watchfiles (`debounce` параметр `awatch`) — больше
не дублируем «окно тишины» собственным asyncio.Queue.

## Последствия

- Положительные:
  - удалено ~150 LOC threading + queue + debounce-кода;
  - единая FS-семантика во всём проекте (rust-`notify`);
  - drop одной runtime-зависимости (`watchdog>=4.0,<5.0`);
  - watcher-tasks полностью async — нет блокирующих join'ов.
- Отрицательные:
  - watchfiles на macOS использует FSEvents, на Linux — inotify;
    специфические FSEvents-кейсы (rename-дубликаты) обрабатываются
    rust-слоем — поведение может слегка отличаться от watchdog
    `PollingObserver`. Митигация: smoke-тест `tests/smoke/test_yaml_hot_reload.py`
    + integration-тест `tests/integration/dsl/yaml_watcher/test_real_watchfiles.py`.
- Нейтральные:
  - `FileWatcherSource` остаётся образцом-обёрткой; теперь все три
    места используют один и тот же API `awatch(stop_event=, debounce=)`.

## Связанные ADR

- ADR-040 secrets-di — Wave A foundation (предшествует Wave B).
- ADR-031 durable workflows — будет superseded в Wave D (Temporal).
