# ADR-0353: Удаление `src/backend/core/rate_limiter/` (cycle 170)

* **Статус**: ACCEPTED (2026-10-20, cycle 170, пользователь Mavis)
* **Supersedes**: ADR-0350 (Draft, содержал устаревшее утверждение про
  cache_keys; см. Amendment 2026-10-16). Этот ADR **финализирует** решение
  ADR-0350 и заменяет его.
* **Затрагивает**:
  - `src/backend/core/rate_limiter/` (245 LOC)
  - `src/backend/core/rate_limiter/DEPRECATED.md`
  - `tests/unit/core/rate_limiter/test_rate_limiter_focused.py`

## Контекст

`src/backend/core/rate_limiter/` реализует кастомный token-bucket:

```python
def acquire(self, cost: float = 1.0, *, timeout: float | None = None) -> bool:
    deadline = time.monotonic() + timeout if timeout is not None else None
    while True:
        if self.try_acquire(cost):
            return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(min(0.1, cost / max(self._config.refill_rate, 0.01)))
```

### Проблемы

1. **Мёртвый код.** Цикл 168 re-audit подтвердил (после Amendment
   2026-10-16 убралшего cache_keys misattribution):
   - 0 production callers вне `core/rate_limiter/`.
   - 1 focused test (`tests/unit/core/rate_limiter/test_rate_limiter_focused.py`).
   - Только self-imports в `__init__.py` и focused test.

2. **Анти-паттерн.** `time.sleep()` в `acquire()` блокирует event loop
   на время ожидания refill. CLAUDE.md явно перечисляет:
   «time.sleep() в async-контексте» как запрещённый паттерн.

3. **Заменён полностью.** Текущие production rate-limit решения:

   | Слой | Реализация | Свойства |
   |---|---|---|
   | `entrypoints/dependencies/rate_limit.py` | `SafeRateLimiter` + `RedisLimiterAdapter` | Redis-backed, multi-instance safe, `async try_acquire_async`, fail-open |
   | `infrastructure/resilience/unified_rate_limiter.py` | `RedisRateLimiter` | Per-resource limits, Redis, sliding window |

   `SafeRateLimiter` (коммит `b65fe0635`) дополнительно обходит upstream-баг
   `fastapi_limiter==0.2.0` (`AttributeError` на `_IncludedRouter.path`).

## Решение

**Удалить** `src/backend/core/rate_limiter/` полностью:
- `src/backend/core/rate_limiter/__init__.py` (re-export shim)
- `src/backend/core/rate_limiter/limiter.py` (реализация token-bucket)
- `src/backend/core/rate_limiter/DEPRECATED.md` (метаданные)
- `tests/unit/core/rate_limiter/test_rate_limiter_focused.py` (1 focused test)

**Объём**: 245 LOC удалено, 1 focused test удалён.

## Обоснование

1. **Доказанный нулевой импорт.** Статический grep подтвердил: 0 production
   callers вне удаляемого пакета. Динамический `importlib` не используется
   (grep `import_module|__import__` для rate_limiter — 0 результатов).
2. **Замена существует и production-ready.** `SafeRateLimiter` +
   `RedisRateLimiter` покрывают все use-cases.
3. **Устраняет анти-паттерн.** `time.sleep()` в потенциально-async пути
   исчезает из кодовой базы.
4. **Снижает cognitive load.** Новые разработчики не будут тратить время
   на изучение deprecated модуля, который легко пропустить
   (`DEPRECATED.md` — markdown, не runtime warning).

## Последствия

### Позитивные

- -245 LOC кодовой базы.
- Устранена ловушка для новых разработчиков (DEPRECATED.md легко
  пропустить).
- `time.sleep()` в потенциально-async коде исчезает.

### Негативные

- `DEPRECATED.md` удаляется вместе с пакетом. Любые ссылки в
  документации на этот файл нужно обновить. (Проверено: grep в `docs/`
  не находит ссылок на `DEPRECATED.md` из rate_limiter.)

## Миграция

Заменить нечего: активных потребителей нет. Для будущих изменений
использовать:

- per-route HTTP лимиты → `entrypoints/dependencies/rate_limit.py`
  (`get_default_rate_limiter()`)
- per-resource лимиты в resilience-коде →
  `infrastructure/resilience/unified_rate_limiter.py`
- generic retry → `tenacity` (R-V15-8)

## Проверка после удаления

```bash
# 1. Layer check
uv run python tools/check_layers.py

# 2. Import smoke (app_factory поднимает всю композицию)
uv run python -c "import src.backend.plugins.composition.app_factory"

# 3. Полный unit-прогон по resilience + entrypoints
uv run pytest tests/unit/services/resilience/ \
             tests/unit/entrypoints/dependencies/ -q

# 4. Grep — нет ссылок на rate_limiter
grep -rn "core\.rate_limiter\|src\.backend\.core\.rate_limiter" src/ tests/ docs/
# Expected: 0 результатов
```

## Статус реализации

**Cycle 170** (этот ADR). `git rm` + удаление focused test + коммит.