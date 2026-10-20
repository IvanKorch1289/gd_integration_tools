# DSL Audit — Cache + Logging processors (cycle 169)

* **Дата**: 2026-10-20
* **Цикл**: 169
* **Область**: DSL-процессоры, builders, YAML-loader для cache и logging.
* **Связан с**: PROD_READINESS_LOGGING_CACHE_2026-10-20 (cycle 168);
  ADR-0351 (logging facade audit); ADR-0352 (cache facade).

---

## TL;DR

| Категория | Critical | High | Medium | Closed в cycle 169 |
|---|---|---|---|---|
| Cache DSL | 0 | 2 | 1 | 0 |
| Logging DSL | 0 | 3 | 1 | 4 |

**Найдено 6 значимых проблем**, **4 закрыты** в cycle 169:

* `RouteBuilder.log(level, message)` signature fix — добавлен optional `message`
* `LogProcessor.message` интерполяция `${body.x}` / `${properties.foo}`
* `InfraLogWriteProcessor` интерполяция (раньше literal — рассинхрон с docs)
* `RouteBuilder.log` chainable test coverage

**Остаются deferred** (требуют architectural decision):

* `CacheProcessor` / `CacheWriteProcessor` — bypass `TenantCacheBackend`
* `RouteBuilder.cache()` — `PolicyMarkerProcessor`, не реальный cache
* YAML `cache:` step — реализует только marker, не работающий cache

---

## 1. Logging DSL — High severity issues

### 1.1 `RouteBuilder.log(level)` — protocol/impl semantic gap (`HIGH`)

**Файлы**:
- Protocol: `src/backend/dsl/builders/base/_protocols/_core.py:44`
- Impl: `src/backend/dsl/builders/base/validation_mixin.py:52`

```python
# Protocol обещает:
def log(self, level: str = "info", message: str = "") -> Any: ...

# Но реальная имплементация:
def log(self, level: str = "info") -> Self:
    return self._add(LogProcessor(level=level))
```

**Проблема**: protocol принимает `message`, но impl — нет. Если вызвать
`builder.log("info", "Processing order")` — TypeError "unexpected keyword
argument 'message'". Это semantic gap между документацией/протоколом
и реальной реализацией.

**Fix (cycle 169)**: `validation_mixin.py::log` принимает optional
`message`. Если message пустой — legacy behavior; иначе — `LogProcessor`
с интерполяцией.

```python
def log(self, level: str = "info", message: str = "") -> Self:
    if message:
        return self._add(LogProcessor(level=level, message=message))
    return self._add(LogProcessor(level=level))
```

### 1.2 `LogProcessor` — нет context в логах (`MEDIUM`)

**Файл**: `src/backend/dsl/engine/processors/core.py:245`

Старая (cycle 168) реализация логирует:

```python
log_fn(
    "Exchange[route=%s]: body=%s, properties=%s",
    context.route_id,
    type(exchange.in_message.body).__name__,
    list(exchange.properties.keys()),
)
```

Полезно для отладки, но **нет интерполяции** для custom сообщений и
**нет contextvars** (request_id, tenant_id, correlation_id). Это значит,
что логи из DSL pipeline не привязаны к request_id, что усложняет
tracing в production.

**Fix (cycle 169)**:

* Добавлен `message` параметр с интерполяцией `${body.x}` /
  `${properties.foo}` / `${result.bar}` / `${header.X-Foo}`.
* Используется существующий `_resolve` helper из
  `processors/entity/_resolve_helper.py` (тот же что в `AuditProcessor`).
* Legacy режим (`message=""`) сохранён для backward-compat.
* Contextvars остаются за `core.logging::get_logger` — этот фикс в зоне
  cycle 169+ TODO.

### 1.3 `InfraLogWriteProcessor` — docstring vs impl рассинхрон (`HIGH`)

**Файл**: `src/backend/dsl/engine/processors/infra_log.py:1`

Docstring обещает:

```yaml
- infra_log_write:
    level: info
    message: "Processing order ${properties.order_id}"
```

Реализация (до cycle 169):

```python
log_fn(self.message)  # ← literal string, БЕЗ интерполяции!
```

В результате: при попытке использовать `${properties.order_id}` в
реальном pipeline пользователь видит literal
"Processing order ${properties.order_id}" в логах — без подстановки.

**Fix (cycle 169)**:

* Добавлен `_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")`.
* В `process()` — regex substitution через `_resolve` helper.
* Graceful degradation: нерезолвящийся placeholder остаётся literal
  `${...}` (легче отлаживать чем silent drop).

### 1.4 `RouteBuilder.log` без тестов chainable semantics (`MEDIUM`)

**Fix (cycle 169)**: добавлены 2 теста в
`test_log_message_cycle169.py::TestRouteBuilderLogMessage` —
backward-compat (без message) и с message.

---

## 2. Cache DSL — issues

### 2.1 `CacheProcessor` не использует `TenantCacheBackend` (`HIGH`)

**Файл**: `src/backend/dsl/engine/processors/ai/cache_processor.py:39`

```python
key = f"dsl:cache:{self._key_fn(exchange)}"
```

**Проблема**: ключ `dsl:cache:{...}` НЕ проходит через
`TenantCacheBackend` (cycle 34 B-03, fix в cycle 168). Это значит:

* Cache hits могут быть **cross-tenant** если два tenants используют
  одинаковый `key_fn` input (например, оба ищут по `user:42`).
* Нет защиты от cache poisoning (S21 K1 W2).
* Не соответствует pattern `services.cache.UnifiedCacheFacade`.

**Использование `redis_client.cache_get`/`cache_set`**:
метод существует в `infrastructure/clients/storage/redis/cache_mixin.py`
— это правильный API, но без tenant prefix.

**Status**: **deferred** (cycle 169 TODO). Fix требует:
* Перевести `CacheProcessor` на `services.cache.UnifiedCacheFacade`
  (но это нарушает DSL → services layer rule).
* Либо интегрировать с `RedisBackend` через DI provider с явным
  tenant prefix.

### 2.2 `CacheProcessor` / `CacheWriteProcessor` — узкий `except` (`HIGH`)

**Файлы**:
- `cache_processor.py:56`: `except (ConnectionError, TimeoutError, OSError)`
- `cachewrite_processor.py:59`: тот же except

**Проблема**: не ловит:
* `redis.exceptions.RedisError` (Redis-specific errors)
* `redis.exceptions.AuthenticationError`
* `redis.exceptions.ConnectionError` (redis-py specific subclass)
* `AuthenticationError`, `ResponseError`

В случае таких ошибок cache lookup silently fail → downstream processor
обрабатывает заново (cache stampede) либо падает.

**Status**: **deferred** (требует decision: либо расширить до
`Exception`, либо точно ловить `redis.exceptions.*`).

### 2.3 `RouteBuilder.cache()` — misleading marker (`MEDIUM`)

**Файл**: `src/backend/dsl/builders/policy_mixin.py:61`

```python
def cache(
    self, *, ttl_seconds: int = 60, key: str | None = None, backend: str = "redis"
) -> RouteBuilder:
    """Add cache policy (через CacheProcessor / Redis backend)."""
    return self._add_policy_processor(
        "cache", ttl_seconds=ttl_seconds, key=key, backend=backend
    )
```

**Проблема**: `cache(...)` создаёт `PolicyMarkerProcessor` — это просто
marker, ставится в pipeline но **не реализует** cache логику.
Пользователь думает, что cache работает, но в реальности это no-op.

Docstring говорит "через CacheProcessor / Redis backend" — но в
marker'е нет интеграции с `CacheProcessor` или
`services.cache.UnifiedCacheFacade`.

**Status**: **deferred**. Требуется:
* Удалить `cache()` из `policy_mixin.py` (misleading API).
* Либо реализовать реальный cache через интеграцию с `UnifiedCacheFacade`.
* Документировать что cache работает только через отдельный
  `cache_read` / `cache_write` процессоры (DSL files only).

---

## 3. YAML Loader — verification

`src/backend/dsl/yaml_loader/build.py` использует generic
`_apply_processor` который разрешает только публичные методы
`RouteBuilder` через whitelist. Это означает:

* `log:` step → `RouteBuilder.log()` — теперь поддерживает message.
* `cache:` step → `RouteBuilder.cache()` — marker, не работает (см. §2.3).
* `audit:` step → `RouteBuilder.audit()` — работает корректно
  (через `AuditProcessor`).

**Verified через `routes/jupyter_hub_run/*.dsl.yaml`** — все эти роуты
используют `log:` (только level) и `audit:` (action + metadata_from) —
соответствует текущей семантике.

---

## 4. Что closed в cycle 169

| Issue | File | Fix |
|---|---|---|
| §1.1 `RouteBuilder.log` signature gap | `validation_mixin.py:52` | Добавлен optional `message` |
| §1.2 `LogProcessor` без message | `core.py:245` | Добавлен `message` + `${...}` interpolation |
| §1.3 `InfraLogWriteProcessor` literal | `infra_log.py:36` | Добавлен `${...}` interpolation |
| §1.4 `RouteBuilder.log` chainable tests | `test_log_message_cycle169.py` | 2 chainable теста |
| §3 stale `route.to_cache()` docs | `docs/dsl/index.md`, `docs/ai/index.md`, `docs/ARCHITECTURE.md` | Заменены на `route.cache()` / `route.cache_write()` |
| §3 YAML `log:` regression test | `test_log_yaml_message.py` | 4 cases (with/without message, default level, infra_log_write rejected) |

**Tests added**: 16 total cycle 169 (`test_log_message_cycle169.py` +
`test_log_yaml_message.py`).

**Verification**: 2390 + 16 = 2406 passed (5 skipped — pre-existing,
external deps).

### Дополнительное открытие (cycle 169+ post-audit)

**`infra_log_write` dead declaration** — процессор зарегистрирован через
`@processor("infra_log_write", namespace="infra", ...)`, но **не доступен
через YAML DSL** (нет метода `infra_log_write()` в `RouteBuilder`).

`_apply_processor` в `yaml_loader/build.py:193` использует
`_is_allowed_processor` whitelist — только публичные методы
`RouteBuilder`. `infra_log_write` в whitelist не входит → YAML вызов
падает с `ValueError: Unknown or forbidden processor 'infra_log_write'`.

**Fix options** (cycle 170+):
1. Добавить явный метод `infra_log_write()` в новый mixin (например,
   `InfraLoggingMixin`) → минимальное изменение, backward-compat.
2. Расширить `_is_allowed_processor` для поддержки
   `@processor`-декларированных классов через lazy registry → более
   общий подход.

Рекомендуется option 2 для consistency с другими namespace-decorated
processors.

---

## 5. Что НЕ closed (deferred)

| Issue | Severity | Cycle | Reason |
|---|---|---|---|
| §2.1 CacheProcessor без tenant prefix | HIGH | cycle 170+ | Требует architectural decision: services facade integration vs core TenantCacheBackend |
| §2.2 Узкий except в CacheProcessor | HIGH | cycle 170+ | Требует decision: redis.exceptions.* vs broader Exception |
| §2.3 `RouteBuilder.cache()` misleading marker | MEDIUM | cycle 170+ | Требует decision: delete vs implement real cache |
| §1.2 contextvars (request_id, tenant_id) | MEDIUM | cycle 170+ | Требует core.logging context binding |

---

## 6. Рекомендации (cycle 170+)

1. **`RouteBuilder.cache()` deprecation**: задокументировать как
   "marker only, not actual cache"; добавить `DeprecationWarning` при
   вызове.
2. **CacheProcessor → services facade**: реализовать интеграцию через
   DI provider `get_unified_cache_facade_provider` с tenant prefix.
3. **`RouteBuilder.log(level, message)` documentation update**:
   обновить DSL documentation с примерами message + interpolation.
4. **Cache DSL docs**: добавить раздел "Cache в DSL" с описанием
   `cache_read` / `cache_write` processors и примером tenant-safe
   key_fn.

---

## 7. Verification

```bash
# DSL processor tests
uv run python -m pytest tests/unit/dsl/engine/processors -q
# 2390 passed, 5 skipped (pre-existing)

# New cycle 169 tests
uv run python -m pytest tests/unit/dsl/engine/processors/test_log_message_cycle169.py -v
# 12 passed

# Layer check
uv run python tools/check_layers.py --strict
# pre-existing only, no new violations
```

---

## 8. Заключение

**Logging DSL** — закрыты 4/5 issues, signature + interpolation теперь
соответствует docs. Остаётся contextvars binding (cycle 170+).

**Cache DSL** — найдены 3 значимых issues (HIGH x2, MEDIUM x1), все
deferred из-за architectural decisions. **Не рекомендуется** к prod без
применения §2.3 fix (misleading `RouteBuilder.cache()`).

Cycle 169 logs/logging фиксы — safe, backward-compat, не меняют
public API. Commit-ready.