# T-P0.1.4 — Per-module coverage gap analysis

> **Метод:** `pytest tests/unit/<layer>/ --cov=src/backend/<layer>` (per-module)
> **Время:** ~5 сек на модуль (vs >10 мин для full coverage = timeout 600s)
> **Покрытие:** coverage.xml + term report
> **v9 цель:** 75% lines / 60% branches (минимум), 83% / 70% (target)

## core/auth coverage (02.06.2026)

| Файл | Stmts | Miss | Cover |
|------|------:|-----:|------:|
| `__init__.py` | 23 | 0 | 100% |
| `admin_role_resolver.py` | 35 | 35 | **0%** |
| `admin_roles.py` | 44 | 1 | 97% |
| `api_key_backend.py` | 12 | 2 | 83% |
| `jwks_cache.py` | 59 | 11 | 77% |
| `jwt_backend.py` | 150 | 14 | 88% |
| `jwt_backend_joserfc.py` | 178 | 69 | 56% |
| `jwt_blacklist.py` | 65 | 15 | 75% |
| `mtls_backend.py` | 85 | 22 | 75% |
| `protocols.py` | 10 | 10 | **0%** |
| `quotas.py` | 55 | 3 | 93% |
| `quotas_protocol.py` | 22 | 2 | 91% |
| `saml/__init__.py` | 4 | 0 | 100% |
| `saml/sp_handler.py` | 22 | 0 | 100% |
| `saml_backend.py` | 73 | 3 | 94% |
| **TOTAL** | **837** | **187** | **74%** |

**Tests:** 94 passed in 5.33s

## Gap analysis (worst-covered)

| # | Файл | Stmts | Cover | Что делать |
|:-:|-------|------:|------:|------------|
| 1 | `admin_role_resolver.py` | 35 | **0%** | Добавить 3-5 unit-тестов |
| 2 | `protocols.py` | 10 | **0%** | Protocol-only, не тестируемо (можно `pragma: no cover`) |
| 3 | `jwt_backend_joserfc.py` | 178 | 56% | 5-10 integration tests |
| 4 | `mtls_backend.py` | 85 | 75% | 2-3 unit tests |
| 5 | `jwks_cache.py` | 59 | 77% | 1-2 tests |

**Effort для auth 75% → 90%:** 10-15 новых тестов, ~1-2 дня.

## Другие слои (TBD)

| Слой | Тесты в tests/ | Покрытие | Статус |
|------|---------------|----------|--------|
| `core/auth/` | 94 | 74% | ✅ measured |
| `core/resilience/` | TBD | TBD | queued |
| `core/dsl/` | TBD | TBD | queued |
| `core/ai/` | TBD | TBD | queued |
| `core/utils/` | TBD | TBD | queued |
| `dsl/engine/` | TBD | TBD | queued |
| `infrastructure/` | TBD | TBD | queued |
| `services/` | TBD | TBD | queued |

## S38 реалистичный target (P0)

- **auth: 74% → 80%** (1-2 дня): 5-7 unit-тестов для `admin_role_resolver.py`, `jwt_backend_joserfc.py`
- **resilience: baseline → 75%** (2-3 дня): tests для CB/RateLimit canonical (post-deprecation)
- **dsl: baseline → 75%** (3-5 дней): tests для processors

## Что НЕ делаем

- ❌ Не пишем property-based tests (overengineering для S38)
- ❌ Не пишем E2E tests (отдельный scope)
- ❌ Не тестируем Protocols (нет логики)

## Следующий шаг

**T-P0.1.5** — добавить 3-5 unit-тестов для `core/auth/admin_role_resolver.py` (worst 0%).
- Текущий: 74.36% → 80%+ после 3-5 тестов
- 1 PR, минимальный impact
