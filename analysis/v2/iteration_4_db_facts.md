# V2 Итерация 4: БД — фактические находки

## alembic.ini
- `script_location = ./src/infrastructure/database/migrations` — нет сегмента `backend`
- Фактический путь: `src/backend/infrastructure/database/migrations/`
- Alembic при прямом запуске упадёт с ModuleNotFoundError

## pool_use_lifo
- `database.py:181-201` — `_engine_kwargs()` передаёт только: pool_size, max_overflow, pool_recycle, pool_timeout, pool_pre_ping
- `pool_use_lifo` объявлен в `DatabaseConnectionSettings` но **не прокидывается**

## UnitOfWork — отсутствует
- `repositories/base.py`: все методы с `@main_session_manager.connection()`
- `get()`, `count()`, `first_or_last()`, `add()`, `update()`, `delete()` — каждый открывает **свою сессию**
- **Критичный баг**: `update()` вызывает `self.get()` → detached object (разные сессии)

## CDC backends — scaffold
- `poll_backend.py`: `yield` защищён `if False:` — события не эмитятся
- `listen_notify_backend.py`: только `await self._stopped.wait()` — не подключается к БД
- Оба: docstring «Scaffold: пустой stream до Wave R3»

## ORM модели
- infrastructure/models: 14 ORM-классов
- extensions domain/models.py: 5 файлов, но только 3 оригинальные (credit_pipeline), остальные — re-export из infrastructure

## Nested transactions / savepoints
- `session_manager.py`: поиск `begin_nested`, `savepoint`, `NestedTransaction` — 0 совпадений
- `transaction()` — простой commit/rollback без вложенности

## Дополнительный факт
- `session_manager.py:124` — `async with self.session_maker() as session:` — нет `begin_nested`
