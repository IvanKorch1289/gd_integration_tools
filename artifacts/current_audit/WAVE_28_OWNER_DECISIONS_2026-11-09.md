# Волна 28 (2026-11-09) — решения владельца: capability-контур, идемпотентность, портальные эндпоинты

Владелец согласовал все восемь рекомендаций (A/B/C/D → A). Реализовано
кодом; решения 2 и 7 зафиксированы без кода.

| # | Решение | ADR | Статус |
|---|---|---|---|
| 1 | Caller-aware namespace для capability-проверок | ADR-0430 | ✅ код |
| 2 | SQL-консоль `POST /api/v1/admin/sql/query` не поднимается | — | ✅ зафиксировано (панель выключена) |
| 3 | Из 7 отсутствующих эндпоинтов портала подняты живые capability | ADR-0432 | ✅ код |
| 4 | Capability-декларации обязательны + CI-гейт (рэтчет) | ADR-0430 | ✅ код |
| 5 | Ключ идемпотентности → заголовок внешнего вызова | ADR-0431 | ✅ код |
| 6 | Компенсация откатывает только выполненные шаги | ADR-0431 | ✅ код |
| 7 | Инфраструктурные долги — пакет «инфра-решения» | — | ⚙️ кодом не закрывается |
| 8 | Волна 28 = «стойкость» | ADR-0431 | ✅ код |

## 1. Caller-aware capability (ADR-0430)

* `core/security/capabilities/caller.py` — ContextVar namespace'а вызывающего.
* DSL-движок привязывает `route_id` **только если** у роута есть декларации
  (`CapabilityGate.has_plugin`) → иначе проверка идёт под платформенным
  namespace'ом (регрессия не ломает существующие роуты).
* Фасады `StorageFacade`/`UnifiedCacheFacade`/`ExternalDatabaseFacade` и
  `OutboundHttpClient` проверяют capability под namespace'ом вызывающего.
* Гейт `tools/check_route_capabilities.py` (+ шаг в `lint.yml`): роут обязан
  объявлять `net.inbound`, плагин — хотя бы одну capability; легаси-манифесты
  в `.security/route-capabilities-baseline.txt` (8 записей, рэтчет).
* Тесты: `tests/unit/core/security/capabilities/test_caller_namespace_adr0430.py`
  (10), `tests/unit/tools/test_check_route_capabilities.py` (4).

## 2. Идемпотентность и компенсация (ADR-0431)

* Ключ шага вынесен в `pg_runner_internals/step_keys.py`; executor кладёт его в
  свойства Exchange'а (не в payload — контракт action'ов не ломается).
* `http_call` пробрасывает `Idempotency-Key` получателю.
* Компенсация в pg-runner считает индекс по **выполненным** шагам — как в
  Temporal-пути (было: по всем forward-шагам → разные откаты при частичном
  падении).

## 3. Портальные эндпоинты (ADR-0432)

* `GET /api/v1/admin/guardrails-metrics`,
  `POST /api/v1/admin/guardrails-metrics/{tenant_id}/false-positive` —
  DI-провайдер + наполнение из AI-шлюза (`gateway_audit_mixin`).
* `GET /api/v1/webhooks/scheduled`, `POST /api/v1/webhook/schedule` —
  DI-провайдер `WebhookScheduler` + SSRF-guard `assert_safe_url`.
* Страницы портала 47 и 67 переведены на живые пути; гейт контракта путей
  (ADR-0425) подтверждает их существование.

## 4. Что осталось (owner-задачи)

* `OWNER_TASKS.md` §15: prompt-versions (нужны методы `PromptRegistry`),
  storage list/get/download по ключу, pools-snapshot, processes/queues.
* `OWNER_TASKS.md` §16: линтер `*.workflow.yaml`, `workflow_setup.py` глотает
  ошибку загрузки, `bulkhead`/`CB` не подключены к DSL-процессорам, `core/api`
  не экспортирует примитивы устойчивости, cookbook «как написать workflow YAML»,
  дубли `lint.py`/`dry_run.py`, регистрация `memory.reflect` и
  `workflow.checkpoint.put`.
* `OWNER_TASKS.md` §17 (решения владельца) — п. 7: инфраструктурные долги
  (`.env:92`, образ от 18.08, Prometheus-правила SLA, `audit.write` в роутах,
  JWKS RS256, service-DNS, OpenWebUI, replica DSN, BYPASSRLS, `jupyter.hub`).

## 5. Проверки

| Гейт | Результат |
|---|---|
| `tests/unit` (волна 28, полный) | см. `.run/wave13-logs/reg_final_28.txt` |
| ruff `src/` | All checks passed |
| mypy-бюджет | 16 ошибок при бюджете 30 |
| `check_layers.py --strict` | 41 (прежний долг, без регресса) |
| `check_docstrings.py src --max-allowed 0` | 0 missing |
| `check_route_capabilities.py` | OK (8 легаси в baseline) |
| гейт контракта путей портала | 6 passed |
