# S173 — Финальный UI/UX анализ фронта GD Integration Tools

**Период**: ~3 сессии (4 раунда fix + Round 5 analysis)
**Метод**: grep-анализ всех 69 страниц + AST inspection + live browser (Streamlit 1.58.0)
**Скоуп**: `src/frontend/streamlit_app/`

──────────────────────────────────────
## TL;DR

| Метрика | До S173 | После S173 |
|---|---:|---:|
| Frontend tests passed | 384 | **405** (+21) |
| Frontend test failures | 9 | **0** |
| Collection errors | 1 | **0** |
| Backend re-export broken symbols | 11 | **0** |
| Pages без caption | 7 | **2** (shims) |
| Streamlit router files (single source) | 0 (auto-discover) | **1** (`app.py`) |
| Sidebar: grouped nav | ❌ (flat) | **✅** (10 секций) |

**Остаётся** (out of S173 scope): 3 god-pages >300 LOC, 0 кросс-навигации, security review RBAC.

──────────────────────────────────────
## ✅ Сделано в S173

### Round 1 — UI/UX Audit (analysis only)
**Найдено**:
- 3 страницы без `setup_page()`: 2 cron-shims + 1 OK (Вход)
- 7 страниц без caption/описания
- 31 страница с mixed-language заголовками (эмодзи + tech terms — норма)
- 3 god-pages >300 LOC: `31_DSL_Визуальный_редактор` (611), `62_Админ_схем` (373), `54_Replay_DLQ` (345)
- 0/69 `st.page_link` — нет кросс-навигации
- 1/69 `st.switch_page` — только login redirect
- 1/69 auth check — только Home
- 8/69 `st.spinner` — мало feedback для долгих операций

### Round 2 — Streamlit-auto-sidebar fix
- `app.py` (entry-point, Kimi Code d5d5541) переиспользует `st.navigation()` с 10 секциями
- В этой сессии: `Главная.py` → router (позже удалён как мёртвый код, т.к. manage.py указывает `app.py`)
- Live-фильтр в sidebar (без submit-кнопки)
- 0+ Playwright manual verified

### Round 3 — Backend re-export fix (`builder_facade.py`)
- Добавлено 11 недостающих импортов
- Unblocked: `dsl_portal/__init__.py`, `_editor/yaml_sync.py`, `pages/33_DSL_Шаблоны.py`
- Cascade: `test_dsl_editor_helpers.py` collection error → resolved

### Round 4 — 4 frontend tests sync
- 9 pre-existing failures с английскими filenames (страницы переименованы в русские, тесты не обновили)
- 45_admin.py → 45_Админ.py
- 54_DLQ_Replay → 54_Replay_DLQ
- 70_Tenants → 70_Тенанты
- 71_Capabilities → 71_Матрица_возможностей
- 30_Files_S3 → 57_Файлы_S3
- 66_Workflow_Logs → 66_Логи_Воркфлоу
- 31_DSL_Visual_Editor → 31_DSL_Визуальный_редактор
- 86_DSL_Usage_Audit → 86_Аудит_использования_DSL (без DSL_ prefix)
- 9 failed → 0 failed

### Round 5 — UX polish (5 captions)
- 10_Заказы: "CRUD заказов: просмотр списка, создание и удаление."
- 35_Мастер_генерации_кода: "Wizard для запуска codegen-инструментов из UI..."
- 37_API_Вызовы: "Универсальный клиент к backend..."
- 47_AI_Безопасность: "Метрики guardrail-проверок per-tenant..."
- 48_Лаборатория_промптов: "Управление версиями prompt'ов, A/B-сравнение, rollback..."
- 7 → 2 страниц без caption (остались cron shims)

──────────────────────────────────────
## 🚨 ОТКРЫТЫЕ ISSUES (Round 5 deep audit)

### P0 — Security / Critical

**S1. 63_Вики.py:69 — `unsafe_allow_html=True`**
```python
st.markdown(h.snippet, unsafe_allow_html=True)
```
- `snippet` приходит из Whoosh search index (`whoosh_index`)
- Источник контента: docs/ директория (controlled by team, low XSS risk)
- **Рекомендация**: добавить `bleach.clean()` или заменить на `st.markdown(h.snippet)` (auto-escape)
- Файл: `src/frontend/streamlit_app/pages/63_Вики.py:69`

**S2. Admin pages без auth/RBAC gate (10 файлов)**
- 45_Админ, 50_Фича_флаги, 60_Админ_кеша, 61_Журнал_аудита, 64_SQL_Админ,
  70_Тенанты, 73_Просмотр_конфига, 76_Подключение_плагинов, 88_Тенантные_фича_флаги, 83_Инспекция_тенанта
- Frontend НЕ проверяет auth (`is_authenticated` отсутствует)
- API client (`api_clients/base.py:78-80`) отправляет `Authorization: Bearer {token}` только если `set_token()` вызван
- **Вопрос**: backend RBAC достаточно для защиты? Неаутентифицированный пользователь может открыть Streamlit → делает HTTP без token → backend отвечает 401?
- **Рекомендация**: добавить `if not is_authenticated(): st.warning("Требуется вход"); st.stop()` в admin pages; проверить backend RBAC

**S3. 11 WRITE-action pages без auth gate**
- Все делают `client.create/update/delete/post/put`
- Нет `is_authenticated` ни в одной
- Если пользователь открывает страницу без login — API вызовы идут без токена, backend должен отвергнуть

### P1 — UX Issues

**U1. 0/69 кросс-навигация (`st.page_link`)**
- 69 страниц — нет ссылок между связанными разделами
- Примеры упущенных связей:
  - 16_Воркфлоу ↔ 17_Replay_Воркфлоу ↔ 18_Версионирование_Воркфлоу (related)
  - 22_RAG_Консоль ↔ 75_Мастер_загрузки_RAG ↔ 85_Массовая_загрузка_RAG
  - 11_Маршруты ↔ 59_Отладчик_маршрутов ↔ 58_Шина_действий
- **Рекомендация**: добавить в footer каждой страницы 2-4 `st.page_link` на связанные

**U2. 9 страниц без try/except (crash on network errors)**
- 13_Конструктор_Cron, 14_Панель_Cron (shims — render() внутри)
- 68_Маркетплейс_плагинов, 70_Тенанты, 71_Матрица_возможностей
- 75_Мастер_загрузки_RAG, 76_Подключение_плагинов, 77_Каталог_процессоров
- 95_Покрытие_EIP
- Cron shims — вызывают `_groups/cron/*.render()` который может крашить
- **Рекомендация**: добавить try/except в entry-point файлах

**U3. 3 god-pages >300 LOC (decomposition candidates)**
- 31_DSL_Визуальный_редактор.py: **611** LOC — самый большой
  - Структура: 15 visual containers (tabs/expanders), 0 long functions
  - Уже частично декомпозирован: импортирует 11 функций из `_editor/`
  - **Следующий шаг**: extract inline-блоки в `_editor/` модули
- 62_Админ_схем.py: **373** LOC
  - Структура: 3 main tabs (Импорт / Реестр / API-схемы)
  - API-схемы: 6 sub-tabs (OpenAPI/AsyncAPI/SOAP/gRPC/GraphQL/XML-XSD)
  - **Следующий шаг**: extract `_groups/schema/{import,registry,viewer}/`
- 54_Replay_DLQ.py: **345** LOC
  - Структура: 3 helper-функции (`_get_outbox`, `_run_async`, `_ensure_demo_data`)
  - **Следующий шаг**: extract `_groups/replay/dlq/`

**U4. 8/69 страниц с `st.spinner` (мало feedback для долгих операций)**
- Спиннер есть в: 20_AI_Чат, 21_AI_Обратная_связь, 39_Консоль_вызовов, 58_Шина_действий,
  63_Вики, 66_Логи_Воркфлоу, 85_Массовая_загрузка_RAG, 86_Аудит_использования_DSL
- **Рекомендация**: добавить spinner в API calls во всех 61 страницах (где есть try/except)

### P2 — Косметика

**C1. 15/69 `help=` параметр** — мало подсказок для form inputs
**C2. 3/66 страниц с explicit labels** — Streamlit auto-label OK, но для accessibility нужен explicit label
**C3. Inline-блоки в 31_DSL_Визуальный_редактор** — длинные inline tabs/expanders можно вынести в функции

──────────────────────────────────────
## 📋 Файлы изменённые в S173

```
backend:
  src/backend/services/dsl_portal/builder_facade.py        +11 import lines

frontend (router + captions + redirect):
  src/frontend/streamlit_app/Главная.py                    +251/-193 (router, deleted)
  src/frontend/streamlit_app/pages/00_Вход.py              +1/-1 (redirect → app.py)
  src/frontend/streamlit_app/pages/10_Заказы.py            +1/-0 (caption)
  src/frontend/streamlit_app/pages/35_Мастер_генерации_кода.py  +5/-0 (caption)
  src/frontend/streamlit_app/pages/37_API_Вызовы.py        +4/-0 (caption)
  src/frontend/streamlit_app/pages/47_AI_Безопасность.py   +5/-0 (caption)
  src/frontend/streamlit_app/pages/48_Лаборатория_промптов.py +4/-0 (caption)
  src/frontend/streamlit_app/shared/page_registry.py       sync titles
  src/frontend/streamlit_app/pages/PAGES_GROUPS.toml       82→88 prefix fix

tests:
  tests/unit/frontend/streamlit_app/test_33_dsl_templates_imports.py  +facade expectations
  tests/unit/frontend/streamlit_app/test_page_registry.py           sync
  tests/unit/frontend/test_admin_pages_imports.py                   45_admin → 45_Админ
  tests/unit/frontend/test_k5_pages_imports.py                      K5_PAGES → real filenames
  tests/unit/frontend/test_no_sys_path_hacks.py                     31/86 → Cyrillic
  tests/unit/frontend/test_workflow_logs_page.py                   66_Workflow_Logs → 66_Логи_Воркфлоу
```

──────────────────────────────────────
## 🎯 Рекомендации для S174+

### Priority queue (вне scope S173):
1. **Security review (P0)**:
   - Аудит backend RBAC для admin endpoints
   - Добавить `is_authenticated` gate в 10 admin pages (или подтвердить что backend защищает)
   - Sanitize `63_Вики.py:69` XSS risk
2. **God-pages decomposition (P1)**:
   - Extract `31_DSL_Визуальный_редактор` inline-блоков в `_editor/` (15 visual containers → modules)
   - Extract `62_Админ_схем` 3 tabs → `_groups/schema/{import,registry,viewer}/`
   - Extract `54_Replay_DLQ` → `_groups/replay/dlq/`
3. **Кросс-навигация (P1)**:
   - Добавить `st.page_link` footer с 2-4 связанными страницами
   - Использовать `PAGE_METADATA` для автогенерации related pages
4. **Spinner coverage (P1)**:
   - Wrap API calls в `with st.spinner("Загрузка..."):` в 61 странице без spinner
5. **Form help text (P2)**:
   - Добавить `help=` к основным inputs в admin pages

──────────────────────────────────────
## ✅ Не нашёл проблем

- **Bare except** — 0/69 страниц (хороший code style)
- **Hardcoded secrets** — 0 найдено (anti-pattern check чистый)
- **Try/except coverage** — 60/69 страниц (87%, хорошо)
- **Test coverage** — 405 tests passing, 0 failures
- **Page title consistency** — все в PAGE_METADATA синхронизированы
- **Cyrillic URL backwards-compat** — Streamlit auto-strip prefix работает

──────────────────────────────────────
## Коммиты S173 (без пуша, 5 шт)

```
19e012e S173: add st.caption descriptions to 5 pages without them
ab931d7 S173: remove dead Главная.py router — single entry-point app.py
8dfa5ba S173: sync 4 frontend tests with Cyrillic page filenames
458a40a S173: fix builder_facade re-export chain — unblock dsl_portal facade
384db7e S173: Streamlit router via st.navigation() — grouped sidebar
```

Итого: 5 коммитов, +313 строк, -466 строк (net -153 — преимущественно cleanup).

Все S173 задачи завершены. Открытые issues описаны в P0/P1/P2 выше для S174+.