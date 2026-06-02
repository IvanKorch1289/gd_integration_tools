# T1.2 — План split'а `features.py` → 8 доменных модулей

> **T1.2 артефакт.** Конкретный mapping flag → domain + стратегия миграции.
> Defaults применены за Ivan (таймаут, ожидание явного ответа):
> **B (8 модулей) + M1 (conservative) + по 1 домену за PR**.

## Структура: 8 feature-доменов

```
src/backend/core/config/features/
├── __init__.py                  # re-exports (backwards-compat)
├── auth.py                      # K1 Auth, JWT, ...
├── security.py                  # K1 Secrets/Vault, plugins, ...
├── resilience.py                # K2 Net, K3 Resilience, Sprint 5/6 К2, Sprint 17, Sprint 21
├── observability.py             # K1 Tracing, K8 Audit, Sprint 18
├── net.py                       # K2 Net & WAF (ConnectionReuse, etc)
├── workflow.py                  # K4 Workflow, Temporal
├── ai.py                        # K4 AI, K6, Sprint 5/6/7 К4, Sprint 11, Sprint 19, S24-S27
├── dsl.py                       # K3, K5, Sprint 4, Sprint 5/6/7 К3, Sprint 10
└── experimental.py              # Sprint 5 К5, Sprint 7 T5, Sprint 8, Sprint 15
```

`features.py` (на верхнем уровне) становится **slim shim**:

```python
# src/backend/core/config/features.py
from .features.auth import AuthFlags
from .features.security import SecurityFlags
# ... etc
class FeatureFlags(AuthFlags, SecurityFlags, ...):
    """Composite — backwards-compat shim. Prefer domain-specific imports."""
    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

__all__ = ("FeatureFlags", "feature_flags")
```

## Стратегия миграции: M1 (conservative)

- **Старый API (`from features import feature_flags; feature_flags.X`)** — работает как и раньше через shim
- **Новый API (`from core.config.features.auth import auth_flags; auth_flags.X`)** — optional, не обязателен
- **DeprecationWarning** — НЕ ставим в S38 (отложено в V24)
- **Удаление старого shim'а** — V24+ (post-V23)

## Частота split'а: по 1 домену за PR (8 PRs)

Причины:
- Атомарно — каждый PR можно откатить отдельно
- Pre-prod-check baseline (38/38) ловит регрессии после каждого PR
- Coverage gate не падает (новые модули можно покрывать постепенно)
- Code review проще (1 домен = 1 PR)

## План PR'ов (последовательность)

| # | PR | Домен | Полей (оценка) | Строки в коде |
|:-:|---|-------|:--------------:|:-------------:|
| 1 | T1.3.1 | `auth.py` | ~15 | 1 домен |
| 2 | T1.3.2 | `security.py` | ~15 | 1 домен |
| 3 | T1.3.3 | `resilience.py` | ~35 | 1 домен |
| 4 | T1.3.4 | `observability.py` | ~10 | 1 домен |
| 5 | T1.3.5 | `net.py` | ~8 | 1 домен |
| 6 | T1.3.6 | `workflow.py` | ~10 | 1 домен |
| 7 | T1.3.7 | `ai.py` | ~70 | 1 домен (большой) |
| 8 | T1.3.8 | `dsl.py` | ~70 | 1 домен (большой) |
| 9 | T1.3.9 | `experimental.py` | ~10 | 1 домен (маленький) |
| 10 | T1.4 | `features.py` shim + `__init__.py` | 0 | backwards-compat |

**Стоп после каждого PR.** Ревью через `requesting-code-review`, pre-prod-check baseline (38/38 → sustain).

## Coupling handling (без pre-аудита)

Если в первом PR (auth.py) обнаружится, что какие-то flags зависят от security/dsl — фиксим inline. Документируем в audit-файле.

Не делаем pre-аудит coupling (overengineering).

## Тестирование

- Существующие тесты `tests/unit/core/config/test_features.py` (если есть) должны проходить без изменений
- Каждый новый модуль — минимум 1 sanity-тест (smoke import)
- Coverage gate (75% strict) — sustain, не улучшаем

## Что НЕ делаем в T1.2 (явно out of scope)

- ❌ Не переименовываем fields
- ❌ Не удаляем/объединяем sections
- ❌ Не ставим DeprecationWarning (V24+)
- ❌ Не удаляем features.py (V24+)
- ❌ Не делаем pre-аудит coupling

## Открытые вопросы (можно решить inline)

- **Имя переменной в каждом модуле:** `auth_flags`, `security_flags`, etc. (или `flags`?). Default: `<domain>_flags` (явно).
- **Класс в каждом модуле:** `AuthFlags(BaseSettingsWithLoader)`, etc. Default: `<Domain>Flags`.
- **Re-exports в `__init__.py`:** explicit list или `__all__ = ("auth_flags", ...)`. Default: explicit.

## Следующий шаг

**T1.3.1 — PR #1: `auth.py` (15 полей).** Скелет + миграция + sanity-тест + ревью + коммит.

Ожидает согласование Ivan (если передумал — текстом «A/C + M2/M3» или «стоп»).
