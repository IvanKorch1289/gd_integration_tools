# P1.1 Audit: `features.py` Decomposition

> **T1.1 артефакт.** Аудит god-файла `src/backend/core/config/features.py`
> перед декомпозицией. Не код, только факты + варианты split'а.
> **T1.2 (план split'а) — отдельный шаг, требует согласование Ivan.**

## Top-level numbers (факт, 02.06.2026)

| Метрика | Значение |
|---------|:--------:|
| Файл | `src/backend/core/config/features.py` |
| LOC | 2804 |
| Pydantic-полей (`bool = Field()`) | **229** |
| Section headers (`# ─── ... ───`) | **45** |
| Module | `core.config.features` |
| Экспорты | `FeatureFlags`, `feature_flags` |

## Текущая организация (по K-номерам команд)

Структура **по командам/спринтам**, не по feature-domain:

| K-номер | Примерная тема | Полей | Секций |
|---------|----------------|:-----:|:------:|
| **K1** | Auth, Security, Secrets, Vault, Tracing, Plugins | ~22 | 7 |
| **K2** | Net & WAF, Resilience+Perf | ~24 | 4 |
| **K3** | Builder, DSL, Workflow, Source-сахар | ~50 | 7 |
| **K4** | Workflow, AI Safety, RAG, Gateway | ~30 | 5 |
| **K5** | DSL, Frontend | ~10 | 2 |
| **K6** | AI | 6 | 1 |
| **K7** | EventBus | 2 | 1 |
| **K8** | Audit & ClickHouse | 2 | 1 |
| **K9** | Extensions Migration | 2 | 1 |

## Топ-10 секций по количеству полей

| Поля | Секция | Строка |
|:----:|--------|:------:|
| **28** | Sprint 11 — AI/RAG Completion | 1592 |
| **25** | Sprint 5 — К3 DSL+Workflow | 752 |
| **23** | Sprint 19 — DSL+AI Extensions + DX | 2530 |
| **12** | Sprint 17 — GAP P0 Closure + Centralization Hardening | 1972 |
| **10** | Sprint 18 — Operational + Security GAP Carryover | 2401 |
| **8**  | Sprint 21 — Resilience & Multi-tenancy | 2120 |
| **7**  | Sprint 9 — GAP closure feature flags | 1513 |
| **7**  | Sprint 6 — К2 Resilience+Perf | 1155 |
| **7**  | Sprint 5 — К4 AI+RAG | 986 |
| **6**  | K6 — AI | 216 |
| **6**  | Sprint 6 — К1 Security | 1086 |
| **6**  | Sprint 5 — К2 Resilience+Perf | 687 |

## Группировка по feature-domain (предложение)

| Feature-domain | Источники секций | Полей (оценка) |
|----------------|------------------|:--------------:|
| **ai** | K4, K6, Sprint 5 К4, Sprint 6 К4, Sprint 7 К4, Sprint 11, Sprint 19, S24-S27 | ~70 |
| **dsl** | K3, K5, Sprint 4, Sprint 5 К3, Sprint 6 К3, Sprint 7 K3, Sprint 10, Sprint 19 | ~70 |
| **resilience** | K2, K3 Resilience, Sprint 5 К2, Sprint 6 К2, Sprint 17, Sprint 21 | ~35 |
| **auth** | K1 Auth, Sprint 5 К1, Sprint 6 К1 | ~15 |
| **security** | K1 Secrets/Vault, Sprint 5 К1, Sprint 6 К1, Sprint 18 | ~15 |
| **workflow** | K4 Workflow, Sprint 21 | ~10 |
| **observability** | K1 Tracing, K8, Sprint 18 | ~10 |
| **net** | K2 Net & WAF, Sprint 6 К2 | ~8 |
| **experimental** | Sprint 4 capability gate, Sprint 5 К5, Sprint 7 T5, Sprint 8 HTTP/3, Sprint 15 | ~10 |
| **eventbus** | K7 | 2 |

**Всего (оценка):** ~245 (включая погрешность маппинга, реально 229).

## Варианты split'а (для T1.2)

| Вариант | Модулей | Структура | Плюсы | Минусы |
|---------|:-------:|-----------|-------|--------|
| **A (5)** | 5 | auth / resilience / ai / infra / experimental | Мало файлов, простая навигация | "ai" и "dsl" слишком большие (~70 each) |
| **B (8)** | 8 | auth / security / resilience / observability / net / workflow / ai / dsl | Логические границы | "ai" и "dsl" всё ещё большие |
| **C (10)** | 10 | auth / security / resilience / observability / net / workflow / ai / dsl / eventbus / experimental | Гранулярно, 1 домен = 1 файл | Много мелких модулей, overhead |

## Backwards-compat стратегия (предложение)

После split'а сохранить `from features import feature_flags` работающим:

```python
# src/backend/core/config/features.py (slim wrapper)
from __future__ import annotations
from .features.auth import AuthFlags
from .features.resilience import ResilienceFlags
# ... etc

class FeatureFlags(
    AuthFlags, ResilienceFlags, SecurityFlags, ObservabilityFlags,
    NetFlags, WorkflowFlags, AIFlags, DSLFlags, EventBusFlags, ExperimentalFlags
):
    """Composite — backwards-compat shim. Prefer domain-specific imports."""
    model_config = SettingsConfigDict(env_prefix="FEATURE_", extra="forbid")

__all__ = ("FeatureFlags", "feature_flags")
```

Новые callsite'ы: `from src.backend.core.config.features.auth import auth_flags` (или аналог).

## Открытые вопросы (нужны решения Ivan)

1. **Структура:** A (5) / B (8) / C (10)? По умолчанию **B (8)** как баланс.
2. **Стратегия миграции:**
   - **M1 (conservative):** оставить `feature_flags.X` working, новые imports = optional.
   - **M2 (parallel):** новые imports обязательны для нового кода, старые → DeprecationWarning в S39.
   - **M3 (aggressive):** один PR с миграцией всех callsite (229 полей → много правок).
3. **Частота split'а:** один PR (все домены) или по 1 домену за PR (8 PRs)?
4. **Coupling проверка:** некоторые flags могут быть cross-domain (например, AI flag зависит от auth). Сделать pre-аудит coupling или довериться интуиции?

## Что НЕ делаем в T1.1

- ❌ Не правим код (только аудит)
- ❌ Не создаём новые модули
- ❌ Не переименовываем fields
- ❌ Не удаляем/объединяем sections

## Следующий шаг

**T1.2** — план split'а (конкретный mapping flag → domain, выбор A/B/C, стратегия M1/M2/M3).
Требует согласование Ivan.
