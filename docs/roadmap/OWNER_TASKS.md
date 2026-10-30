# OWNER_TASKS — Известные ограничения и owner-задачи (волна 20)

> Реестр позиций, которые **нельзя закрыть в кластере** без решения
> владельца: внешние зависимости, эксплуатационные решения, сознательно
> отложенные миграции. Каждая позиция: что именно не сделано, почему,
> минимальный шаг, критерий приёмки.
>
> Источник правды по wave-20 решениям — `docs/adr/` (ADR-0398…ADR-0401).
> Реестр прод-готовности — [PROD_READINESS_GAPS.md](PROD_READINESS_GAPS.md).

## Как читать

| Пометка | Значение |
|---|---|
| **требует владельца** | Нужен выбор/решение человека: внешний пин, инфраструктура, эксплуатация, миграция данных. Кодом не закрывается. |
| ⚙️ инженерно | Закрывается кодом в следующей волне, владелец не нужен. |

Все позиции ниже — **требует владельца**, если не указано иное.

---

## 1. Миграция `route.toml` под новый namespace capability

* **Что не сделано.** Часть роутов объявляет capability в старой плоской
  форме (`capabilities = ["net.outbound", "audit.write"]`), а новая форма —
  табличная (`[[route.capabilities]]` с `name` + `scope`). Миграция не
  выполнена: в репозитории сосуществуют обе формы (например
  `routes/hello_route/route.toml` — плоская, `routes/composition_demo/route.toml`
  — табличная).
* **Почему.** Runtime-резолвер namespace (ADR-0366) берёт namespace =
  `route_id` роута; core-baseline (`dsl_capability_core_baseline_enabled`)
  закрывает только fallback-namespace `"core"`. Пока роуты не объявляют
  capability в новой форме, откат на baseline остаётся единственным путём
  для части capability — это осознанная политика least privilege, но её
  нельзя закрыть волной, не изменив контракт декларации.
* **Требует владельца.** Да — изменение семантики авторизации оформляется
  отдельным ADR (governance-правило **ADR-0284 §1.1**: изменения ALLOWED-матрицы
  и семантики авторизации требуют per-ADR approval). Список роутов под
  миграцию и целевой namespace — решение владельца авторизации.
* **Минимальный шаг.** ADR + миграция `routes/*/route.toml` на табличную
  форму, затем выключение `dsl_capability_core_baseline_enabled` в
  `config_profiles/prod.yml` (сейчас `false` — см.
  [ADR-0393](../adr/0393-db-capability-gate-and-rpa-authorization.md)).
* **Done-критерий.** `routes/*/route.toml` используют только табличную
  форму; `dsl_capability_core_baseline_enabled: false` в prod; гейт
  `tools/check_layers.py --strict` без новых нарушений.

## 2. Lock-чанж: Pillow 13 и `psycopg[binary]` → extra `db_drivers`

* **Что не сделано.** (а) Пин `pillow>=12.3.0,<13.0.0` удерживается в трёх
  местах `pyproject.toml` (`rpa`, `rpa-windows`, `multimodal-rag`).
  (б) `psycopg[binary]>=3.1,<4.0.0` объявлен в extra `sources-cdc`, а не в
  `db_drivers`, где соседствуют остальные драйверы БД (`oracledb`, `aioodbc`,
  `aiomysql`, `clickhouse-connect`, `pyodbc`).
* **Почему.** (а) `streamlit` (core-зависимость) требует `pillow<13` — снятие
  пина делает lock-файл неразрешимым; 59 CVE Pillow 12.x приняты осознанно
  (ADR-0385 A5, ADR-0388). (б) перенос затрагивает lock-файл, а lock-файл в
  волне 20 не менялся.
* **Требует владельца.** Да — владелец зависимостей: без обновления
  `streamlit` (или снятия пина с явным принятием CVE) и без решения по
  `uv.lock` пункт не закрывается. Lock-чанж — **вне зоны** кластера
  документации.
* **Минимальный шаг.** (а) обновить `streamlit` до версии, допускающей
  `pillow>=13`, снять пин в трёх местах, обновить lock. (б) перенести
  `psycopg[binary]` в extra `db_drivers`, обновить lock, прогнать
  `tools/check_dsn_drivers.py`.
* **Done-критерий.** `uv lock` без `pillow<13`; `psycopg` объявлен в
  `db_drivers`; `uv audit --frozen` не содержит Pillow; `tools/config_audit.py
  --scope orphans` → 0.

## 3. Прод-значения, оставленные осознанно

Все четыре позиции помечены в `config_profiles/prod.yml` как owner-задачи
(ADR-0371, ADR-0377) и требуют внешней инфраструктуры:

| Позиция | Текущее значение | Почему требует владельца | Минимальный шаг |
|---|---|---|---|
| **HS256** в проде | `security` — JWT подписывается HS256 (секрет из Vault) | Переход на RS256 требует RSA-keypair + JWKS/IdP; без этой инфраструктуры переключение ломает выпуск и проверку JWT | выдать keypair, настроить JWKS/IdP, переключить `algorithm` |
| **WAF `allow_hosts`** | в allowlist остаются `localhost` / `127.0.0.1` (sidecar'ы: clamd, otel) | Реальные хосты локальных sidecar'ов без инфраструктуры вывести нельзя | заменить на явные service-DNS имена |
| **open_webui** в fallback-цепочке AI | `open_webui` исключён из `ai_providers.fallback_chain` (в base — `http://localhost:3000`) | Реальный host OpenWebUI без инфраструктуры вывести нельзя; молчаливый откат на localhost в проде опаснее | задать продовый endpoint OpenWebUI и вернуть его в цепочку |
| **`replica_dsn`** | `database.replica_dsn: null` — read-replica выключен, весь трафик идёт на primary | Нужен реальный async-DSN реплики; YAML не поддерживает `${VAR:-default}` (ADR-0377) — значение задаётся литералом или env `DB_REPLICA_DSN` | выдать DSN реплики, задать `replica_dsn`/`DB_REPLICA_DSN`, включить `snapshot` в prod |

> **Требует владельца** — все четыре: эксплуатационные решения и внешняя
> инфраструктура.

## 4. Baseline `missing-secret` / `missing-non-secret`

* **Что не сделано.** Baseline `tools/config_audit_allowlist.txt` **пуст**
  (только комментарии). Scope `missing` (ADR-0373, ADR-0362) сейчас даёт
  0 расхождений на всех профилях — то есть весь прежний долг по
  недокументированным переменным закрыт.
* **Почему это owner-задача.** Пока allowlist пуст, гейт
  `--scope missing` блокирует **любую** новую недокументированную
  переменную окружения. Если владелец решит, что часть таких переменных
  допустимо держать вне `.env.example`, это осознанное исключение, которое
  должно быть зафиксировано в allowlist, а не возникать само.
* **Требует владельца.** Да — решение «документировать в `.env.example` или
  внести в baseline» принимает владелец безопасности.
* **Минимальный шаг.** Решить судьбу каждой недокументированной переменной;
  при «допустимо» — внести в `tools/config_audit_allowlist.txt` с
  `owner=<team>`.
* **Done-критерий.** `tools/config_audit.py --scope all` → 0 при пустом
  allowlist **или** allowlist непуст и каждая запись имеет owner.

## 5. `PolicyMixin.cache()` — шим с MRO-коллизией

* **Что не сделано.** `PolicyMixin.cache()` (`src/backend/dsl/builders/policy_mixin.py`)
  остаётся deprecated-шимом: из-за MRO-коллизии с `RouteBuilder.cache`
  (реальный cache через `CacheProcessor`) он выдаёт **silent no-op** —
  маркер `policy:cache` вместо кэша.
* **Почему.** Шим сохранён для backward-compat (ADR-0355) и должен быть
  удалён после cycle 175. Удаление — ломающее изменение публичного API
  билдеров.
* **Требует владельца.** Да — владелец DSL решает, когда и как удалять
  публичный метод.
* **Минимальный шаг.** Удалить `PolicyMixin.cache()` (оставив
  `cache_policy()`), прогнать миграцию вызовов в репозитории.
* **Done-критерий.** `PolicyMixin.cache` отсутствует; в коде нет вызовов
  `builder.cache(...)` в позиции policy-маркера.

## 6. Дубль OCR-процессора

* **Что не сделано.** OCR реализован дважды:
  `src/backend/services/rpa/ocr_processor.py` (протокол `OCRProcessor`,
  `PytesseractOCRProcessor`, `NoOpOCRProcessor`) и
  `src/backend/dsl/engine/processors/rpa/operations/imageocrprocessor.py`
  (`ImageOcrProcessor` — DSL-шаг `ocr`). ADR-0368 починил таймаут только в
  сервисной копии, ADR-0393 добавил предел ожидания в DSL-копии.
* **Почему.** Две реализации живут в разных слоях (services vs dsl) и
  различаются поведением при отсутствии Tesseract: сервисная отдаёт пустую
  строку через `NoOpOCRProcessor`, DSL-шаг — свой fallback.
* **Требует владельца.** Да — какая копия канон (и в каком слое) —
  архитектурное решение; слияние меняет поведение шага `ocr`.
* **Минимальный шаг.** Выбрать канон, свести вторую копию к общему
  протоколу (или удалить), обновить `feature_flags.rpa_ocr_enabled`.
* **Done-критерий.** В `src/` остаётся одна реализация OCR; оба
  потребителя используют её.

## 7. `pg_runner_backend.py:250` — `replay()` → `NotImplementedError`

* **Что не сделано.** `PgRunnerWorkflowBackend.replay()` (строка 250) всегда
  бросает `NotImplementedError`: pg-runner не реализует Temporal-совместимый
  replay (у него нет `WorkflowHistory.from_json`; состояние
  восстанавливается event-sourcing'ом из `workflow_events`). Метод помечен
  deprecated (Sprint 217), backend целиком deprecated.
* **Почему.** Требуется Temporal-кластер; в dev-профилях pg-runner —
  штатный движок.
* **Требует владельца.** Да — перевод прод-окружения на Temporal и
  окончательное удаление pg-runner'а — эксплуатационное решение.
* **Минимальный шаг.** Поднять Temporal в проде, перевести
  `workflow_backend` на `temporal`, удалить метод после Sprint 220.
* **Done-критерий.** `replay()` удалён; `pg_runner_backend.py` не
  используется в прод-профилях.

> **Формулировка про DLQ.** Runbook'а `docs/runbooks/dlq-replay.md` относится
> к **messaging** (Kafka/RabbitMQ/NATS/Inbox, admin-API `/api/v1/admin/dlq/*`,
> метрика `dlq_depth` по транспортам). Workflow в DLQ **не** попадает:
> `workflow_events` — это append-only event log инстанса, а не очередь
> недоставленных сообщений. У workflow нет собственного DLQ и нет replay'а
> сообщений; «DLQ-паттерн» в компенсациях — это WARNING-лог + audit-событие
> (`src/backend/infrastructure/workflow/compensating_driver.py`), то есть
> сигнал без потери данных, но **не** очередь для переигровки.

## 8. `SlaTracker` — SLA-алертинг не реализован

* **Что не сделано.** Класс `SlaTracker`
  (`src/backend/services/workflows/sla_alerting.py`) существует, но
  **не инстанцируется нигде в `src/`**: `WorkflowFacade` принимает
  `sla_tracker` только как опциональный параметр, а сам фасад в `src/` не
  создаётся. Email/Slack-эскалация по `soft_limit_seconds` /
  `hard_limit_seconds` в рантайме не работает.
* **Почему.** Фасад workflow-сервисов не собирается в composition root —
> это следствие неполной интеграции сервисного слоя.
* **Требует владельца.** Да — владелец K3 DSL+Workflow: создание фасада и
  подключение трекера — сервисная интеграция, не документация.
* **Минимальный шаг.** Зарегистрировать `WorkflowFacade` (+ `SlaTracker`)
  в composition root, либо удалить класс и опциональный параметр.
* **Done-критерий.** `SlaTracker` инстанцируется в composition root **или**
  класс удалён; в [runbook'е HITL](../runbooks/hitl-stuck-workflow.md)
  ссылка на неё соответствует коду.

> Идентификатор owner-задачи: **GAP-WF-4.5** (зафиксирован в
> [PROD_READINESS_GAPS.md](PROD_READINESS_GAPS.md)).

## 9. Step-level audit-события workflow

* **Что не сделано.** `StepAuditMiddleware`
  (`src/backend/infrastructure/workflow/middlewares/step_audit.py`) существует,
  но не инстанцируется и не подключён к runner'у: записи в
  `workflow_step_log` не уходят. Instance-level event log (`workflow_events`)
  при этом работает. Флаг `feature_flags.workflow_step_log_enabled` ничего
  не меняет — включать нечего.
* **Требует владельца.** Да — владелец K3 DSL+Workflow.
* **Done-критерий.** Middleware подключён к runner'у **или** класс удалён.

## 10. `extensions/credit_pipeline` — activity-имена не резолвятся

* **Что не сделано.** YAML-декларации расширения ссылаются на
  activity-имена, которых нет среди зарегистрированных actions ядра:
  `receive_dataset`, `llm_propose_code`, `execute_code_sandboxed`,
  `evaluate_results`, `format_final_report`,
  `collect_loan_inputs`, `supervisor_dispatch`, `risk_agent`,
  `compliance_agent`, `scoring_agent`, `consolidate_results`,
  `final_decision`, `fetch_credit_data`, `rag_query_legal_policies`,
  `llm_credit_decision` — в
  `extensions/credit_pipeline/workflows/` (`code_interpreter_loop`,
  `multi_agent_supervisor`, `rag_augmented_saga`). Резолвится только
  `credit_assessment.workflow.yaml` (его activity — это
  `module:fn`-ссылки на функции расширения).
* **Почему.** ADR-0398 включил build-time резолв activity
  (`collect_activities(declarations, validate=True)`) — worker падает на
  старте с явным списком неизвестных имён вместо runtime-ошибки
  `ActivityNotRegisteredError`. Имена — **бизнес-логика расширения**:
  правка в ядре невозможна, нужны либо реальные actions с этими именами,
  либо переименование в декларациях расширения.
* **Требует владельца.** Да — владелец расширения `credit_pipeline`.
  **Вне зоны** кластера документации: `extensions/*` — не наша зона.
* **Минимальный шаг.** Либо зарегистрировать actions с этими именами,
  либо привести `name:` в декларациях к существующим action'ам.
* **Done-критерий.** `collect_activities(..., validate=True)` проходит без
  `UnknownActivityError` для всех деклараций расширения.
* **Смягчение сейчас.** Флаг `workflow_use_temporal` default-OFF, поэтому
  default-конфигурация не затронута: дефект проявится только при
  включении Temporal в окружении с расширением `credit_pipeline`.

## 11. Межtenant-снимок под RLS требует роли `BYPASSRLS`

* **Что не сделано.** После ADR-0400 snapshot выставляет tenant-скоуп
  перед выборкой (`set_config('app.tenant_id', ...)`), поэтому снимок
  покрывает **один** tenant. Межtenant-снимок (все таблицы, все tenant'ы)
  таким способом не получить: при отсутствии tenant-контекста job
  работает в системном tenant (`_system`) и пишет WARNING в лог.
* **Почему.** Для межtenant-снимка нужна служебная роль с `BYPASSRLS` —
  а её выдача и DSN — эксплуатационное решение владельца БД (ADR-0393,
  «BYPASSRLS-роль для служебных соединений»).
* **Требует владельца.** Да — владелец БД: выдать роль и DSN.
* **Минимальный шаг.** Выдать служебную роль с `BYPASSRLS` и отдельный
  DSN для snapshot-job'а; job должен ходить по нему, а не по
  tenant-скоупу.
* **Done-критерий.** Снимок покрывает все tenant-таблицы без
  tenant-скоупа и без WARNING'а о системном tenant'е.
* **Сейчас в проде не актуально:** в `config_profiles/prod.yml`
  `snapshot.enabled: false`.

---

## Связанные документы

* [Workflows](../workflows/index.md) — контракт workflow-подсистемы и схема
  состояний.
* [Workflow-архитектура](../architecture/workflow_architecture.md) — карта
  модулей и границы слоёв.
* [Capability runtime](../explanation/capability_runtime.md) — capability-гейт.
* [PROD_READINESS_GAPS.md](PROD_READINESS_GAPS.md) — реестр прод-готовности.
* ADR волны 20: [ADR-0398](../adr/0398-workflow-event-log-pagination-and-subflow-semantics.md),
  [ADR-0399](../adr/0399-dsl-schemas-lsp-catalog-and-workflow-metrics.md),
  [ADR-0400](../adr/0400-snapshot-rls-graphql-hot-reload-and-bls-gate.md),
  [ADR-0401](../adr/0401-rpa-runtime-wiring-cache-invalidation-and-quotas.md).
