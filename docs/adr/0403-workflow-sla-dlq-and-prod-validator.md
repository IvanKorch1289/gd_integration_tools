# ADR-0403 — Workflow-SLA/DLQ: удаление мёртвого трекера, честная фиксация DLQ, прод-валидатор JWT/AI-fallback (волна 21, кластер A2)

* Статус: Accepted (2026-10-30, волна 21, кластер A2 — workflow-долг, owner-задачи, прод-валидатор)
* Cycle: 180 (волна 21)
* Связан с:
  - ADR-0396 (компенсации и бюджет времени workflow; источник преувеличения про SLA),
  - ADR-0398 (build-time резолв activity — `collect_activities(validate=True)`),
  - ADR-0400 (профильный гейт интроспекции GraphQL — образец проверки в `profile_merge.py`),
  - ADR-0373 (env-секреты: правило «в `.env` только секреты» и гейт `missing-secret`),
  - ADR-0371 (прод-значения, оставленные осознанно: HS256, `open_webui` вне fallback-цепочки)
* Затрагивает:
  - `src/backend/services/workflows/sla_alerting.py`,
  - `src/backend/services/workflows/facade.py`,
  - `src/backend/infrastructure/workflow/pg_runner_backend.py`,
  - `src/backend/core/config/validator/profile_merge.py`,
  - `tools/config_audit.py`, `.security/config-audit-missing-secret-allowlist.txt`,
  - `extensions/credit_pipeline/workflows/*.workflow.yaml`,
  - `docs/workflows/index.md`, `docs/runbooks/dlq-replay.md`, `docs/runbooks/hitl-stuck-workflow.md`

---

## Контекст

Кластер A2 закрывал пять технических открытых задач по вехам (волна 20 →
21). Исходное состояние и его фактическая проверка:

1. **`SlaTracker` мёртв.** Класс `SlaTracker`
   (`src/backend/services/workflows/sla_alerting.py`) не инстанцировался
   **нигде** в `src/`: ни в `lifespan`, ни в worker'ах, ни в composition
   root. `WorkflowFacade` принимал `sla_tracker` опциональным параметром, а
   сам фасад в `src/` не создаётся. ADR-0396 утверждал, что «SLA-политика
   перестала быть инертной» — трекинга SLA в рантайме не было; эскалация
   (email/Slack) не работала.
2. **Workflow-DLQ.** `PgRunnerWorkflowBackend.replay()`
   (`pg_runner_backend.py:250`) всегда бросает `NotImplementedError`. В
   документации это читалось как «нереализованный DLQ для workflow».
   Фактически `replay()` — Temporal-совместимый **replay-gate**
   (детерминизм history), а не очередь недоставленных сообщений.
3. **Activity-имена `extensions/credit_pipeline` не резолвятся.** 15 имён
   (`receive_dataset`, `llm_propose_code`, `execute_code_sandboxed`,
   `evaluate_results`, `format_final_report`, `collect_loan_inputs`,
   `supervisor_dispatch`, `risk_agent`, `compliance_agent`, `scoring_agent`,
   `consolidate_results`, `final_decision`, `fetch_credit_data`,
   `rag_query_legal_policies`, `llm_credit_decision`) отсутствуют и в
   action-реестре ядра, и среди `module:fn`-ссылок расширения. ADR-0398
   включил build-time резолв (`collect_activities(declarations,
   validate=True)`) → Worker Temporal падал на старте со списком неизвестных
   имён (auto-load подхватывает `extensions/*/workflows/*.workflow.yaml`).
4. **Baseline `missing-secret`.** `tools/config_audit.py` умел блокировать
   класс `missing-secret`, но долг по нему не был зафиксирован явно:
   allowlist общий для всех видов расхождений и без обязательных
   обоснований. Проверка фактического состояния: долг по классу = **0**
   (все 51 секретное поле Settings-классов документированы в
   `.env.example`) — волна 18 закрыла прежние 64 записи.
5. **Прод-валидатор.** `manage.py validate-profile prod` не сверял
   `security.algorithm` с наличием секрета и не проверял
   `ai_providers.fallback_chain` на loopback-хосты.

---

## Решение

### 1. `SlaTracker` удалён как мёртвый код (owner-задача GAP-WF-4.5)

* Удалены: класс `SlaTracker`, протокол `SlaAlertDispatcher`, его
  in-memory реализация `InMemorySlaAlertDispatcher`, а также параметр
  `sla_tracker` и методы `_track_sla`/`_untrack_sla` в `WorkflowFacade`.
* Оставлена чистая функция оценки `evaluate_sla` (+ `SlaBreachRecord`,
  `SlaBreachLevel`): она эмитит метрику
  `workflow_sla_compliance_total{level}`, на которую завязан дашборд
  `infrastructure/observability/grafana/workflow_sla_compliance.json`.
  Удаление функции потребовало бы правки файлов вне зоны кластера
  (дашборд, feature-flag-документация).
* В `WorkflowFacade` сохранён `sla_resolver`: SLA hard-limit как бюджет
  времени (`execution_timeout`) — контракт ADR-0396, не требующий
  фонового исполнителя.
* Docstring'и `sla_alerting.py` и `facade.py` теперь прямо фиксируют:
  «SLA-алертинг **не реализован**», с идентификатором owner-задачи
  `GAP-WF-4.5`.

**Почему не «создать фасад в composition root и включить трекинг»:**
(а) composition root (`src/backend/plugins/composition/**`) и
production-путь старта workflow
(`src/backend/dsl/engine/processors/invoke_workflow.py`, который стартует
workflow напрямую через `WorkflowBackend`, минуя фасад) — **вне зоны
кластера**; (б) канала эскалации (email/Slack) в репозитории нет — был
только in-memory тест-дубль; (в) трекер без подписки на старт/завершение
workflow — фоновая задача, которая ничего не отслеживает (тихое
«зелёное» состояние). Поднять «настоящий» трекер можно только вместе с
подключением фасада к production-пути — это отдельная задача владельца
K3 DSL+Workflow (см. «Открытое»).

### 2. Workflow-DLQ: «не реализовано» — зафиксировано честно

* Реализация DLQ-поступления для исчерпавших попыток шагов **не
  выполнена**: точка решения о retry-бюджете находится в
  `infrastructure/workflow/runner.py` (вне зоны кластера), а «очереди
  недоставленных workflow-сообщений» в модели нет — `workflow_events` это
  append-only event log инстанса.
* В коде и документации зафиксировано фактическое поведение: retry-бюджет
  исчерпан → терминальный `WorkflowStatus.failed` + метрика
  `record_workflow_status` + текст ошибки в `workflow_instances.error` +
  компенсации выполненных forward-шагов (ADR-0396). Записи в DLQ и
  переигровки шага нет.
* `pg_runner_backend.py`: docstring модуля получил раздел «Workflow-DLQ»,
  `replay()` — разъяснение «это replay-gate, а не DLQ» в docstring'е и в
  тексте `NotImplementedError` (с ссылкой на ADR-0403).
* `docs/runbooks/dlq-replay.md` получил явный scope-marker: runbook
  относится к messaging-транспортам, workflow-шаги в этот DLQ не попадают.
  Формулировка волны 20 про messaging-DLQ не откатывается.
* `docs/workflows/index.md` — уточнён путь «исчерпание попыток → FAILED»
  и добавлена ссылка на owner-задачу.

### 3. `extensions/credit_pipeline`: activity-имена приведены к реальным targets

Изменены только имена (и payload-аргументы под контракт цели); порядок
шагов, `wait_signal` и saga-структура не менялись:

| Было (не существовало) | Стало (реальная цель) |
|---|---|
| `receive_dataset` | `extensions.credit_pipeline.services.clients.skb:fetch_result` |
| `llm_propose_code` | `ai.chat` |
| `execute_code_sandboxed` | `ai.run_agent` |
| `evaluate_results` | `extensions.credit_pipeline.functions.normalize:apply_rules` |
| `format_final_report` | `export.to_pdf` |
| `collect_loan_inputs` | `extensions.credit_pipeline.services.clients.skb:fetch_result` |
| `supervisor_dispatch` | `ai.run_agent` |
| `risk_agent` | `extensions.credit_pipeline.agents:scoring_agent` |
| `compliance_agent` | `extensions.credit_pipeline.agents:document_parser_agent` |
| `scoring_agent` | `extensions.credit_pipeline.agents:scoring_agent` |
| `consolidate_results` | `extensions.credit_pipeline.functions.normalize:apply_rules` |
| `final_decision` | `extensions.credit_pipeline.agents:decision_agent` |
| `fetch_credit_data` | `extensions.credit_pipeline.services.clients.skb:fetch_result` |
| `rag_query_legal_policies` | `rag.search` |
| `llm_credit_decision` | `extensions.credit_pipeline.agents:decision_agent` |
| `fund_account` (saga forward) | `webhook.schedule` |
| `refund_account` (saga compensate) | `webhook.cancel` |

Основание выбора целей: (а) `module:fn`-ссылки резолвятся на build-time
**без** action-реестра — plugin-registrations грузятся в фазе services
позже фазы infrastructure, где собирается activity-list Worker'а, поэтому
names вида `credit_pipeline.*` в YAML-декларациях использовать нельзя;
(б) saga-пара — единственная реальная пара «создать/отменить» в ядре
(ledger-операций в расширении нет).

Соответствие «старое имя → новая цель» зафиксировано в шапке каждого
YAML-файла; `extensions/credit_pipeline/workflows/README.md` обновлён
(утратившее «при запуске Temporal вернёт UnknownActivity — для S12 это
OK» удалено).

### 4. Явный allowlist класса `missing-secret`

* Новый файл `.security/config-audit-missing-secret-allowlist.txt` —
  отдельный baseline класса `missing-secret` с форматом
  `<kind>:<profile>:<group>:<name>  # owner=<team> | reason=<обоснование>`.
* `tools/config_audit.py`:
  - новая функция `load_justified_allowlist()` — запись действует **только**
    если в комментарии есть `owner=` и `reason=`; записи без них
    игнорируются и печатаются как «необоснованные» (гейт продолжает
    блокировать — сигнал не теряется);
  - новый CLI-флаг `--missing-secret-allowlist` (по умолчанию — новый
    файл) и поля в JSON-выводе (`missing_secret_allowlist`,
    `unjustified_allowlist_entries`).
* Текущий долг по классу — **0 записей**; файл существует как явный
  baseline и место для будущих обоснованных исключений (решение
  владельца безопасности).

### 5. Прод-валидатор: JWT-алгоритм и AI-fallback

В `src/backend/core/config/validator/profile_merge.py` добавлены две
проверки (по образцу ADR-0400):

* `security.jwt_symmetric_algorithm_without_secret` (CRITICAL) — в prod
  симметричный алгоритм (`HS*`) требует гарантированного источника
  секрета: `security.secret_key` в YAML, env `SEC_SECRET_KEY` или Vault
  (`vault.enabled` + `addr` + `secret_path`). Источники — из моделей и
  рантайм-контракта (`SecureSettings`, `VaultSettings`).
* `ai_providers.fallback_chain_localhost` (CRITICAL) — в prod
  fallback-цепочка AI не должна содержать провайдера с loopback-`base_url`
  (`localhost` / `127.0.0.1` / `::1` / `0.0.0.0`).

Значения политики **не менялись**: `security.algorithm` в prod остался
`HS256` (owner-задача ADR-0371: переход на RS256 требует keypair + JWKS),
`open_webui` остался исключённым из prod-цепочки. Валидатор только
сообщает.

---

## Альтернативы

* **Оставить `SlaTracker` и «поднять его позже».** Отклонено: мёртвый код
  с «зелёным» статусом — источник ложной уверенности (ADR-0396 уже
  преувеличил). Удаление + явный owner-идентификатор честнее.
* **Перевести `invoke_workflow` на фасад (настоящая интеграция).**
  Отклонено в этом кластере: ломающее изменение (все роуты должны
  объявить `workflow.start`), DSL-процессор вне зоны кластера, требует
  per-ADR решения по capability-матрице (OWNER_TASKS § 1).
* **Реализовать DLQ для исчерпавших попыток шагов.** Отклонено: точка
  решения вне зоны кластера, а модель workflow-DLQ требует нового
  контракта (что именно «переигровывать»). Зафиксировано как owner-задача.
* **Удалить YAML-декларации `credit_pipeline` целиком.** Отклонено: теряем
  полезные декларации; переименование на реальные targets сохраняет поток
  шагов и делает build-time резолв проходящим.
* **Оставить `evaluate_sla` мёртвой функцией / удалить её.** Оставлена:
  удаление требует правки дашборда и feature-flag-документации (вне зоны),
  а функция — точка входа для будущего исполнителя.

---

## Последствия

* Позиции `GAP-WF-4.5` (SLA-алертинг) закрыты **кодом** (мёртвый код
  удалён, состояние задокументировано) — владельцу остаётся решить, нужна
  ли функциональность и как её реализовывать.
* `docs/roadmap/OWNER_TASKS.md` (§ 7, § 8, § 10) описывает состояние до
  волны 21; обновление реестра — за владельцем roadmap (файл общий для
  кластеров волны).
* Дашборд `workflow_sla_compliance.json` и описание feature-флага в
  `core/config/features/ai_rag.py` продолжают ссылаться на метрику
  `workflow_sla_compliance_total`, которую сейчас никто не эмитит —
  обновление этих файлов вне зоны кластера.
* Новые CRITICAL-коды прод-валидатора не меняют текущий prod-профиль
  (`manage.py validate-profile prod` → 0 CRITICAL): секрет приходит из
  Vault, `open_webui` вне цепочки.

---

## Проверка

* `tests/unit/services/workflows/test_sla_alerting_removed_wave21.py` —
  удаление трекера/диспетчера, отсутствие `sla_tracker` у фасада, честные
  docstring'и (падало → зелёное).
* `tests/unit/infrastructure/workflow/test_pg_runner_backend_dlq_statement.py` —
  «replay — не DLQ», формулировки в коде и документах (падало → зелёное).
* `tests/unit/extensions/credit_pipeline/test_workflow_activities_resolve.py` —
  `collect_activities(validate=True)` для всех YAML-деклараций расширений
  + проверка `module:fn`-целей (падало → зелёное).
* `tests/unit/tools/test_config_audit_missing_secret_allowlist.py` —
  allowlist с обоснованиями; запись без `owner=` не снимает блокировку
  (падало → зелёное).
* `tests/unit/core/config/test_profile_prod_security_policy_gate.py` —
  две новые проверки прод-профиля (падало → зелёное).
* Гейты: `tools/config_audit.py --scope orphans` → 0; `--scope missing` → 0;
  `tools/check_layers.py --strict`; `tools/check_docstrings.py src
  --max-allowed 0`; `tools/checks/mypy_budget.py`; `ruff`.

---

## Открытое (owner-задачи)

1. **GAP-WF-4.5 — SLA-алертинг.** Реализовать исполнителя (реальный
   dispatcher + подписка на старт/завершение workflow) **или** удалить
   `evaluate_sla` вместе с дашбордом `workflow_sla_compliance.json`.
   Владелец: K3 DSL+Workflow.
2. **Workflow-DLQ.** Если нужен DLQ для исчерпавших попыток шагов —
   определить контракт (что переигровывается, где хранится, кто
   разбирает) и реализовать в `infrastructure/workflow/runner.py`.
   Владелец: K3 DSL+Workflow + K2 (messaging).
3. **Подключение `WorkflowFacade` к production-пути** (иначе capability-гейт
   и audit-emit фасада не работают). Владелец: K3 DSL+Workflow, требует
   per-ADR решения по capability-матрице.
4. **`extensions/credit_pipeline`:** e2b-sandbox (code-interpreter),
   выделенные risk/compliance-агенты, ledger-операции (fund/refund).
   Владелец: расширение `credit_pipeline`.
5. **Реестр owner-задач** (`docs/roadmap/OWNER_TASKS.md` § 7/§ 8/§ 10) —
   привести в соответствие с волной 21.

---

## Связи

* ADR-0396 — workflow-компенсации и бюджет времени (источник
  преувеличения про SLA).
* ADR-0398 — DSL workflow: activity-резолв, sensor, BPMN gateway.
* ADR-0400 — snapshot/RLS/GraphQL/hot-reload: образец профильного гейта.
* ADR-0373 — env-секреты: правило «в `.env` только секреты» и гейт
  `missing-secret`.
* ADR-0371 — прод-значения, оставленные осознанно (HS256, `open_webui`).
* `docs/roadmap/OWNER_TASKS.md` § 7 (DLQ), § 8 (`SlaTracker`), § 10
  (activity-имена `credit_pipeline`).
* `docs/roadmap/PROD_READINESS_GAPS.md` — GAP-WF-4.5.
* `docs/workflows/index.md` § «Не реализовано», `docs/runbooks/dlq-replay.md`,
  `docs/runbooks/hitl-stuck-workflow.md`.
