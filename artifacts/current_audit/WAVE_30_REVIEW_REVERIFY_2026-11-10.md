# Повторный анализ и перепроверка (волна 30, 2026-11-10)

Инструменты: скиллы `code-review`, `python-dev`, `ponytail` (+ `graphify`:
индекс обновлён — 135 237 nodes / 186 388 edges; `explain`/`path`/`query` по
зонам изменений). Скилл `update-config` не применялся: он про конфигурацию
самого Kimi CLI, а не приложения.

Область ревью: волны 28–29 (`00e69575e..HEAD`, 54 файла, +2676/−496).

---

## 1. Code review — findings и что сделано

### 🔴 Блокеры — 0 (после правок)

### 🟡 Важно — 2 (исправлены в этой волне)

1. **`src/backend/entrypoints/api/v1/endpoints/webhook_scheduler.py:77` — tenant-скоупинг
   webhook'а не проверялся.** ADR-0345 требует сверять явный `tenant_id` с
   тенантом вызывающего; оператор мог указать чужой тенант. Исправлено:
   `auth: _AdminCtx` (OPERATOR/SUPER_ADMIN) → `extract_tenant_id(auth)`;
   mismatch → 403, иначе тенант вызывающего. Тесты: `test_schedule_webhook_rejects_foreign_tenant`,
   `test_schedule_webhook_uses_caller_tenant` (в `tests/unit/api/test_guardrails_webhook_endpoints.py`).
2. **`src/backend/entrypoints/api/v1/endpoints/admin_runtime_metrics.py:75` — `/admin/processes/active`
   возвращал несуществующее поле `workflow_id`** (`WorkflowInstanceRow` такого поля
   не содержит → всегда `None`). Исправлено: `workflow_name`, `route_id`,
   `status`, `tenant_id`, `created_at`.

### 🟢 Нит — 0 (ruff/format зелёные)

### Автоматические проверки (по чеклисту скилла)

| Проверка | Результат |
|---|---|
| Секреты в коде (`make secrets-check`) | чисто |
| Слои (`check_layers.py --strict`) | 41 — прежний долг, регресса нет |
| Blocking I/O в async (AST-скан по 18 изменённым модулям) | 0 |
| `except Exception` без логирования | 0 в новом коде (находки — CLI-вывод и `st.error` в портале) |
| `print()` в production-коде | только CLI-инструменты (`dsl/cli/lint.py`, `tools/check_route_capabilities.py`) — норма для CLI |
| Mutable default args | 0 |
| Type hints (mypy) | 12 ошибок при бюджете 30 (было 30; рэтчет обновлён) |
| Vulture (dead code) | 1 находка — pre-existing (`config_loader.py:995`) |
| Refurb | не установлен (skipped) |

---

## 2. python-dev — соответствие правилам

| Правило | Проверка | Итог |
|---|---|---|
| `entrypoints/` → только `services/`, `core/`, `schemas/` | `check_layers --strict` | без новых нарушений |
| `core/` не импортирует `src/` | проверка слоёв | ок (новый `core/security/capabilities/caller.py` — только stdlib) |
| `extensions/` без прямых импортов infrastructure/services | проверка слоёв | ок |
| async-first, без blocking I/O | AST-скан | ок |
| `await` с таймаутом | внешние вызовы — через `guarded_external_call` (CB + bulkhead) | ок |
| Pydantic v2 DTO | новые эндпоинты — `BaseModel` (`PromptVersionCreate`, `PromptActivate`, `WebhookScheduleRequest`) | ок |
| Type hints, `Any` с обоснованием | mypy-бюджет 12/30 | ок |
| Тесты: markers, имена, fixtures | новые файлы — `@pytest.mark.unit`, `pytest.mark.asyncio` | ок |
| `make lint-strict` | ruff `src/` — All checks passed | ок |
| `graphify update .` после структурных изменений | выполнено (индекс пересобран) | ок |

---

## 3. Ponytail — ревью на over-engineering

| Решение | Оценка |
|---|---|
| 6 новых модулей (`providers/prompts.py`, `processors/_resilience.py`, 4 эндпоинта) | по одному на конкретную дыру; лишних абстракций/фабрик нет |
| `guarded_external_call` — одна обёртка на 5 процессоров | вместо 5 копий ✓ (проверка — 1 тест-файл) |
| ADR 0434–0441 (8 шт.) | не «лишняя документация», а требование проекта (ADR-0284 §1.1: решения по capability/security/семантике фиксируются ADR); каждая — про отдельное решение |
| `tools/check_route_capabilities.py` + baseline-файл | рэтчет вместо «все роуты должны объявлять» (иначе CI красный сразу) |
| Удаление дублей (`dsl/cli/lint.py` → тонкая обёртка) | deletion over addition ✓ |
| Не реализовано (осознанно): сводка очередей, SQL-консоль, `audit.write`-декларации, строгая проверка scope у процессоров | capability отсутствует / требует решения владельца — зафиксировано в реестре |

---

## 4. Перепроверка приложения

* **Образ пересобран** (`gd-integration-tools:light`, свежая сборка), контейнеры
  пересозданы: `/health` 200, `/ready` 200.
* **Smoke маршрутов**: 14 новых/портальных путей → **401** (маршрут зарегистрирован,
  требуется admin/tenant-право), `POST /api/v1/auto/admin.get_config` → 401,
  `POST /graphql` → 401 (auto-schema поднялась: queries=8, mutations=16),
  `POST /api/v1/webhook/schedule` → 401.
* **Гейты**: ruff `src/` ✓ · mypy 12/30 ✓ (рэтчет) · docstrings 0 ✓ ·
  `check_route_capabilities` ✓ (4 легаси в baseline) · `check_workflow_specs` ✓ (22) ·
  `classify_object_authorization --strict` 0 unknown ✓ · secrets-check ✓ ·
  vulture — 1 pre-existing ✓.
* **Регрессия**: `tests/unit` — см. `.run/wave13-logs/reg_final_30.txt`.

---

## 5. Остаток (owner-задачи)

Без изменений по сравнению с волной 29: сводка очередей (нет capability),
SQL-консоль (решение владельца — не поднимать), `audit.write`-декларации
(рекомендация — не объявлять до enforcement), инфраструктурные действия из
`docs/ops/infra-release-checklist.md`.
