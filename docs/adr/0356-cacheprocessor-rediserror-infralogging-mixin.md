# ADR-0356: CacheProcessor RedisError handling + InfraLoggingMixin (cycle 170)

* **Статус**: ACCEPTED (2026-10-20, cycle 170, пользователь Mavis)
* **Cycle**: 170
* **Связан с**:
  - `DSL_AUDIT_CACHE_LOGGING_2026-10-20.md` §2.2 + §4
  - ADR-0354 (cache processor cleanup)
* **Затрагивает**:
  - `src/backend/dsl/engine/processors/ai/cache_processor.py`
  - `src/backend/dsl/engine/processors/ai/cachewrite_processor.py`
  - `src/backend/dsl/builders/infra_logging_mixin.py` (new)
  - `src/backend/dsl/builders/base.py` (mixin registration)

## Контекст

Cycle 169 audit обнаружил два связанных issue в DSL processors.

### §2.2: `CacheProcessor` узкий `except`

```python
# src/backend/dsl/engine/processors/ai/cache_processor.py:56
except (ConnectionError, TimeoutError, OSError):
    pass
```

Не ловит `redis.exceptions.*`:

- `redis.exceptions.ConnectionError` (Redis-specific subclass,
  наследует `redis.exceptions.RedisError`).
- `redis.exceptions.TimeoutError`.
- `redis.exceptions.AuthenticationError`.
- `redis.exceptions.ResponseError`.
- `redis.exceptions.RedisError` (parent class).

В случае таких ошибок cache lookup silently fail → downstream
processor обрабатывает заново (cache stampede risk).

### §4: `infra_log_write` dead declaration

```python
# src/backend/dsl/engine/processors/infra_log.py:22
@processor(
    "infra_log_write",
    namespace="infra",
    spec_schema={...},
    capabilities=("log.write",),
    meta={"tier": 1, "category": "infra"},
)
class InfraLogWriteProcessor(BaseProcessor):
    ...
```

Задекларирован через `@processor(namespace="infra")`, но **не
интегрирован** с `RouteBuilder`. YAML DSL whitelist (через
`_is_allowed_processor`) не находит метод `infra_log_write()` в
`RouteBuilder` → YAML вызов падает с `ValueError: Unknown or forbidden
processor 'infra_log_write'`.

Это dead declaration — процессор зарегистрирован в registry, но
недоступен пользователю.

## Решение

### §2.2 fix: расширить except до `redis.exceptions.RedisError`

```python
# cache_processor.py
import redis.exceptions

try:
    redis_client = get_redis_client_provider()
    cached = await redis_client.cache_get(key)
    if cached is not None:
        # ...
except redis.exceptions.RedisError:
    # Cache miss — log debug, continue.
    pass
```

**Почему `RedisError`**: parent class для всех redis-py exceptions.
Один import, точное покрытие, не over-catch.

### §4 fix: добавить `InfraLoggingMixin`

Создать `src/backend/dsl/builders/infra_logging_mixin.py`:

```python
class InfraLoggingMixin:
    def infra_log_write(self, level: str, message: str) -> "Self":
        """DSL processor для структурированного логирования."""
        return self._add(
            InfraLogWriteProcessor(level=level, message=message)
        )
```

Подмешать в `RouteBuilder` через MRO. После этого YAML
`infra_log_write: {level, message}` будет корректно разрешаться через
`RouteBuilder.infra_log_write()`.

### Backward-compat

`InfraLogWriteProcessor` API не меняется — добавление mixin это
**только addition**, без breaking changes.

## Альтернативы

### §2.2 alternatives

**Option B: catch `Exception`** (rejected per CLAUDE.md anti-pattern).

**Option C: catch bare `RedisError` + логировать на WARNING**
(rejected — silent fall-through не нужен; cache lookup failure
достаточно серьёзен чтобы логировать на WARNING).

**Rejected** в пользу Option A (точное покрытие redis-py errors).

### §4 alternatives

**Option B: расширить `_is_allowed_processor` для lazy registry**
(rejected для cycle 170 — generic fix требует больше работы и
может сломать существующие тесты).

**Rejected** в пользу Option A (явный mixin — минимальное изменение).

**Примечание**: Option B может быть рассмотрен в будущем как
generic fix для всех namespace-decorated processors.

## Последствия

### Позитивные

- Cache lookup failures больше не silent на redis-specific exceptions.
- `infra_log_write` теперь доступен через YAML DSL — dead declaration
  устранён.
- Тесты для обоих processors могут покрыть negative paths.

### Негативные

- Дополнительный import `redis.exceptions` в cache processors.
- Новый mixin файл (один файл, ~30 LOC).

## Проверка после реализации

```bash
# 1. Cache processor negative test
uv run pytest tests/unit/dsl/engine/processors/test_cache_processor.py -v

# 2. infra_log_write integration test
uv run pytest tests/unit/dsl/yaml_loader/test_log_yaml_message.py -v

# 3. Layer check
uv run python tools/check_layers.py --strict

# 4. Существующие cache tests passing
uv run pytest tests/unit/infrastructure/cache tests/unit/services/cache -q
```

## Статус реализации

**Cycle 170** (этот ADR). Реализация + тесты + коммит.