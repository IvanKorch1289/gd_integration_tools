# OWNER_TASKS — Известные ограничения и owner-задачи (волны 20 → 22)

> Реестр позиций, которые **нельзя закрыть кодом** без решения владельца:
> внешние зависимости, эксплуатационные решения, сознательно отложенные
> миграции. Позиции, закрытые кодом, помечены **✅ ЗАКРЫТО** со ссылкой на ADR
> и доказательством — они остаются здесь как traceability, а не как долг.
>
> Источник правды по волнам 13–22 — `docs/adr/` (ADR-0357…ADR-0410).
> Реестр прод-готовности — [PROD_READINESS_GAPS.md](PROD_READINESS_GAPS.md).

## Как читать

| Пометка | Значение |
|---|---|
| **требует владельца** | Нужен выбор/решение человека: внешний пин, инфраструктура, эксплуатация, миграция данных. Кодом не закрывается. |
| ⚙️ инженерно | Закрывается кодом в следующей волне, владелец не нужен. |
| ✅ ЗАКРЫТО | Закрыто кодом и проверено тестами; ссылка на ADR + что именно сделано. |

---

## 1. Миграция `route.toml` под новый namespace capability

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0405, волна 22).
* **Что сделано.** Все `routes/*/route.toml` переведены на табличную форму
  `[[route.capabilities]]` с `name` из vocabulary и осмысленным `scope`
  (`net.outbound` — host, `audit.write` — `audit:*`); legacy-форма принимается с
  `WARNING` + `DeprecationWarning` (`services/routes/manifest_toml.py`).
  Найден и устранён реальный дефект: capability без scope давал
  `CapabilityRef(scope=None)`, а `validate_ref` отвергает `scope=None` при
  `scope_required=True` → `ValueError` при загрузке роута (грузились 3 из 7
  роутов; стало 6 из 7 — `jupyter_hub_run` требует plugin-провайдера
  `jupyter.hub`, см. §12).
* **Проверка.** Гейт `tests/unit/services/routes/test_route_capabilities_migrated.py`
  (11 тестов): нет legacy-формы, имя без `:` и из vocabulary, все роуты
  грузятся `RouteLoader` и проходят capability-гейт.
* **Governance.** Миграция меняет семантику декларации авторизации →
  оформлена отдельным ADR-0405 согласно governance-правилу **ADR-0284 §1.1**
  (изменения ALLOWED-матрицы и семантики авторизации требуют per-ADR approval).
* **Осталось владельцу.** ⚙️ инженерно: мигрировать генераторы
  `tools/scaffold_route.py` и `tools/wizards/route_templates.py` на табличную
  форму (ADR-0405 §Открытое).

## 2. Lock-чанж: Pillow 13 и `psycopg[binary]` → extra `db_drivers`

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0402 — psycopg; ADR-0406 — Pillow/Streamlit).
* **Что сделано.** `psycopg[binary]>=3.1,<4.0.0` перенесён в extra `db_drivers`
  (sync-PG — задача драйверов БД; в `sources-cdc` объявление сохранено).
  Pillow обновлён 12.3.0 → **13.0.0** вместе со Streamlit 1.63.0 → **1.66.1**
  (первая версия, допускающая `pillow<14`); вынужденно подняты
  `docling-ibm-models` 4.0.4 и `docling-parse` 7.24.2 (их `pillow<13`).
  Pillow 13 удалил молчаливое обрезание mode `I` при сохранении в PNG →
  конвертация в `"I;16"`.
* **Проверка.** `uv lock --check` → 0; `uv audit --frozen`: **84 → 47** advisory
  (59 Pillow-ID сняты); гейт `tools/uv_audit_gate.py` → PASS; гейт
  `tests/unit/test_pillow13_upgrade_gate.py` (9 тестов).
* **Осталось владельцу.** ⚙️ инженерно: пересобрать dev/CI-образы (Streamlit
  теперь требуется ≥1.66.1) и подтвердить в среде с доступным `pypi.org`
  (`uv lock --check`, `uv sync --all-extras`, `uv audit --frozen`).

## 3. Прод-значения, оставленные осознанно

* **Статус.** ⚙️ контракты ✅ **ЗАКРЫТО** (ADR-0407): четыре «прод-значения»
  переведены из комментариев в исполняемые проверки `profile_merge.py`:
  HS256 допустим только при гарантированном `SEC_SECRET_KEY` (иначе CRITICAL);
  WAF `allow_hosts` обязан покрывать хосты внешних интеграций (SKB, Dadata),
  loopback — только при включённой локальной зависимости; `fallback_chain` без
  недоступных в проде сервисов (open_webui уже исключён); `replica_dsn=null` =
  «реплики нет» (не CRITICAL), непустое значение → реальный не-loopback хост и
  маскирование (ADR-0378). Проверка: `tests/unit/core/config/test_prod_values_contracts.py` (24 теста);
  `manage.py validate-profile prod|staging` → 0 CRITICAL.
* **Осталось владельцу** (инфраструктурные решения, кодом не закрываются):
  * **3.1. Переход prod на RS256.** Требует RSA-keypair + JWKS/IdP и
    `security.algorithm=RS256` + `jwks_url`. Критерий: prod работает с
    внешним IdP; `validate-profile prod` → 0 CRITICAL.
  * **3.2. Service-DNS вместо loopback для sidecar'ов.** Сейчас `waf.clamav_host`
    и otel-экспорт указывают на loopback → в pod-сети это другой контейнер.
    Критерий: `waf.clamav_fail_open: false` в prod + хосты sidecar'ов в
    Service-DNS.
  * **3.3. Прод-endpoint OpenWebUI.** Провайдер исключён из `fallback_chain`
    (сервис не развёрнут). Критерий: endpoint развёрнут и провайдер возвращён в
    цепочку.
  * **3.4. DSN read-реплики.** `replica_dsn: null` = реплики нет. Критерий:
    DSN указывает на реальную реплику, покрыт тестом «не-loopback хост» и
    маскируется в дампах.

## 4. Baseline `missing-secret` / `missing-non-secret`

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0403). Явный allowlist
  `.security/config-audit-missing-secret-allowlist.txt` (запись действует только
  с `owner=` и `reason=`), гейт по этому классу → 0.
* **Осталось владельцу.** ⚙️ инженерно: периодически разбирать allowlist и
  переносить подтверждённые исключения в `.env.example`.

## 5. `PolicyMixin.cache()` — шим с MRO-коллизией

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0355, волны 13–14). `cache_policy()` —
  маркер без кэша; добавлен `RuntimeWarning` с указанием канонического пути
  (`RouteBuilder.cache(...)`); deprecated-шим `cache()` предупреждает.
  Реальный кэш в DSL-маршруте отложен отдельным ADR (ADR-0355, Option C).
* **Осталось владельцу.** ⚙️ инженерно: если нужен реальный кэш в маршрутах —
  отдельный ADR + реализация через `UnifiedCacheFacade` (ADR-0354).

## 6. Дубль OCR-процессора

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0402). `services/rpa/ocr_processor.py` удалён
  как мёртвый дубль DSL-шага `ImageOcrProcessor` (0 вызовов, 0 lazy-импортов,
  0 DI) вместе с тестами.

## 7. `pg_runner_backend.py:250` — `replay()` → `NotImplementedError`

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0408). `replay()` переигровывает исчерпанный
  шаг по записи DLQ (контракт DLQ — общий с **messaging**-DLQ, `infrastructure/messaging/dlq_base.py`):
  сброс бюджета (`resumed` + `attempts_reset`), возврат в
  `pending`; отсутствующая/битая запись → fail-loud (`ValueError`/`KeyError`).
  Попутно устранён pre-existing баг волны 19: `runner.py` не компилировался
  (`except A, B:`) — весь pg-runner стек падал на импорте.
* **Проверка.** `tests/unit/infrastructure/workflow/test_workflow_dlq_wave22.py`,
  `test_pg_runner_backend_dlq_statement.py`, `test_pg_runner_replay_deprecated.py`.

## 8. `SlaTracker` — SLA-алертинг не реализован

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0403 + ADR-0408, GAP-WF-4.5). Мёртвый
  `SlaTracker` удалён; контракт заменён на измеримый: метрика
  `workflow_sla_compliance_total` эмитится в рантайме на каждом терминальном
  переходе workflow (бюджет: `__sla_hard_limit_s` → `__execution_timeout_s` →
  `run_timeout_s` спеки), 4 правила Prometheus/alertmanager в
  `docs/ops/workflow-sla-alerts.md`, runbook `docs/runbooks/hitl-stuck-workflow.md`
  переписан под фактическую семантику.
* **Осталось владельцу.** ⚙️ инженерно: доставить правила в Prometheus
  (в репозитории нет rule-файлов) и настроить маршрутизацию алерта.

## 9. Step-level audit-события workflow

* **Статус.** ⚙️ инженерно: аудит **процессоров** закрыт (ADR-0401: базовый
  класс эмитит `audit_event` — только метаданные capability/route/tenant, без
  значений данных). События именно **шагов workflow** в pg-runner не
  эмитятся — нужен контракт «что считать шагом» (ADR-0391: текущая семантика
  `step_started/step_finished` в событийном логе не доходит до audit-сервиса).
* **Минимальный шаг.** Определить, что является шагом для аудита (событие
  pg-runner или DSL-шаг), и эмитить единообразно с уже реализованным
  процессорным аудитом.
* **Требует владельца.** Да — выбор модели аудита шагов.

## 10. `extensions/credit_pipeline` — activity-имена не резолвятся

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0409). Вместо фиктивных шагов — честные
  реализации: `extensions/credit_pipeline/sandbox.py` (через core-контракт
  `CodeSandbox`, без `subprocess`) и `supervisor.py` (core-`MultiAgentSupervisor`
  с реальными агентами расширения); `decision_agent` получает настоящий
  `scoring_agent` (раньше `credit_score=0` → кредит отклонялся всегда); плоский
  payload вместо вложенных `body/responses` (цели теряли данные); 5 actions
  зарегистрированы в `plugin.py`/`plugin.toml`; `collect_activities(validate=True)`
  проходит для всех 4 workflow расширения.
* **Проверка.** 30 новых тестов в `tests/unit/` (наборы sandbox/supervisor и
  консистентности workflow — команды в ADR-0409 §Проверка) плюс тесты
  расширения в `extensions/credit_pipeline/tests/`.

## 11. Межtenant-снимок под RLS требует роли `BYPASSRLS`

* **Статус.** ⚙️ контракт ✅ **ЗАКРЫТО** (ADR-0409): проход по тенантам с
  per-tenant `SET` невозможен (реестра tenant'ов нет, `SELECT DISTINCT tenant_id`
  под RLS видит только текущего) → контракт «снапшот в пределах одного
  `tenant_id`; без скоупа — fail-closed» (`SnapshotTenantScopeError`); скоуп
  определяется **до** создания движка/транзакции → отказ не затирает файл
  снимка; пустой снимок → WARNING.
* **Осталось владельцу.** Да — если нужен межtenant-снимок: роль с
  `BYPASSRLS` + DSN, либо per-tenant job'ы (по одному на тенанта) с
  `register_snapshot_job(scheduler, tenant_id=...)`. Критерий: снапшот всех
  тенантов без «тихих 0 строк» и без обхода RLS в привилегированном режиме
  без явного решения.

## 12. `jupyter.hub` — capability без plugin-провайдера

* **Статус.** ⚙️ инженерно: `routes/jupyter_hub_run/route.toml` объявляет
  `jupyter.hub` (scope `run`), но провайдера в проекте нет → роут не проходит
  capability-гейт (`capability_superset`). Остальные 6 роутов грузятся.
* **Минимальный шаг.** Либо реализовать провайдер `jupyter.hub` (расширение),
  либо убрать capability из манифеста роута (роут без доступа к Jupyter).
* **Требует владельца.** Да — функциональное решение (нужен ли Jupyter-доступ
  в проде).

## 13. Порядок в `tests/unit` — order-dependent загрязнение

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0404, ADR-0410). 86 падений в 31 файле
  (все — в изоляции проходят) сведены к 0: причины (action-реестр,
  `sys.modules`-stub'ы, `os.environ`, `lru_cache`, синглтоны, незакрытые
  ресурсы) закрыты точечными фикстурами/изоляцией, без ослабления assert'ов и
  без skip/xfail. Банк `tests/unit/_xfail_environment.py` — только для
  ограничений ОКРУЖЕНИЯ (с причиной и ссылкой на owner-задачу); гейт роста
  банка — `tests/unit/test_order_dependent_pollution_gate.py`.
* **Проверка.** Полный прогон `pytest tests/unit` → **0 failed / 23484 passed**.

---

## Связанные документы

* [ADR-0405](../adr/0405-route-capabilities-namespace-migration.md) — миграция capability-деклараций роутов.
* [ADR-0406](../adr/0406-pillow-13-blocker-and-criteria.md) — Pillow 13 / Streamlit 1.66.1.
* [ADR-0407](../adr/0407-production-values-contracts.md) — исполняемые контракты прод-значений.
* [ADR-0408](../adr/0408-workflow-dlq-contract-and-sla-alerting.md) — DLQ workflow и SLA-алертинг.
* [ADR-0409](../adr/0409-multi-tenant-snapshot-and-credit-pipeline-agents.md) — скоуп снапшота и честные агенты расширения.
* [ADR-0410](../adr/0410-order-dependent-pollution-final.md) — закрытие order-dependent загрязнения.
* [ADR-0403](../adr/0403-workflow-sla-dlq-and-prod-validator.md) — SLA-алертинг, workflow-DLQ, прод-валидатор.
* [PROD_READINESS_GAPS.md](PROD_READINESS_GAPS.md) — реестр прод-готовности.
