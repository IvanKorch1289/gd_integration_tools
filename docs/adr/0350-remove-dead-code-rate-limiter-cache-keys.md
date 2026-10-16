# ADR-0350 — Удаление мёртвого кода: `core/rate_limiter/` и `core/utils/cache_keys.py`

* Статус: Draft (на согласование владельца)
* Дата: 2026-10-15
* Затрагивает: `src/backend/core/rate_limiter/` (245 LOC), `src/backend/core/utils/cache_keys.py` (48 LOC)
* Связан с: CLAUDE.md §«Безопасность» (запрет удаления без подтверждения),
  R-V15-8 (tenacity unification), `docs/roadmap/INTEGRATION_RPA_OPTIMIZATION_2026-10-15.md`

## Контекст

Re-audit 2026-10-15 обнаружил два модуля без единого импортера за пределами
собственного пакета. Ниже — доказательная база, а не предположение.

### `core/rate_limiter/` — 245 LOC

Модуль реализует кастомный token-bucket:

```python
# src/backend/core/rate_limiter/limiter.py:82-91
def acquire(self, cost: float = 1.0, *, timeout: float | None = None) -> bool:
    deadline = time.monotonic() + timeout if timeout is not None else None
    while True:
        if self.try_acquire(cost):
            return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(min(0.1, cost / max(self._config.refill_rate, 0.01)))
```

Две проблемы:

1. **Мёртвый код.** Проверка:
   ```bash
   grep -rn "from src.backend.core.rate_limiter\|core\.rate_limiter" \
       src/ tests/ --include="*.py" | grep -v "core/rate_limiter/"
   ```
   → 0 результатов.

2. **Блокирующий sync-код в async-контексте.** `acquire()` использует
   `time.sleep()` — в event loop это блокирует весь loop на время ожидания
   refill. CLAUDE.md в «Запрещённые паттерны» явно перечисляет
   `time.sleep() в async-контексте`.

Модуль **уже помечен** как deprecated — `src/backend/core/rate_limiter/DEPRECATED.md`
содержит «Pending: approval for git rm».

### Что используется вместо него

| Слой | Реализация | Свойства |
|---|---|---|
| `entrypoints/dependencies/rate_limit.py` | `SafeRateLimiter` + `RedisLimiterAdapter` | Redis-backed, multi-instance safe, `async try_acquire_async`, fail-open |
| `infrastructure/resilience/unified_rate_limiter.py` | `RedisRateLimiter` | Per-resource limits, Redis, sliding window |

`SafeRateLimiter` (коммит `b65fe0635`) дополнительно обходит upstream-баг
`fastapi_limiter==0.2.0` (`AttributeError` на `_IncludedRouter.path`).

### `core/utils/cache_keys.py` — 48 LOC

> **Amendment 2026-10-16.** Re-проверка при подготовке к accept обнаружила,
> что ADR-0350 содержит **ошибочное утверждение** про cache_keys. Ниже —
> исправленная доказательная база.

Хелпер `build_cache_key` для детерминированных cache-ключей через SHA256.
Используется минимум в двух местах:

```bash
$ grep -rn "from src.backend.core.utils.cache_keys" src/ tests/ --include="*.py"
src/backend/infrastructure/decorators/caching/decorator.py:17:from src.backend.core.utils.cache_keys import build_cache_key
src/backend/core/resilience/cache_decorators.py:36:from src.backend.core.utils.cache_keys import build_cache_key
src/backend/core/utils/__init__.py:21:from src.backend.core.utils.cache_keys import build_cache_key
tests/unit/core/utils/test_cache_keys.py:7:from src.backend.core.utils.cache_keys import build_cache_key
```

4 совпадения: 3 production (`caching/decorator.py:127`,
`cache_decorators.py:224`, `utils/__init__.py:21` re-export) и 1 test.
**Это НЕ мёртвый код.** ADR-0350 v1 (2026-10-15) ошибся в подсчёте —
видимо, проверка была ограничена только `core/utils/cache_keys.py`-internal
ссылками, а реальные импортёры в `infrastructure/decorators/caching/` и
`core/resilience/cache_decorators.py` были пропущены.

**Решение:** `cache_keys.py` остаётся. Это shared utility, и его
перенос/удаление сломает минимум 3 production-модуля.

## Рассмотренные альтернативы

### Вариант A — оставить (текущее состояние)

- **Плюс:** ноль риска.
- **Минус:** 293 LOC мёртвого кода; `vulture-check` (если включён) может
  флажить; новые разработчики могут случайно использовать deprecated
  модуль, не заметив `DEPRECATED.md` (его легко пропустить — это
  markdown, а не runtime-warning).

### Вариант B — удалить (рекомендуется)

- **Плюс:** −293 LOC; устраняет ловушку для новых разработчиков;
  синхронизирует код с фактической архитектурой (ADR-R-V15-8);
  `time.sleep()` в `acquire()` исчезает из кодовой базы.
- **Минус:** требует ADR (этот документ); риск поломки при динамическом
  импорте (`importlib.import_module("src.backend.core.rate_limiter")`),
  который статический grep не ловит.

### Проверка на динамический импорт

```bash
grep -rn "import_module\|__import__" src/ tests/ --include="*.py" \
  | grep -i "rate_limiter\|cache_keys"
```

→ 0 результатов. Динамического импорта нет.

### Вариант C — удалить + оставить shim с DeprecationWarning

- **Плюс:** мягкая миграция для внешних потребителей.
- **Минус:** в этом репозитории модуль не является частью публичного API
  (нет документации, нет ADR, фигурирует только в `DEPRECATED.md`).
  Shim сохраняет мёртвый код, что противоречит цели.

## Решение

**Удалить** только `src/backend/core/rate_limiter/` (245 LOC).
**Оставить** `src/backend/core/utils/cache_keys.py` — он активно
используется (см. Amendment 2026-10-16).

Обоснование для rate_limiter: доказанный нулевой импорт (статический +
динамический), уже существующая замена с лучшими свойствами
(`entrypoints/dependencies/rate_limit.py` + `infrastructure/resilience/unified_rate_limiter.py`),
и запрет-паттерн (`time.sleep` в async-контексте) в удаляемом коде.

## Последствия

### Позитивные

- Кодовая база уменьшается на 245 LOC (только rate_limiter; cache_keys остаётся).
- `time.sleep()` в потенциально-async пути исчезает.
- Deprecated-ловушка для новых разработчиков устранена.

### Негативные / риски

- `DEPRECATED.md` удаляется вместе с пакетом. Если кто-то ссылался на
  него в документации — нужно обновить ссылки (grep по `DEPRECATED.md`
  в этом PR).
- `tests/unit/core/rate_limiter/test_rate_limiter_focused.py` тоже
  удаляется (1 focused test для мёртвого кода).

### Миграция

Заменить нечего: активных потребителей нет. Для будущих изменений
использовать:

- per-route HTTP лимиты → `entrypoints/dependencies/rate_limit.py`
  (`get_default_rate_limiter()`);
- per-resource лимиты в resilience-коде →
  `infrastructure/resilience/unified_rate_limiter.py`;
- generic retry → `tenacity` (R-V15-8).

`cache_keys.build_cache_key` остаётся без изменений — её потребителям
(`caching/decorator.py`, `cache_decorators.py`) ничего не нужно
обновлять.

## Проверка после удаления

```bash
# 1. Layer check
uv run python tools/check_layers.py

# 2. Import smoke (app_factory поднимает всю композицию)
uv run python -c "import src.backend.plugins.composition.app_factory"

# 3. Полный unit-прогон по resilience + entrypoints
uv run pytest tests/unit/services/resilience/ \
             tests/unit/entrypoints/dependencies/ -q

# 4. Metrics regen (количество файлов изменится)
uv run python tools/generate_current_metrics.py --write
```

## Статус реализации

**Не выполнено.** Требуется явное подтверждение владельца
(CLAUDE.md: «удалять или переименовывать файлы, классы, модули» —
запрещено без явного подтверждения).

Ожидается: approve / reject / defer.