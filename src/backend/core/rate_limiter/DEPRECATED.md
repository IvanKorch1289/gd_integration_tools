# DEPRECATED — `src/backend/core/rate_limiter/` (2026-09-21)

## Status

**DEPRECATED** — этот модуль **изолирован** (zero production callers)
и дублирует существующую реализацию в `src/backend/core/resilience/rate_limiter.py`.

## Доказательства изоляции

```
$ python tools/checks/scan_isolated_modules.py --module core.rate_limiter
Module                       | src  | tests | status
core.rate_limiter            |  0   |   1   | 🔴 ISOLATED
```

```
$ grep -rln "from src.backend.core.rate_limiter\|core\.rate_limiter\b" src/
src/backend/core/rate_limiter/__init__.py  # self-reference only
```

## Production использует

`src/backend/services/resilience/facade.py:92-93` импортирует из
`src.backend.core.resilience`, **НЕ** из `src.backend.core.rate_limiter`:

```python
from src.backend.core.resilience import (
    RateLimit,
    RateLimiter,
    get_rate_limiter,
)
```

Production rate limiter живёт в `src/backend/core/resilience/rate_limiter.py`,
экспортируется через `src/backend/core/resilience/__init__.py`.

## Почему DELETE

Аудит 2026-09-21: "Ещё один локальный token bucket без production caller увеличивает
поверхность поддержки; предпочтительнее удалить его либо использовать только как
чётко названный local/dev fallback."

Условия выполнены:
- ✅ Production имеет mature реализацию (`core/resilience/rate_limiter.py` +
  `services/resilience/facade.py` + `unified_rate_limiter.py`)
- ✅ Известно, что 27 focused tests будут удалены вместе с модулем
- ⚠️ **Требуется явное approval** для `git rm` (см. AGENTS.md deny list)

## Действия

### Pending: approval для git rm

```bash
# Требует явного одобрения пользователя:
git rm src/backend/core/rate_limiter/__init__.py
git rm src/backend/core/rate_limiter/limiter.py
git rm tests/unit/core/rate_limiter/test_rate_limiter_focused.py
git commit -m "refactor(rate_limiter): DELETE core/rate_limiter — duplicate of core/resilience/rate_limiter.py (audit 2026-09-21)"
```

### Альтернатива: оставить как experimental

Если owner решит сохранить:
- Перенести в `extensions/experimental/rate_limiter/` или закрыть feature flag
- Переименовать в `core/rate_limiter_dev/` для ясного naming
- Добавить runtime caller (e.g. dev-only rate limiting tool)

## Owner decision pending

Sprint 36 W4 или 37 должен выбрать между DELETE и EXPERIMENTAL.
Пока модуль остаётся в дереве, но помечен как DEPRECATED.
