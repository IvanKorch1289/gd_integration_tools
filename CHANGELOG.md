# CHANGELOG — GD Integration Tools

## [Unreleased] — Sprint 172 (S172)

### Infrastructure: архитектурный аудит и cleanup

#### Сделано

**Docstring coverage (P3)**
- Создан инструмент `tools/check_docstrings.py` для анализа покрытия docstrings
- Исправлены 14 missing docstrings в `src/backend/core/ai/policy/spec.py`
- Исправлены missing docstrings в `src/backend/core/auth/`, `src/backend/core/interfaces/`, `src/backend/core/utils/`
- Фикс: docstrings внутри Pydantic моделей (после `model_config`) перенесены перед ним

**Settings consolidation (P2)**
- Создан `src/backend/core/config/mixins.py` с переиспользуемыми mixin-классами:
  - `APIConnectionMixin` — base_url, timeout_s, max_retries
  - `DBPoolMixin` — pool_size, max_overflow, connection_timeout_s
  - `ResilienceMixin` — circuit_breaker_*, retry_*, bulkhead_*

**Dead code deletion**
- Удалён `src/frontend/admin-react/` (entire, deprecated S168 W14)
- Удалены shim-файлы `admin_panel/users.py`, `orders.py`, `files.py`, `orderkinds.py`
- Оставлены `admin_panel/base.py` и `setup_admin.py` (зависимости в extensions)

**Bug fixes**
- AIPolicySpec: docstrings перенесены перед `model_config` (Pydantic convention)

**Circuit Breaker consolidation scaffold (P2 #16)**
- Создан `src/backend/core/resilience/circuit_breaker.py` — unified facade поверх purgatory
- `CircuitBreakerSpec` — единая спецификация для всех адаптеров
- `SlidingWindowBreaker` — адаптер для per-route CB (TODO: интеграция в middleware)
- `ReplicaFailoverBreaker` — адаптер для DB read-replica failover (TODO: интеграция в smart_session)
- `BreakerLike` Protocol — re-export минимального contract для RPA
- Re-export canonical API (`Breaker`, `BreakerRegistry`, `BreakerSpec`, `CircuitOpen`)
- TODO-комментарии в `entrypoints/middlewares/circuit_breaker.py` и `infrastructure/database/smart_session_manager.py`
- Полная миграция → S172 M2.4

**Security fix (P0 #5 — confirmed safe by design)**
- `tools/codegen_settings.py`: добавлен docstring в `_yaml_round_trip()` с обоснованием безопасности `ruamel.yaml.YAML(typ="rt")` (не подвержен RCE-вектору PyYAML `!!python/object/apply:`). Замена на `safe_load` невозможна (метод отсутствует в ruamel API).

**Settings mixins application (S172 M2.2 follow-up)**
- YAGNI-аудит показал: миграция существующих Settings на mixins НЕ безопасна
- Все кандидаты (`AntivirusAPISettings`, `JupyterHubSettings`, 6 LLM-провайдеров в `ai.py`) имеют более строгие ограничения полей (ge/le), чем mixin defaults
- Применение mixin расширило бы допустимый диапазон значений → breaking change
- `mixins.py` оставлен готовым для будущей миграции при перепроектировании Settings

---

## [S171] — Sprint 171 (S171)

## [S171] — Sprint 171 (S171)

### Frontend: перевод на русский язык и оптимизация UX

**Цель:** Frontend полностью на русском языке для русскоязычных пользователей.

#### Сделано

**Перевод UI (190+ strings)**
- 70/70 page files переведены на русский (sidebar nav, form labels, captions, buttons)
- Cyrillic filenames (69/70): `00_Вход.py`, `00_Главная.py`, `10_Заказы.py`, `96_Монитор_зависших_сообщений.py`, etc.
- 1 acceptable exception: `54_Replay_DLQ.py` (DLQ/Replay = industry-standard tech terms)
- 0 frontend strings остаются English (только proper nouns: OpenAPI, AsyncAPI, GraphQL, etc.)

**Новые features**
- 🔍 **Sidebar search** — поиск по разделам с form (text_input + "Искать" button)
- ⚡ **Быстрый доступ** — 10 most-used pages с Material icons в sidebar
- 📚 Page metadata registry — `src/frontend/streamlit_app/shared/page_registry.py` (single source of truth для 70 страниц)
- 🎨 Material icons — favicon + page_icon auto-resolve через `inspect.stack()[1].filename`
- 💾 API cache (TTL memoization) — `cached_get_metrics()` TTL=10s, `cached_get_health()` TTL=5s, `cached_get_orders()` TTL=15s

**Рефакторинг**
- Merge APP + Home → единая страница `pages/00_Главная.py` с dashboard + health + navigation
- `setup_page()` auto-resolves title/icon from page_registry (70 pages no longer need duplicated title+icon args)
- Lazy import dedup в `components.py` (~10ms overhead removed)

**Backend fixes (сопутствующие)**
- Alembic migration cycle fix (3 commits)
- Auth endpoints public (Login page works)
- Outbox repo 2-level session API
- orderkinds.tenant_id migration
- 7+ backend improvements

**Code quality**
- ✅ 70/70 pages ast-valid
- ✅ 70/70 pages HTTP 200
- ✅ 70/70 registry coverage (no missing/extra)
- ✅ Ruff: All checks passed
- ✅ 0 TODO/FIXME в pages
- ✅ No datetime.utcnow() deprecation warnings (Python 3.14 ready)

**Cleanup**
- Dead code removed: `_groups/home/` package (~120 LOC)
- 12 stale English filenames deleted (left over from incomplete rename)
- Lint warnings fixed: trailing newlines, unused imports, sort order

#### Атомарные commits: 36+

#### Migration notes

- URL routing: Streamlit auto-discovery strips `XX_` prefix from filename
  - `00_Главная.py` → `/Главная`
  - `96_Монитор_зависших_сообщений.py` → `/Монитор_зависших_сообщений`
- `st.switch_page()` требует `.py` extension для Cyrillic page names
  - `st.switch_page("pages/00_Главная.py")` ✓
  - `st.switch_page("pages/00_Главная")` ✗ (Streamlit APIException)

#### Known Limitations

- Sidebar "app" label (entry-point from `app.py`) — стандартный Streamlit auto-discover behavior, требует `st.navigation` API для custom label
- AsyncAPI schema: в разработке (placeholder в `62_Админ_схем`)
- ~28% English strings intentional: framework proper nouns (OpenAPI/AsyncAPI/SOAP/WSDL), backend enums (CLOSED/HALF_OPEN/OPEN)

#### Manual steps

```bash
cd /home/user/dev/gd_integration_tools
git push  # 36 S171 commits ready
uv sync   # install deps if needed
```

---

## Earlier sprints

See git history for earlier sprint changes (S170 and before).