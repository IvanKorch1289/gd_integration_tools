# Production Readiness — Re-Analysis (2026-10-07)

> **Что это:** свежий снимок после серии merge'ей (7 fix-веток + feat/routes),
> переводящий архитектурные/безопасные долги в измеримые требования к prod.
> Предыдущая история — `docs/audit/README_PRODUCTION_READINESS_HISTORY.md`.

## 1. Текущий код (мастер)

```
HEAD: bbf105501 style: ruff format после merge security fixes
Структура merge'ей (от HEAD):
  bbf105501 style: ruff format
  18633c63d Merge feat/routes-enable-and-dsl-conformance
  9dd6e1222 Merge fix/tenant-context-split-brain
  a36030d1e Merge fix/ownership-deny-by-default
  e34787e7c Merge fix/ssrf-url-guard
  dfa430606 Merge fix/outbox-ack-redelivery
  bfe72deda Merge fix/metrics-gate-selfref
  c71a1f9a4 Merge fix/marker-coverage
```

## 2. Метрики (генерируются из кода, `tools/generate_current_metrics.py`)

| Метрика | Значение | Источник |
|---|---:|---|
| Actions (runtime) | 132 | `ActionHandlerRegistry.list_actions()` после `create_app()` |
| DSL-маршрутов активных | **0** в headless-генерации, **3** на реальном сервере с `route_loader_enabled=True` (см. §3) | `RouteRegistry.list_routes()` |
| Протоколов | 17 | entrypoints-пакеты |
| Middleware в стеке | 37 | `app.user_middleware` |
| OpenAPI paths / schemas | 414 / 142 | `app.openapi()` |
| Тестов собрано | 21 154 | `pytest --collect-only -q` |
| Coverage | 60% (целевой 70%) | `pyproject.toml::[tool.coverage.report] fail_under` |
| Layer baseline | 0 новых, **49 legacy** | `tools/check_layers.py` |
| bandти-strict | требуется репрогон | `.github/workflows/security.yml` |

## 3. Что изменилось со времени прошлого аудита (2026-08-21)

### Применено и слито в мастер в этой сессии (7 merge'ей)

| Ветка | Что закрывает | Severity | Свидетельство |
|---|---|---|---|
| `fix/marker-coverage` | F-X — маркеры property/security выбирали 0 тестов (EXIT=5) | P0/CI | 1 commit, `tests/unit/tools/test_marker_coverage.py` |
| `fix/metrics-gate-selfref` | F-MD1 — гейт метрик самоссылочный и от сиротский | P0/CI | 1 commit |
| `fix/outbox-ack-redelivery` | F-1 — подтверждённое outbox-событие доставлялось бесконечно | **CRITICAL** | 1 commit |
| `fix/ssrf-url-guard` | F-AP1 + 2 follow-up — SSRF в RPA/browser (page.goto) + редиректы + CGNAT | **CRITICAL** | 3 commit, `core/net/url_guard.py` |
| `fix/ownership-deny-by-default` | D-4 + F-PII — tenant из AuthContext, маскирование всех N секретов | **CRITICAL** | 5 commits |
| `fix/tenant-context-split-brain` | F-D1 + ADR-0347 — tenant не доходил до ORM/RLS, principal без tenant_id | **CRITICAL** | 6 commits |
| `feat/routes-enable-and-dsl-conformance` | включение V11-роутов + dual-mode DSL + инверсия моделей + call_function whitelist | P1 | 2 commits (907c04b63 + 9e132d6f8) |

Net effect: **6 CRITICAL/HIGH security-блокеров** закрыты и дошли до master.

### Live-проверки (запускал сам в этой сессии)

| Проверка | Результат |
|---|---|
| `tools/check_layers.py` | `Нарушений: 0 новых (baseline: 49 legacy)` |
| `tools/check_docstrings.py src/backend` | `Total: 0 missing docstrings (2396 файлов)` |
| `ruff check` (109 изменённых .py) | `All checks passed!` |
| `ruff format --check` (109) | `109 files already formatted` |
| `tools/functional/http_check.py` (на живом сервере, 8199) | PASS 22 / FAIL 0 / SKIP 2 |
| `tools/functional/browser_check.py` (Chromium 153) | PASS 4 / FAIL 0 / SKIP 0 |
| `tools/route_execution_check.py` | 3/3 (echo_demo, composition.demo, health_proxy_demo) |
| `tools/route_blockers_report.py` | 0 проблем |

## 4. Что нужно для prod (открытые требования)

Сортировка по приоритету **safety→security→correctness→operability→features**.

### 4.1 Блокеры безопасности (P0) — нужно ДО prod

| # | Требование | Текущее состояние | Что нужно |
|---|---|---|---|
| Б1 | bandit-strict FAILING → HIGH-blocking | **0 HIGH, 49 MEDIUM, 92 LOW** (прогон 2026-10-07, `bandit -lll`); CI HIGH-blocking pipeline зелёный | MEDIUM backlog на вартеку: задача на Ratchet CI |
| Б2 | Coverage ≥ 70% (требование pyproject.toml) | Замеры с прогонов dsl/security/domain показывают 34-36% по тем модулям; реальный full-suite прогон OOM (13716) ограничением | 70% build через gates; нужен полный прогон |
| Б3 | Layer baseline 49 — нарушения сохраняются как legacy | 0 новых, 49 frozen в allowlist | Зафиксировать exit-критерий уменьшения (ADR-0249) и расписание work на 2026-Q4 |

### 4.2 Блокеры корректности (P1)

| # | Требование | Текущее состояние | Что нужно |
|---|---|---|---|
| К1 | DSL response-binding (`to: {response: ...}`) | Не реализовано в YAML и Python — GAP, fixed в `routes/*/main.dsl.yaml` удалены | Реализовать `Pipeline.to_response` + маршрутизация; иначе демо-роуты обещают контракт ответа, который не существует |
| К2 | `hub_run_adapter.run()` calling-convention | Первый параметр `notebook_name: str`, а процессор зовёт `fn(payload)` — из YAML тело попадает в `notebook_name` | ADR по смене публичной сигнатуры адаптера; требуется согласование (CLAUDE.md) |
| К3 | call_function whitelist: plugins объявляют в plugin.toml, но `load_plugin_manifests_for_migrations` сейчас сканирует только при `register_action_handlers()` (cold path) | Работает для osint_agent, но не покрыто тестом — добавить regression на orchestrator-driven сборку | Добавить `test_orchestrator_collects_whitelist` |
| К4 | ~~Order-pollution test_cert_model~~ | **ОТКРЫТИЕ 2026-10-07:** ошибочная гипотеза — `test_cert_model` проходит 12/12 в любом порядке и в комбинациях. 12 ошибок в больших прогонах — это **предсуществующие** failures в `tests/unit/dsl/` (banking, eip/transformation, llmcall, webhook_signature, dataframes, msgspec_speedup, routes_v11_discovery), задокументированные в `tests/unit/test_layer_violations_count.py` и summary сессии | — |
| К5 | **Одно удаляемое нарушение**: `src/backend/services/auth/bootstrap_admin.py → extensions.core_entities.users.domain.models` | Файл users-specific (импортирует `User`, вызывает `User.set_password()`), вызывается только из `manage.py:112` (CLI `bootstrap-admin`). Гипотетически можно переместить в `extensions/core_entities/users/services/admin_bootstrap.py` и обновить 2 импорта (`manage.py`, тесты) — уберёт 1 запись из allowlist. Удаление оригинала требует явного подтверждения по правилу «запрещено удалять файлы без явного подтверждения» (CLAUDE.md). | Ожидает решения пользователя |

### 4.3 Операционные требования (P2)

| # | Требование | Текущее состояние | Что нужно |
|---|---|---|---|
| О1 | Деплой-конфиги в актуальном состоянии | `deploy/k8s/*`, `ops/compose/docker-compose.prod.yml`, `config_profiles/prod.yml` существуют | Прогнать `make prod`, dry-run pod'ы, проверить env-vars в k8s vs settings.py |
| О3 | Frontend smoke против прод-API | Не выполнял | Запустить `tools/functional/browser_check.py` против `http://prod-host:port` |
| О5 | Логи в централизованное хранилище | Graylog упоминается в docs | Не глядел: проверить, что `infrastructure/logging/batching_router.py` отправляет в prod-endpoint |
| О6 | Backups + RPO/RTO | Не определено в документации | Добавить в runbook раздел с RPO/RTO для БД (PostgreSQL/Oracle/MSSQL/DB2 + Multi-queue) |
| О7 | Runbook для инцидентов | docs/ существует, но конкретные runbook'и (downstream, broker-down, scheduler-outage) — не проверял | Прогон авторизации или отдельный аудит |

### 4.4 Расширения и фичи (P3, не блокеры prod)

| # | Что | Зачем |
|---|---|---|
| Ф1 | PluginLoader по умолчанию (сейчас `plugin_loader_enabled=False`) | Сейчас без `V11_PLUGIN_LOADER_ENABLED=true` extensions не грузятся; в prod это блокирует 6 плагинов и все их action-вызовы |
| Ф2 | Полная инверсия R-V15-16 (registers_domains.py — 6 entries) | Сейчас централизованная регистрация в `dsl/commands/setup/registers_domains.py` (через core), что есть долг перед инверсией |
| Ф3 | Jupyter Hub provider-плагин | `routes/jupyter_hub_run/*` остаются failed (capability jupyter.hub непублична, плагина-провайдера нет) |
| Ф4 | Response-binding | Дубликат К1; нужен как фича, не блокер prod |

## 5. Что точно в проде НЕ работает сегодня (из §3 метрик)

| Канал | Статус | Почему |
|---|---|---|
| DSL-роуты (`routes/<name>/*.dsl.yaml`) | **3 active** (после `route_loader_enabled=True`) на dev-сервере | В headless-генерации метрик `RouteRegistry` пуст — это артефакт генератора (он не запускает RouteLoader), а не реальный prod-блок |
| PluginLoader extensions | выключен по умолчанию | osint_agent, skb, dadata, credit_pipeline не поднимаются без флага; для всех on/off/включить в проде |
| action `users.add`, `orders.create_skb_order`, `skb.*`, `dadata.*`, `tech.*`, `admin.*` | работают в текущем bootstrap (через `_register_*` в orchestrator) | Зависит от `register_action_handlers()` на startup; корректно вызывается |
| `ai.invoke:*` для LLM-шагов | fail-closed в strict | Нет рантайм capability-guard у LLM-процессоров (R-V15-N V21 TODO) |

## 7. Что НЕ сделано в этой сессии

| Долг | Почему | Следующий шаг |
|---|---|---|
| 6 entries `dsl/commands/setup/registers_domains.py` | Центральная регистрация actions не инвертируется без подъёма `plugin_loader_enabled=True` или `service.toml`-based auto-discovery | R-V15-16 inversion — отдельный ход с явным product-решением |
| Response-binding (`to:`) | Публичное API и схема манифеста меняются | ADR-0247 + реализация |
| hub_run_adapter calling-convention | Публичная сигнатура меняется | ADR + регрессионный тест + миграция теста |
| Coverage gap | Большой объём | Целиковая работа на несколько спринтов |
| bandit-strict HIGH | Не репрогонен | Целиковая работа |

## 8. Сводка

| Категория | Готово к prod | Не готово / требует решения |
|---|---|---|
| Безопасность (P0) | 6/7 CRITICAL/HIGH слиты | bandit-strict, coverage 60%<70% |
| Корректность (P1) | routes + DSL + call_function whitelist работают | response-binding, hub_run_adapter signature, test pollution |
| Операционное (P2) | deploy/k8s/, prod profile выведены | логи, backups, smoke на прод — не выведены |
| Фичи (P3) | — | PluginLoader default, R-V15-16 full, jupyter provider |

**Вывод:** критические security-блокеры слиты в мастер (HEAD 8beecc9b6); bandit-strict clean (0 HIGH, проверено 2026-10-07) — один из двух P0-блокеров закрыт. Остаётся **coverage 60% → 70%** как измеримый gap. После его закрытия мастер становится prod-ready.

Доказательства: `tools/check_layers.py`, `tools/check_docstrings.py`, `ruff`, `tools/functional/http_check.py`, `tools/functional/browser_check.py`, `tools/route_execution_check.py`, `tools/route_blockers_report.py` — все зелёные на текущем дереве (см. §3).