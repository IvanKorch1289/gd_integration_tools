# ADR-0387 — Деградация пула при старте и удаление мёртвого `QueryResultCache`

* Статус: Accepted (2026-10-29, wave 17, кластер T2 — «INITIALIZE_ASYNC_POOL + МЁРТВЫЙ QueryResultCache»)
* Cycle: 177
* Дата: 2026-10-29
- **Затрагивает**:
  - `src/backend/infrastructure/database/database/initializer.py`
  - `src/backend/core/security/restricted_unpickler.py` (только текст docstring)
  - удалён `src/backend/infrastructure/database/query_result_cache.py`
  - удалены `tests/unit/infrastructure/database/test_query_result_cache_tenant.py`,
    `tests/unit/infrastructure/test_query_result_cache.py`
  - добавлен `tests/unit/infrastructure/database/test_initializer_async_pool_degradation.py`
- **Связан с**:
  - ADR-0100 (прецедент удаления мёртвого кода)
  - ADR-0383 (tenant-изоляция raw SQL; дефект 5 оттуда закрыт здесь)
  - ADR-0379 (честный статус вместо «зелёного»: недоступность БД не скрывается)
  - ADR-0284 (межслойные зависимости — новых нет)

## Контекст

Волна 17 закрыла кластер из трёх находок по контуру БД:

1. **`initialize_async_pool` ронял старт невнятным трейсбеком.** Метод
   ловил только `OSError`/`TimeoutError`. SQLAlchemy `OperationalError`
   (БД недоступна, отказ старта Postgres, таймаут соединения) проходил
   мимо обработчика и вылетал из `ExternalDatabaseRegistry.initialize_all_pools`
   невнятным трейсбеком вместо внятной деградации.
2. **Мёртвый `QueryResultCache`** (369 LOC): потребителей в `src/` нет —
   ни в `entrypoints/`, ни в `services/`, ни в `dsl/`, ни в реестрах
   плагинов. Единственные упоминания — собственный тест и текст docstring
   в `core/security/restricted_unpickler.py`.
3. **Docstring `restricted_unpickler.py:7`** ссылался на удаляемый модуль.

Дефект 1 был зафиксирован ещё в ADR-0383 («Вне зоны»: минимальный фикс —
добавить `OperationalError`/`SQLAlchemyError` в перехватываемые исключения).

## Решение

1. **Graceful-degradation прогрева пула.** `initialize_async_pool` ловит
   `(OSError, TimeoutError, SQLAlchemyError)`: недоступность БД больше не
   роняет старт. Поведение выровнено с соседним sync-путём (движок →
   `None` + warning, старт продолжается): ошибка логируется на уровне
   `warning` с явным текстом «старт продолжается degraded», пул остаётся
   «холодным» и прогревается лениво при первом запросе. Текст исключения
   и traceback проходят через `sanitize_db_error_text` /
   `sanitized_exc_info` (`infrastructure/database/listeners.py`) — значения
   bind-параметров не утекают в лог (консистентно с ADR-0383).
2. **Ошибка закрытия соединения не пробивает деградацию.** В `finally`
   `await conn.close()` обёрнут в обработчик `(RuntimeError, OSError,
   SQLAlchemyError)`: битое соединение не должно превращать деградацию в
   падение на `finally`.
3. **Удалён мёртвый `QueryResultCache`** (прецедент ADR-0100): модуль
   `src/backend/infrastructure/database/query_result_cache.py`, его тест
   `tests/unit/infrastructure/database/test_query_result_cache_tenant.py`
   и тест `tests/unit/infrastructure/test_query_result_cache.py` удалены.
   Публичный контракт не сломан: модуль не реэкспортировался ни в одном
   `__init__.py`, не был в canonical module map, не использовался в DSL и
   не входил в plugin-registry. Кеширование результатов БД **не
   используется** и остаётся на уровне `services/cache`
   (`UnifiedCacheFacade`) — это единственный канонический путь к кэшу.
4. **Поправлен docstring** `core/security/restricted_unpickler.py`: ссылка
   на удаляемый модуль заменена на описание правила (`# nosec B301` +
   явный комментарий о доверии к источнику).

## Альтернативы (отклонённые)

1. **Оставить `QueryResultCache` «на будущее» / пометить deprecated.**
   Отклонено: мёртвый код с pickle-сериализацией и RCE-историей (ADR-0383,
   cycle 34) — постоянный источник риска и ложных «зелёных» тестов;
   прецедент ADR-0100 — удалять с обоснованием.
2. **Ловить только `OperationalError`.** Отклонено: SQLAlchemy оборачивает
   ошибки драйвера в иерархию `SQLAlchemyError` (`InterfaceError`,
   `DBAPIError`, `sqlalchemy.exc.TimeoutError`); узкий перехват оставлял бы
   дыры. `SQLAlchemyError` не покрывает программные ошибки (AttributeError
   и т. п.) — они по-прежнему поднимаются.
3. **Fail-fast: не деградировать, а ронять старт.** Отклонено: контракт
   соседнего sync-пула — graceful-degradation; недоступность БД в момент
   старта не должна превращать деградацию в «невнятный трейсбек».
4. **Удалить и `core/security/restricted_unpickler.py`.** Отклонено: модуль
   публичен (`core.security.__init__` реэкспортирует `safe_loads` /
   `RestrictedUnpickler`), покрыт тестами и включается фича-флагом
   `restricted_unpickler_enabled` — это не мёртвый код.

## Последствия

* **Позитивные:** старт приложения не падает при недоступной БД — оператор
  видит внятный warning вместо трейсбека; логи прогрева пула не содержат
  PII; в репозитории на 369 LOC меньше кода с pickle-историей; ADR-0383
  (дефект 5) закрыт.
* **Негативные:** при недоступной БД пул остаётся холодным — первый
  реальный запрос платит cold-start latency; кеширование результатов
  SQL-запросов в проекте отсутствует (если понадобится — реализовывать
  поверх `services/cache` / `UnifiedCacheFacade`, а не новым модулем в
  `infrastructure/database`).
* **Вне зоны (чужие файлы):**
  - `tests/unit/infrastructure/test_query_result_cache.py` — тест удаляемого
    модуля лежит вне `tests/unit/infrastructure/database/**`; оставлен он
    был бы сломан (import-error на коллекции), поэтому удалён вместе с
    модулем.
  - `docs/adr/0383-tenant-isolation-raw-sql-and-error-sanitization.md` —
    исторический ADR (упоминает удалённый модуль и его тест); не
    переписывается, связь зафиксирована здесь.
  - `docs/adr/INDEX.md` — индекс ADR обновляется генератором
    (`tools/build_adr_index.py`), в этой задаче не редактировался.

## Проверка

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/database -q -p no:randomly
.venv/bin/python -m pytest tests/unit/core/security -q -p no:randomly
.venv/bin/python -m ruff check src/backend/infrastructure/database/database/initializer.py \
    src/backend/core/security/restricted_unpickler.py \
    tests/unit/infrastructure/database/test_initializer_async_pool_degradation.py
.venv/bin/python tools/config_audit.py --scope orphans
.venv/bin/python tools/check_layers.py --strict
.venv/bin/python tools/check_docstrings.py src --max-allowed 0
```

## Связи с другими ADR

* **ADR-0100** — прецедент удаления мёртвого кода (проверка «нет
  потребителей» + удаление вместе с тестом).
* **ADR-0383** — дефект 5 («OperationalError мимо `initialize_async_pool»»)
  закрыт в этом ADR; там же введён tenant-aware ключ кэша, который вместе
  с модулем удалён.
* **ADR-0379** — принцип «честный статус вместо зелёного»: недоступность БД
  не скрывается — она логируется явно и не роняет старт.
* **ADR-0284** — новых межслойных импортов не добавлено (`sqlalchemy.exc`
  — внешняя зависимость; `listeners.py` — тот же слой `infrastructure`).
