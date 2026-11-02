# ADR-0409 — Multi-tenant снапшот (fail-closed tenant-скоуп) и честные агенты credit_pipeline (волна 22, кластер B5)

* Статус: Accepted (2026-11-02, волна 22, кластер B5 — межtenant-снапшот и e2b-sandbox/риск-агенты)
* Cycle: 22 (волна 22)
* Связан с:
  - ADR-0400 (tenant-скоуп snapshot'а через `set_config('app.tenant_id', …)`),
  - ADR-0393 (BYPASSRLS-роль для служебных соединений — не выдана),
  - ADR-0403 (activity-имена workflow расширений; build-time резолв `collect_activities(validate=True)`),
  - ADR-0207 (core-фасад `MultiAgentSupervisor`/`AgentSpec`),
  - ADR-0398 (build-time резолв activity в workflow-компиляторе),
  - ADR-042 (слой-правило `extensions → core`, формат `plugin.toml`)
* Затрагивает:
  - `src/backend/infrastructure/resilience/snapshot_job.py`,
  - `extensions/credit_pipeline/sandbox.py` (новый),
  - `extensions/credit_pipeline/supervisor.py` (новый),
  - `extensions/credit_pipeline/plugin.py`, `extensions/credit_pipeline/plugin.toml`,
  - `extensions/credit_pipeline/workflows/*.workflow.yaml`,
  - `tests/unit/infrastructure/resilience/test_snapshot_job.py`,
  - `tests/unit/extensions/credit_pipeline/test_workflow_consistency.py` (новый),
  - `tests/unit/extensions/credit_pipeline/test_sandbox_supervisor_actions.py` (новый)

---

## Контекст

Две порученные owner-задачи, обе — про «честность» поведения.

**1. Межtenant-снапшот.** После ADR-0400 snapshot перед выборкой выставляет
`set_config('app.tenant_id', …, true)`. Это корректно ровно для **одного**
tenant'а. При отсутствии tenant-контекста `_resolve_snapshot_tenant()`
подставлял системный tenant (`_system`) и писал WARNING в лог. Под RLS это
даёт **0 строк по всем таблицам без ошибки** — тихая потеря fallback'а
`db_main` (`database_chain.py::_sqlite_ro_query` отдаёт пустой/stale-снимок).
Второй тихий дефект того же класса: `run_snapshot_now()` при отсутствии
скоупа всё равно открывал SQLite-транзакцию и выполнял `DELETE FROM tbl` —
то есть **затирал** ранее валидный снимок пустым.

Межtenant-режим нельзя получить и обходным путём: перечислить tenant'ы
нечем — реестра tenant'ов в БД нет (`tenants`-таблицы не существует), а
`SELECT DISTINCT tenant_id` под RLS отдаёт только текущий tenant. Служебная
роль с `BYPASSRLS` — эксплуатационное решение владельца БД (ADR-0393), её
нет ни в конфигурации, ни в репозитории.

**2. e2b-sandbox и риск-агенты в `extensions/credit_pipeline`.**
`code_interpreter_loop.workflow.yaml` прямо признавал: «e2b-sandbox в
расширении не реализован — исполнение делегировано», а шаг исполнения кода
подменял обычным LLM-вызовом `ai.run_agent` (код не исполнялся никогда).
`multi_agent_supervisor.workflow.yaml` описывал «3 specialist agents
(risk / compliance / scoring)», которых в расширении нет: ни risk-, ни
compliance-агента, а «supervisor-диспетчеризация» была тем же LLM-вызовом
`ai.run_agent`. Реальные агенты расширения — `scoring_agent`,
`document_parser_agent`, `decision_agent` — при этом не использовались в
качестве диспетчеризуемых.

Попутно найдено (тем же классом «тихой неправды»):

* `decision_agent` получал на вход результат `normalize:apply_rules`, а не
  вывод `scoring_agent` → `credit_score` = 0 → **кредит отклонялся всегда**;
* `apply_rules`/`fetch_result` получали payload, обёрнутый в `body`/`responses`,
  хотя `call_function` вызывает цель как `fn(payload)` — цели читали ключи
  верхнего уровня и молча теряли данные (или падали по `KeyError`).

---

## Решение

### 1. Снапшот: контракт «один tenant» + fail-closed

* **Контракт зафиксирован:** снапшот покрывает ровно один `tenant_id`;
  межtenant-режима нет. Это записано в docstring модуля
  (`snapshot_job.py`) и в этом ADR.
* **Скоуп обязателен:** `_resolve_snapshot_tenant(explicit_tenant_id)`
  выбирает «явный аргумент → tenant-контекст процесса». Системный tenant
  больше **не подставляется**: его отсутствие означает
  `SnapshotTenantScopeError` (новое исключение модуля) с понятным текстом
  и указанием на ADR-0409/ADR-0393.
* **Fail-closed до записи:** скоуп определяется **до** создания SQLite-движка
  и до `metadata.create_all` → при отказе файл снимка не трогается
  (прежний валидный снимок остаётся валидным), а `snapshot_sync_errors_total`
  инкрементируется, ошибка логируется на уровне ERROR.
* **API:** `sync_pg_to_sqlite(..., *, tenant_id=None)`,
  `run_snapshot_now(tenant_id=None)`, `register_snapshot_job(scheduler,
  tenant_id=None)` — job можно привязать к tenant'у явно (APScheduler
  получает `kwargs={"tenant_id": …}`); без привязки регистрация пишет
  WARNING о fail-closed поведении каждого запуска.
* **Видимость пустого снимка:** если суммарно 0 строк по всем таблицам —
  WARNING с указанием tenant'а (раньше «0 строк» было видно только на
  уровне INFO построчно).
* **Путь к межtenant-снапшоту** (вне зоны, требует владельца): служебная
  роль с `BYPASSRLS` + отдельный DSN для snapshot-job'а (ADR-0393) либо
  per-tenant job'ы с явным `tenant_id` и раздельными файлами снимка.

### 2. credit_pipeline: реальные реализации вместо фиктивных шагов

* **`extensions/credit_pipeline/sandbox.py`** (новый) — честный
  sandbox-исполнитель поверх core-контракта
  `src.backend/core/ai/sandbox.py::CodeSandbox`:
  `execute_code(payload)` исполняет код (E2B при `E2B_API_KEY` + extra
  `[ai]`, иначе `NoOpSandbox`, который **явно отказывает** — без
  `subprocess`-fallback, V15 R-V15-4); `evaluate_result(payload)` даёт
  вердикт «нужна ли итерация». Расширение импортирует только
  `src.backend.core.*` — слой-правило `extensions → core` (ADR-042).
* **`extensions/credit_pipeline/supervisor.py`** (новый) — честная
  диспетчеризация поверх core-супервизора
  `src.backend/core.ai.multi_agent::MultiAgentSupervisor` с **реальными**
  агентами расширения (`scoring_agent`, `document_parser_agent`), а не со
  stub-агентами ядра (`services/ai/multi_agent/supervisor.py::_build_credit_pipeline_agents`).
  Возвращает плоский словарь (`credit_score`, `risk_class`, `scoring`,
  `document`), пригодный для ссылок `${{ steps.N.field }}`.
* **Регистрация:** plugin регистрирует 5 actions
  (`credit_pipeline.{score,parse,decide,execute_code,supervise}`) —
  `provides.actions` в `plugin.toml` синхронизирован; модули расширения
  объявлены в `call_function_modules` (whitelist DSL-шага `call_function`).
* **Workflow-декларации** приведены к реальности:
  - `code_interpreter_loop` — исполнение кода идёт через
    `sandbox:execute_code` (не `ai.run_agent`), оценка — через
    `sandbox:evaluate_result`;
  - `multi_agent_supervisor` — диспетчеризация идёт через
    `supervisor:supervise`, а `decision_agent` получает **реальный** вывод
    `scoring_agent`;
  - `credit_assessment` / `rag_augmented_saga` — payload стал плоским
    (без вложенных `body`/`responses`), убран фиктивный «nbki»-дубль
    SKB-запроса, в `rag_augmented_saga` добавлен реальный шаг скоринга
    перед решением.

### 3. Инварианты, зафиксированные тестами

* снапшот: tenant-скоуп обязателен; отказ без скоупа не трогает файл
  снимка и не пишет «пустой» результат; пустой снимок виден в логах;
* credit_pipeline: `collect_activities(validate=True)` проходит для всех
  workflow расширения; каждый шаг ссылается на существующую цель
  (зарегистрированный action ядра либо module-level callable); module:fn-цели
  принимают ровно один позиционный аргумент (payload); args module:fn-шага —
  сам payload (плоский контракт); `decision_agent` получает вывод
  `scoring_agent`; вымышленные activity-имена не возвращаются.

---

## Альтернативы (отклонённые)

1. **Проход по тенантам с per-tenant `SET` (без `BYPASSRLS`).** Отклонено:
   перечислить tenant'ы нечем — реестра tenant'ов нет, а под RLS
   `SELECT DISTINCT tenant_id` виден только для текущего tenant'а.
   Реализация потребовала бы нового источника tenant'ов (владелец БД).
2. **Оставить fallback на системный tenant + WARNING.** Отклонено: это и есть
   «тихий 0 строк» — источник задачи.
3. **Роль с `BYPASSRLS` в ядре.** Отклонено: выдача роли и DSN —
   эксплуатационное решение владельца БД (ADR-0393); ядро не может выдать
   себе права.
4. **Оставить `ai.run_agent` как «sandbox» и «supervisor».** Отклонено:
   LLM-вызов не исполняет код и не диспетчеризирует агентов — это
   вводит в заблуждение и ревьюера, и оператора.
5. **Завести в расширении stub-агентов `risk_agent`/`compliance_agent`.**
   Отклонено: запрещено условием задачи («только честная реализация без
   заглушек»); роль risk закрывает реальный `scoring_agent`, роль разбора
   документов — `document_parser_agent`, отдельные compliance/risk-агенты —
   owner-задача.
6. **Реализовать подстановку `${{ … }}` между шагами в workflow-компиляторе.**
   Отклонено как выход за зону кластера (`src/backend/dsl/workflow/**` не
   входит в B5). Зафиксировано owner-задачей (см. «Последствия»).
7. **Вывести workflow расширения из исполняемых (делегировать внешнему
   оркестратору).** Отклонено: после реализации пунктов 2 и 3 все шаги
   ссылаются на реальные цели, а объявление «делегировано» без единого
   реального target'а оставило бы расширение без AI-поверхности вовсе.
   Ограничение (отсутствие подстановки между шагами) зафиксировано в
   заголовках YAML-деклараций.

---

## Последствия

* **Позитивные:**
  - «тихий 0 строк» в снимке устранён: нет скоупа → явная ошибка, файл
    снимка не затирается, пустой снимок виден в логах;
  - у расширения появились реальные (не заглушечные) реализации sandbox'а и
    supervisor'а на core-контрактах, без новых межслойных импортов;
  - workflow расширения больше не содержат вымышленных activity-имён и не
    «отклоняют кредит всегда» из-за неверной передачи данных;
  - инварианты зафиксированы тестами (build-time резолв + консистентность).
* **Ограничения / вне зоны (требует владельца):**
  - **Межtenant-снапшот** не реализован: нужна служебная роль с `BYPASSRLS`
    и отдельный DSN для snapshot-job'а (ADR-0393) либо per-tenant job'ы с
    раздельными файлами снимка;
  - **потребитель снимка** (`infrastructure/resilience/components/database_chain.py`,
    вне зоны кластера) не проверяет, что снимок принадлежит текущему
    tenant'у: при tenant-скоупном снимке fallback отдаст данные своего
    tenant'а другому tenant'у. Требуется guard на стороне потребителя;
  - **подстановка `${{ … }}` между шагами workflow** не реализована в ядре
    (`src/backend/dsl/workflow/compiler/step_compilers/activity.py`):
    аргументы шага уходят в activity буквально. До реализации потоки
    исполняются внешним оркестратором, подставляющим значения; это же
    относится к шагам с core-actions (`_workflow_input` попадает в kwargs
    сервис-метода и ломает вызов). Owner-задача;
  - **выделенные risk/compliance-агенты** в расширении не реализованы
    (ADR-0403 §Открытое) — роли закрыты реальными агентами;
  - **ledger-операции** кредитного конвейера (fund/refund) не реализованы —
    saga использует пару `webhook.schedule`/`webhook.cancel` ядра;
  - `docs/adr/INDEX.md` не обновлялся (по условию задачи) — индекс
    генерируется скриптом `tools/generate_adr_index.py`.

---

## Проверка

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/resilience/test_snapshot_job.py \
  tests/unit/extensions/credit_pipeline/ \
  extensions/credit_pipeline/tests/ -q

.venv/bin/python tools/config_audit.py --scope orphans
.venv/bin/python tools/check_layers.py --strict
.venv/bin/python tools/checks/mypy_budget.py
.venv/bin/python tools/generate_adr_index.py --check
```

---

## Связи

* [ADR-0400](../adr/0400-snapshot-rls-graphql-hot-reload-and-bls-gate.md) —
  tenant-скоуп snapshot'а (источник «тихого 0 строк»).
* [ADR-0403](../adr/0403-workflow-sla-dlq-and-prod-validator.md) —
  activity-имена workflow расширений (предыдущая волна правок).
* [ADR-0393](../adr/0393-db-capability-gate-and-rpa-authorization.md) —
  BYPASSRLS-роль для служебных соединений (owner-задача).
* [ADR-0207](../adr/0207-sprint-120-closure.md) — core-фасад
  `MultiAgentSupervisor` (`src/backend/core/ai/multi_agent.py`).
* [ADR-0078](../adr/0078-plugin-toml-capability-syntax.md) — синтаксис
  `plugin.toml` (`[[capabilities]]`, `provides.actions`); общий формат
  манифеста — ADR-042.
