---
name: python-dev
description: Правила Python-разработки для gd_integration_tools (Python 3.14+, async-first, capability-checked фасады, 80% декларативно)
type: prompt
whenToUse: Пишу или модифицирую Python-код в gd_integration_tools
---

# Python-разработка в gd_integration_tools

Применяй эти правила при любой правке Python-кода. Если правило противоречит
запросу пользователя — спроси, не выдумывай обходной путь.

## Версия и синтаксис

- Python **3.14+** (используй `int | str`, generic `class Foo[T]`, не `Union`,
  не `List`/`Dict`/`Optional` из `typing`);
- Pydantic **v2** (`BaseModel`, `ConfigDict`, `Field`, `field_validator`);
- f-string только с `=` для отладки (`f"{x=}"`).

## Async и I/O

- `async/await` по умолчанию (FastAPI, Temporal, ASGI middlewares);
- **Никакого blocking I/O в async-контексте** (sync `requests`, `time.sleep`,
  `open()` в async-функции). Используй httpx/asyncpg/aiofiles;
- CPU-bound → `asyncio.to_thread()` или `ProcessPoolExecutor`;
- `await` ВСЕГДА с таймаутом (`asyncio.wait_for` / `asyncio.timeout`);
- Никогда `asyncio.gather` без `return_exceptions=True` для независимых задач.

## Архитектурные слои (ЖЁСТКО)

- `entrypoints/` импортирует: только `services/`, `schemas/`, `core/` (Protocols);
- `services/` импортирует: только `core/`, `schemas/`;
- `infrastructure/` реализует контракты из `core/` (Protocols);
- `core/` НЕ импортирует код из `src/` (только stdlib + Protocols);
- `dsl/` импортирует `core/` (контракты) + `infrastructure/` через registries;
- `extensions/<name>/` импортирует ТОЛЬКО:
  - `gd_integration_tools.core.*`
  - `gd_integration_tools.testkit.*`
  - capability-checked фасады
  - **Прямой импорт из `infrastructure/*` / `services/*` ЗАПРЕЩЁН**;
- `frontend/streamlit_app/` импортирует ТОЛЬКО публичный API + REST через
  `api_client.py`.

Проверка: `tools/checks/check_layers.py` (вызывается через `make lint-strict`).

## Бизнес-логика

- Только в `extensions/<name>/`. Каждый extension имеет `plugin.toml`
  (capabilities, requires_core, semver);
- Service DSL: `@service_dsl(crud=True)` + `services/<name>.service.toml`;
- Route DSL: `route.toml` + `*.dsl.yaml` (steps[] любых типов);
- 80% декларативно / 20% Python. Через `call_function('module:fn')` без обёрток
  в Action;
- Если добавляешь новый модуль — изучи существующий паттерн через `codebase-map`
  skill или `graphify query "module_name"`.

## Type hints и схемы

- Все сигнатуры функций и методов с type hints (включая `-> None`);
- DTO через Pydantic `BaseModel` (не dataclass для API/DTO);
- Внутренние структуры — `dataclass(frozen=True, slots=True)`;
- Enum — `StrEnum` (Python 3.11+);
- Никогда `Any` без обоснования; если используешь — комментарий `# type: ignore[arg-type]` с причиной.

## Capability-gate

- Cross-layer доступ ТОЛЬКО через capability-checked фасады;
- Перед добавлением нового импорта между слоями — спроси: "это идёт через
  фасад или напрямую?";
- Capability объявляется в `plugin.toml` (`[capabilities] requires = [...]`).

## Тесты

- `pytest` + `pytest-asyncio` + `pytest-cov`;
- Markers: `@pytest.mark.unit`, `.integration`, `.asyncio`, `.security`;
- Имя файла: `test_<module>.py` рядом с модулем ИЛИ в `tests/`;
- Имя функции: `test_<unit>_<scenario>_<expected>` (snake_case, явный);
- Fixtures — в `conftest.py` ближайшего уровня;
- Mock через `unittest.mock` / `pytest-mock`, не monkeypatching руками;
- Integration тесты — с docker-compose (`tests/integration/conftest.py`);
- Property-based — `hypothesis` (есть в Sprint 35).

## Качество перед коммитом

```bash
make format         # ruff format
make lint           # ruff check
make type-check     # mypy strict
make vulture-check  # dead code
make refurb-check   # pyupgrade-style
make secrets-check  # detect-secrets
make test           # pytest
```

Если `make lint-strict` ругается — не обходи, исправь. Если не можешь —
отметь в commit message.

## Секреты и безопасность

- НИКОГДА `.env`, `.env.*`, `*.pem`, `*.key`, `*secret*`, `*token*` в коде
  или коммитах (запрещено permission rules);
- Секреты — через Vault (`src/infrastructure/secrets/`);
- `detect-secrets` в CI;
- PII в логах запрещена — `make secrets-check` ловит;
- Все API-ключи/Telegram-токены/пароли БД — через переменные окружения
  или Vault, не в коде.

## Commit

- Короткий, Russian-first, без emoji;
- Conventional prefix: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`,
  `build:`, `ci:`, `perf:`;
- Пример: `feat(routes): добавил step типа db_call_procedure`;
- Атомарный: одна логическая правка = один коммит;
- Перед коммитом — `make format && make lint && make test`.

## План работы

1. Изучи существующий паттерн (`codebase-map` skill, `graphify query`).
2. Составь план: новые файлы + изменяемые + зависимости. **СТОП — покажи план,
   жди подтверждения.**
3. Реализуй по одному файлу, после каждого `make lint`.
4. Покрой тестами.
5. `make test && make lint-strict && graphify update .`.
6. Коммит.

## Анти-паттерны (ЗАПРЕЩЕНО)

- `from infrastructure.x import *`;
- `print(...)` для отладки (используй `structlog` / `logger`);
- `except Exception` без логирования и re-raise;
- `asyncio.run()` внутри async-кода;
- `type: ignore` без комментария с причиной;
- Глобальные mutable state;
- Magic numbers (выноси в `settings.py` / env);
- Mixin-ы без явной композиции;
- Protocol-сигнатуры, дублирующие concrete mixin: Protocol-методы пишем как
  позиционные-only аргументы (без `*` / дефолтов) или через `# type: ignore[misc]`
  при несовместимости;
- Protocol-атрибуты (`_cache`, `_tenant_cache` и т.п.) не решают ``has-type``
  само по себе — присваивайте в ``__init__`` конкретного хоста и используйте
  локальные аннотации внутри mixin;
- `# noqa` без обоснования в комментарии.
