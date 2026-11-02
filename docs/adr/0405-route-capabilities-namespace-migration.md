# ADR-0405 — Миграция `route.toml` под namespace capability: структурированная форма `[[route.capabilities]]`

* Статус: Accepted (2026-11-02)
* Автор: wave-22, кластер B1
* Затрагивает: `routes/*/route.toml`, `src/backend/services/routes/manifest_toml.py`,
  `src/backend/dsl/cli/explanation.py`, `tests/unit/services/routes/**`,
  `tests/unit/dsl/cli/test_explanation.py`

## Контекст

Owner-задача №1 (`docs/roadmap/OWNER_TASKS.md`) — закрыть разрыв между двумя
формами объявления capability в манифестах маршрутов:

| Форма | Пример | Где |
|---|---|---|
| **legacy** (плоский список) | `capabilities = ["net.outbound", "audit.write"]` | `hello_route`, `test_route_w1`, `jupyter_hub_run`, `osint_agent` |
| **каноничная** (табличная) | `[[route.capabilities]] name = "..." scope = "..."` | `composition_demo`, `echo_demo`, `health_proxy_demo` |

Разрыв был не косметическим, а **ломающим**:

1. **Терялся scope.** Плоская строка без `":"` превращалась в
   `CapabilityRef(scope=None)`, а `CapabilityVocabulary.validate_ref`
   отвергает `scope=None` для capability с `scope_required=True`
   (`net.outbound`, `audit.write`, …). `CapabilityGate.declare` бросал
   `ValueError` → `RouteLoader` помечал роут как `failed`:
   `capability_error: Capability 'net.outbound' requires explicit scope`.
   Дефект был замаскирован выключенными feature-flag'ами роутов.
2. **Scope прятался в имя.** `"jupyter.hub:run"` и `"ai.invoke:*"` — не
   валидные имена capability: по модели ADR-0078/ADR-0366 имя берётся из
   vocabulary (`jupyter.hub`, `ai.invoke`), а scope живёт в отдельном поле.
3. **Runtime-резолвер namespace (ADR-0366)** выбирает namespace = `route_id`
   роута; без корректной декларации capability в манифесте fallback на
   core-baseline оставался единственным путём.

Governance-основание — ADR-0284 §1.1: изменение семантики декларации
авторизации оформляется отдельным ADR.

## Решение

1. **Каноничная форма — одна на все `routes/*/route.toml`:** конверт
   `[route]` + таблицы `[[route.capabilities]]` с отдельными полями `name`
   и `scope` (ADR-0078). Мигрированы `hello_route`, `test_route_w1`,
   `jupyter_hub_run`, `osint_agent`.
2. **Семантика `scope`** — «алиас ресурса» в терминах vocabulary, а не
   декоративная строка:
   * `net.outbound` — **host** внешнего сервиса: runtime-гейт сверяет scope
     по hostname (`core/net/outbound_http.py` → `CapabilityGate.check(plugin,
     "net.outbound", host)`), поэтому `scope = "api.test"` (host из
     `https://api.test/sink`), `"*.perplexity.ai"` (как у plugin-владельца
     `extensions/osint_agent`), `"localhost"` (Jupyter Hub из
     `jupyter_hub.base_url`);
   * `audit.write` — семейство audit-sink'ов: `scope = "audit:*"`
     (vocabulary: scope = tenant-id, audit-sink или `*`);
   * `ai.invoke` — `scope = "*"` (vocabulary: workflow_id pattern или `*`),
     совпадает с декларацией plugin-владельца;
   * `jupyter.hub` — `scope = "run"` (verb; раньше было `"jupyter.hub:run"`).
3. **Legacy-форма принимается, но с явным предупреждением о миграции:**
   `load_route_manifest` выдаёт `DeprecationWarning` и пишет WARNING в лог
   (`services.routes.manifest_toml`). Жёсткий отказ отложен: legacy-форму
   ещё генерируют `tools/wizards/route_templates.py` и
   `tools/scaffold_route.py` (вне зоны этой волны).
4. **Гейт** (`tests/unit/services/routes/test_route_capabilities_migrated.py`):
   ни один `routes/*/route.toml` не использует плоскую форму, каждая
   capability — таблица `name` + `scope`, имя без двоеточия и присутствует
   в `CapabilityVocabulary`; каждый манифест читается `load_route_manifest`,
   а `RouteLoader` не отвергает роуты по scope.
5. **Потребитель манифеста приведён к каноничной форме:**
   `src/backend/dsl/cli/explanation.py` разворачивает конверт `[route]` и
   читает `name` из табличной декларации — иначе `gd route explain` показывал
   для reference-роутов «capability не объявлены» (ложное срабатывание,
   зафиксированное в `artifacts/current_audit/RE_AUDIT_2026-10-15_post_fix.md`).

## Альтернативы

| Вариант | Вердикт | Почему |
|---|---|---|
| **A.** Отвергать legacy-форму на parse-time | отклонён | Ломает ещё не мигрированные route-wizard / `tools/scaffold_route.py` (вне зоны); отказ отложен до их миграции |
| **B.** Оставить плоский манифест + top-level `[[capabilities]]` | отклонён | В `routes/` остались бы две структурированные формы; owner задал канон `[[route.capabilities]]` (ADR-0078/ADR-0366) |
| **C.** Сделать `jupyter.hub` публичной capability, чтобы `jupyter_hub_run` грузился | отклонён | Запуск ноутбука = удалённое выполнение произвольного кода; публичность отдала бы привилегированную операцию любому роуту без провайдера. Роут честно остаётся незагруженным (`capability_superset`) |
| **D.** Объявлять capability без `scope` (как в legacy) | отклонён | `scope_required=True` → `CapabilityGate.declare` отвергает; это и был исходный дефект |

## Последствия

### Позитивные

* Роуты `hello_route` / `test_route_w1` / `osint_agent` **грузятся** —
  `capability_error: requires explicit scope` устранён.
* Декларация читается человеком и машиной одинаково: имя — из vocabulary,
  scope — ресурс; runtime-гейт может сопоставить scope с реальным host.
* Legacy-форма больше не молчит: миграция видна в логах и в warning'ах.
* Гейт фиксирует форму декларации — регрессия (плоский список) ломает CI.

### Отрицательные / ограничения

* `routes/jupyter_hub_run` по-прежнему не грузится: `jupyter.hub` не
  покрыта ни одним плагином-владельцем (осознанное least-privilege решение,
  зафиксировано в `vocabulary/defaults/base.py`).
* `scope` для `net.outbound` привязан к host'у: при смене внешнего сервиса
  декларацию надо обновлять (это и есть цель least privilege).
* `tools/wizards/route_templates.py` и `tools/scaffold_route.py` продолжают
  генерировать legacy-форму (вне зоны) — до их миграции scaffolded-роут
  грузится с warning'ом.

## Проверка

```bash
# Гейт миграции + загрузка всех роутов
uv run pytest tests/unit/services/routes/ -q

# Legacy-форма принимается с предупреждением о миграции
uv run pytest tests/unit/services/routes/test_manifest_toml.py -q

# Прочие гейты репозитория
uv run ruff check src/backend/services/routes/manifest_toml.py src/backend/dsl/cli/explanation.py tests/unit/services/routes
uv run ruff format --check src/backend/services/routes/manifest_toml.py src/backend/dsl/cli/explanation.py tests/unit/services/routes
uv run python tools/check_docstrings.py          # 0 missing
uv run python tools/config_audit.py --scope orphans   # 0
uv run python tools/check_layers.py --strict          # без новых нарушений
uv run python tools/checks/mypy_budget.py              # бюджет 30
```

Фактическое состояние на момент принятия ADR: 6 из 7 роутов загружаются
(`enabled`), `jupyter_hub_run` — `failed` с `capability_superset` (осознанное
least-privilege решение, см. «Альтернативы», вариант C).

## Связи

* **ADR-0078** — синтаксис `[[capabilities]]` (`name` + `scope`).
* **ADR-0366** — runtime-резолвер namespace (`route_id` роута).
* **ADR-0393** — capability-гейт и least privilege в prod/staging.
* **ADR-044** — vocabulary, `CapabilityGate`, инвариант
  `route.capabilities ⊆ union(plugins) ∪ public`.
* **ADR-0284 §1.1** — governance: изменение семантики декларации авторизации
  оформляется отдельным ADR.
* **Owner-задачи** — `docs/roadmap/OWNER_TASKS.md`, п. 1.
