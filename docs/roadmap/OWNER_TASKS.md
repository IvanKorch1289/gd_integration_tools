# OWNER_TASKS — Известные ограничения и owner-задачи (волны 20 → 23)

> Реестр позиций, которые **нельзя закрыть кодом** без решения владельца:
> внешние зависимости, эксплуатационные решения, сознательно отложенные
> миграции. Позиции, закрытые кодом, помечены **✅ ЗАКРЫТО** со ссылкой на ADR
> и доказательством — они остаются здесь как traceability, а не как долг.
>
> Источник правды по волнам 13–23 — `docs/adr/` (ADR-0357…ADR-0414).
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
* **Осталось владельцу.** ✅ закрыто (ADR-0415, волна 23): генераторы
  `tools/scaffold_route.py`, `tools/wizards/route_templates.py` и
  `tools/wizards/route_wizard.py` переведены на табличную форму; гейт
  `tests/unit/tools/test_route_generators_capabilities.py` (51 тест) не даёт
  вернуть legacy-форму.

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

* **Статус.** ⚙️ контракты ✅ **ЗАКРЫТО** (ADR-0407, ADR-0412): пять
  «прод-значений» переведены из комментариев в исполняемые проверки
  `profile_merge.py`:
  HS256 допустим только при гарантированном `SEC_SECRET_KEY` (иначе CRITICAL);
  WAF `allow_hosts` обязан покрывать хосты внешних интеграций (SKB, Dadata),
  loopback — только при включённой локальной зависимости; `fallback_chain` без
  недоступных в проде сервисов (open_webui исключён); `replica_dsn=null` =
  «реплики нет» (не CRITICAL), непустое значение → реальный не-loopback хост и
  маскирование (ADR-0378); **sidecar'ы в prod/staging — по service-DNS**
  (`clamd`, `otel-collector`), loopback-хост sidecar'а — CRITICAL
  (`waf.clamav_host_loopback_in_prod`,
  `app.opentelemetry_endpoint_loopback_in_prod`). Проверка:
  `tests/unit/core/config/test_prod_values_contracts.py` (24 теста) +
  `tests/unit/core/config/test_adr0412_sidecar_dns.py` (32 теста);
  `manage.py validate-profile prod|staging` → 0 CRITICAL.
* **Осталось владельцу** (инфраструктурные решения, кодом не закрываются):
  * **3.1. Переход prod на RS256.** ✅ кодовая поддержка закрыта (ADR-0411,
    волна 23): режимы HS* ↔ RS*/ES* взаимоисключающие, JWKS/PEM-резолв по
    `kid`, отказ при несовпадении alg/ключа (algorithm confusion закрыт),
    утилита `python -m src.backend.core.security.jwt_keys generate --out <dir>`,
    контракт в SETTINGS_GUIDE. Осталось только инфраструктура: выпустить
    RSA-пару, задать `security.algorithm=RS256` + `jwt_private_key_path` +
    (`jwks_url` **или** `jwt_public_key_path`) + `jwt_kid`. Критерий: login
    возвращает RS256-токен; `validate-profile prod` → 0 CRITICAL.
  * **3.2. Service-DNS вместо loopback для sidecar'ов.** ✅ контракт закрыт
    кодом (ADR-0412), осталось — инфраструктура. Хосты sidecar'ов
    конфигурируемы и по умолчанию равны service-DNS именам (`clamd`,
    `otel-collector`); в prod/staging loopback-хост sidecar'а — CRITICAL
    (`waf.clamav_host_loopback_in_prod`,
    `app.opentelemetry_endpoint_loopback_in_prod`); `Service`-объекты для
    sidecar'ов и значения хостов — в `deploy/k8s/{service,configmap}.yaml`.
    **Критерии приёмки:** (1) развёрнуты Deployment'ы clamd и
    otel-collector с лейблами `app.kubernetes.io/name: clamd` /
    `otel-collector`; (2) `kubectl get svc clamd otel-collector` — оба
    ClusterIP в namespace приложения; (3) из pod'а приложения
    `nc -z clamd 3310` и `nc -z otel-collector 4317` — успех; (4)
    выбран режим отказа clamd в prod: `waf.clamav_fail_open: false`
    (недоступный clamd = блокировка запроса) либо осознанно `true`
    (тогда запросы проходят без сканирования — риск, который сейчас
    отмечает WARNING `waf.clamav_fail_open_in_prod`); (5)
    `python manage.py validate-profile prod` → 0 CRITICAL.
  * **3.3. Прод-endpoint OpenWebUI.** ✅ контракт закрыт кодом (ADR-0412),
    осталось — инфраструктура. Endpoint провайдера объявлен явно
    (`open_webui.base_url`, env `OPEN_WEBUI_BASE_URL`) со значением по
    умолчанию `http://open-webui:3000` (service-DNS); `Service`
    `open-webui` объявлен в `deploy/k8s/service.yaml`; провайдер **не**
    входит в `ai_providers.fallback_chain` prod/staging-профиля, пока
    сервис не развёрнут. **Критерии приёмки:** (1) развёрнут OpenWebUI
    (Deployment + Service `open-webui`); (2) из pod'а приложения
    `curl -sf http://open-webui:3000/api/v1/config` — 200; (3) провайдер
    возвращён в `ai_providers.fallback_chain` prod-профиля;
    (4) `python manage.py validate-profile prod` → 0 CRITICAL.
    Процедура включения — `docs/config/SETTINGS_GUIDE.md`, раздел
    «Sidecar-DNS и endpoint-контракты (ADR-0412)».
  * **3.4. DSN read-реплики.** ✅ контракт закрыт кодом (ADR-0407 +
    ADR-0412), осталось — инфраструктура. `replica_dsn: null` — валидное
    прод-значение («реплика не развёрнута»), непустое значение проверяется
    валидатором (реальный не-loopback хост) и маскируется в дампах; шаблон
    DSN задокументирован в комментариях профилей, в `SETTINGS_GUIDE.md` и
    закомментированным примером в `deploy/k8s/configmap.yaml`:
    `postgresql+asyncpg://<user>:<pass>@<replica-host>:5432/<db>`.
    **Критерии приёмки:** (1) выдан async-DSN реплики (Secret/Vault);
    (2) `database.replica_dsn` (или env `DB_REPLICA_DSN`) указывает на
    реальный хост реплики; (3) `snapshot.enabled: true` в prod включён по
    runbook'у; (4) `python manage.py validate-profile prod` → 0 CRITICAL.

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

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0414, волна 23, кластер C4). Модель шага
  зафиксирована: **шаг** = переход между `step_started` и терминальным
  исходом (`step_finished` / `step_failed` / отмена workflow'а). На шаг
  эмитятся события `workflow.step.started` и `workflow.step.succeeded` /
  `.failed` / `.cancelled` через unified audit-service
  (`core.audit.facade.emit_audit`) — **только метаданные**
  (route_id / step / tenant / attempt / outcome / duration_ms /
  capability / workflow_id), без значений данных и payload'а шага (тот же
  принцип «без данных», что ADR-0401 для процессоров). Гейт включения —
  декларация capability `audit.write` роутом (opt-in, как `audit_event` у
  процессоров): без декларации событий нет. Событие старта
  идемпотентно — один раз на (инстанс, шаг, попытка); дедупликация по
  event log'у (`idempotency_key`), поэтому переживает перезапуск
  процесса.
* **Проверка.** 8 тестов в
  `tests/unit/infrastructure/workflow/test_step_audit_wave23.py`
  (started/succeeded/failed/cancelled с метаданными; payload шага не
  попадает в событие; повторный запуск не дублирует событие старта; без
  декларации `audit.write` событий нет) + регресс
  `tests/unit/infrastructure/workflow/` и `tests/unit/core/workflow/` —
  358 passed, 5 skipped.
* **Осталось владельцу.** Да, вне кода: (1) аудит шагов
  Temporal-backend'а (production-путь не покрыт — у Temporal своя
  history-модель); (2) декларация `audit.write` в `routes/*/route.toml`
  роутов с workflow-спеками — без неё шаги не аудируются; (3) флаг
  `audit_clickhouse_enabled` в проде — иначе события не сохраняются.
  Критерии приёмки — в ADR-0414 §Открытое.

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

## 11. Межtenant-снимок под RLS: режимы выгрузки и роль `BYPASSRLS`

* **Статус.** ⚙️ кодовая часть ✅ **ЗАКРЫТО** (ADR-0409 + ADR-0413, волна 23,
  кластер C3). Контракт ADR-0409 («снапшот в пределах одного `tenant_id`;
  без скоупа — fail-closed») сохранён и расширен явной настройкой режима
  в модели `SnapshotSettings` (`snapshot.mode`):
  * `single-tenant` (по умолчанию, прежнее поведение) — скоуп из явного
    аргумента → tenant-контекста процесса, без скоупа —
    `SnapshotTenantScopeError`;
  * `per-tenant` — **безопасная** альтернатива `BYPASSRLS`: явный список
    `snapshot.tenants`, для каждого tenant'а свой `SET app.tenant_id`;
    пустой список — fail-closed (`SnapshotModeError`), снимок не пишется;
  * `service-role` — чтение служебной ролью с `BYPASSRLS` по DSN из
    `snapshot.service_dsn` (`SecretStr`, `SNAPSHOT_SERVICE_DSN`); DSN не
    задан — fail-closed; наличие `BYPASSRLS` у роли проверяется **до**
    выборки (`_assert_bypassrls`).
* **Проверка.** 16 новых тестов в
  `tests/unit/infrastructure/resilience/test_snapshot_job_modes.py` + 24
  существующих (регрессия `single-tenant`) — оба файла зелёные; «тихих 0
  строк» нет ни в одном режиме (пустой результат в межtenant-режимах —
  ошибка, файл снимка не затирается пустым). Операционный артефакт (SQL
  роли + шаблон DSN + проверки + откат + критерии приёмки) —
  `docs/ops/snapshot-bypassrls-role.md`.
* **Осталось владельцу.** Да — эксплуатационная часть (ADR-0393): если
  выбран режим `service-role`, владелец БД выдаёт роль (`NOLOGIN` +
  `BYPASSRLS` + `GRANT SELECT` только на таблицы снимка), заводит логин и
  кладёт DSN в секрет-хранилище по процедуре
  `docs/ops/snapshot-bypassrls-role.md`. Критерий приёмки: (1) у роли нет
  прав на запись; (2) `SNAPSHOT_SERVICE_DSN` не в YAML/репозитории;
  (3) при отзыве `BYPASSRLS` job падает с `SnapshotModeError`, а снимок не
  перезаписывается пустым; (4) RLS-политики остальных пользователей не
  изменены. Без выдачи роли работоспособен режим `per-tenant` (список
  tenant'ов — эксплуатационные данные владельца).

## 12. `jupyter.hub` — capability без plugin-провайдера

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0415, волна 23): реализован провайдер
  capability `jupyter.hub` на базе существующего клиента
  `infrastructure/clients/external/jupyter_hub.py` (verb `run` покрывается) —
  `extensions/jupyter_hub/{plugin.py,plugin.toml}` + sanctioned мост
  core→services (`core/di/providers/jupyter.py`); роут объявляет
  `requires_plugins`. Итог: **7 из 7 роутов `enabled`** (было 6/7).
* **Осталось владельцу.** Инфраструктура: развернуть JupyterHub и включить
  `v11.plugin_loader_enabled` + `jupyter_hub_enabled`. Отдельно: registry-ноутбуки
  на Hub не выполнятся — `NotebookExecutionService.execute()` требует локальный
  файл (отдельная задача).

## 13. Порядок в `tests/unit` — order-dependent загрязнение

* **Статус.** ✅ **ЗАКРЫТО** (ADR-0404, ADR-0410). 86 падений в 31 файле
  (все — в изоляции проходят) сведены к 0: причины (action-реестр,
  `sys.modules`-stub'ы, `os.environ`, `lru_cache`, синглтоны, незакрытые
  ресурсы) закрыты точечными фикстурами/изоляцией, без ослабления assert'ов и
  без skip/xfail. Банк `tests/unit/_xfail_environment.py` — только для
  ограничений ОКРУЖЕНИЯ (с причиной и ссылкой на owner-задачу); гейт роста
  банка — `tests/unit/test_order_dependent_pollution_gate.py`.
* **Проверка.** Полный прогон `pytest tests/unit` → **0 failed / 23484 passed**.

## 14. Мультироевое ревью (волны 24–25): что закрыто кодом

Ревью 6 агентами (безопасность, БД, workflow/DSL, инфраструктура, API,
качество) дало 2 critical + 12 high + ряд medium. Закрыто:

* **[critical] Авторизация на action-поверхности** (ADR-0421): `ActionMetadata.permissions`
  не проверялся нигде → 253 из 470 роутов без auth-зависимости, а
  `POST /api/v1/auto/admin.get_config` отдавал `settings.model_dump()`. Теперь
  права проверяются в `dispatch()` и на auto-/invocation-поверхности (без права —
  403, конфигурация не выдаётся).
* **[high] Дрейф контракта клиент↔сервер** (ADR-0422): 18 путей `api_clients/*` давали 404 →
  выровнены с роутером сервера + CI-гейт (AST-сверка 62 путей).
* **[high] CORS/CSRF-порядок** (ADR-0422): preflight → 401 → 204 без auth; CSRF перенесён
  внутрь auth-слоя → без ключа 401, без CSRF-токена 403.
* **[high] Tenant-guard** (ADR-0417): guard применялся к ВНЕШНИМ БД и пропускался без
  tenant-контекста → только main-движок, без tenant → fail-closed; единый канон
  tenant-таблиц (в т.ч. orders/users/files/orderkinds с RLS).
* **[high] Capability-контур** (ADR-0416): capability скиллов не проверялись (мёртвый
  `_global_capability_check`); baseline-флаг обходился; wildcard-scope `**` в baseline
  отключал scope-проверку storage.*/fs.read/net.outbound.
* **[high] Лимиты и надёжность БД** (ADR-0418): лимит выборки применялся ПОСЛЕ `fetchall()`
  (DoS через `SELECT *`); нет retry на 40001/40P01 и savepoint'ов; `connect/command_timeout`
  мертвы для mysql/mssql; batch-шаги без capability/квот/лимита.
* **[high] OpenAPI и загрузка файлов** (ADR-0423): 206 операций без 4xx, 188 мутаций без
  `requestBody`; загрузка файлов без лимита и content-type-проверки.
* **[medium] Ротация кредов БД** (ADR-0420): DSN менялся только с рестартом → отпечаток +
  dispose + пересоздание, подключено к hot-reload.
* **[medium] Прочее** (ADR-0419): JWKS без предельного окна stale и без https-проверки;
  Jinja без sandbox (SSTI); `pickle.loads` без provenance; `waf.clamav_fail_open` в проде;
  внешний `replica_dsn` без маскирования; CDC-DDL без валидации идентификаторов;
  deprecated `VALUES(col)` в MySQL-UPSERT.

### 14.1. Что осталось открытым из этого аудита

* ~~**D-4 (critical)**~~ — закрыто ADR-0428: patch-слой `_filter_statement`
  фильтрует ветви UNION/CTE (публичный API `visitors.replacement_traverse`);
  G13 переведён в «закрыт».
* ~~**WS/GraphQL admin-действия**~~ — закрыто ADR-0427: WS и GraphQL
  передают `principal`/`permissions` в action-диспетчер, `role:admin`
  добавляется из `admin_roles`; аннотация `info` исправлена (больше не
  псевдо-аргумент GraphQL-схемы).
* ~~**Namespace фасадов**~~ — **закрыто ADR-0430**: проверка идёт под namespace'ом
  вызывающего (`ContextVar` `core/security/capabilities/caller.py`), фасады
  `StorageFacade`/`UnifiedCacheFacade`/`ExternalDatabaseFacade` и `OutboundHttpClient`
  используют `effective_plugin(...)`; деградация безопасная — без деклараций у
  роута остаётся платформенный baseline (ADR-0416 §Открытое закрыто).
  * **Результат:** декларации `storage.*`/`db.*`/`cache.*` в `route.toml`
    влияют на проверку; гейт `tools/check_route_capabilities.py` блокирует
    недекларированные ресурсные capability у новых роутов (baseline легаси —
    `.security/route-capabilities-baseline.txt`).
  * **Статус:** требует решения владельца (безопасность × удобство), кодом
    в одиночку не закрывается.
* **Пустые capability-декларации в роутах** — ни одного `storage.*`/`db.*`/`cache.*`
  в `route.toml`/`plugin.toml` → автор обязан объявлять права сам.
* ~~**CI-скан зависимостей**~~ — закрыто: job `uv audit --frozen` + gate
  `tools/uv_audit_gate.py` разбирают **весь** `uv.lock` (все extras) и
  блокируют новые advisory-ID (канон — `.security/uv-audit-allowlist.txt`);
  job `pip-audit` остаётся вторым эшелоном на default-venv.

---

## 15. Контракт путей портала (волна 26, ADR-0425)

Гейт ADR-0422 сканировал только `api_clients/`; страницы `pages/**` ходили в API
напрямую и вне гейта держали **39 запросов, которых сервер не регистрирует**
(404, съеденные `except`). Закрыто кодом:

* гейт расширен на `pages/**` (`test_api_contract_paths.py`) — путь страницы
  обязан существовать на сервере, legacy-алиасы запрещены;
* 22 вызова переведены на канонические пути (префикс `/api/v1`, `/api/v1/routes/inventory`,
  `/api/v1/audit/capability`, `/api/v1/user/all/`, `/api/v1/admin/cron/list`,
  `/api/v1/admin/workflow-audit/events`, `/api/v1/admin/resilience-profiles`);
* 17 панелей без серверного endpoint'а показывают явное «endpoint не реализован»
  вместо swallowed 404.

Осталось закрыть (требует capability — **⚙️ инженерно**, но с решениями владельца):

| # | Endpoint | Что нужно | Статус сервиса |
|---|---|---|---|
| 1 | `GET /api/v1/admin/guardrails-metrics` + `POST …/{tenant_id}/false-positive` | — | ✅ **закрыто ADR-0432** (DI + эндпоинты + наполнение из AI-шлюза) |
| 2 | `GET /api/v1/admin/prompt-versions*` (list/activate/compare) | — | ✅ закрыто ADR-0437 |
| 3 | `GET /api/v1/webhooks/scheduled`, `POST /api/v1/webhook/schedule` | — | ✅ **закрыто ADR-0432** (DI + эндпоинты + SSRF-guard) |
| 4 | `GET /api/v1/storage/list|get|download` (по ключу) | — | ✅ закрыто ADR-0438 |
| 5 | `GET /api/v1/admin/pools/snapshot` + `GET /api/v1/admin/processes/{active,stats}` | — | ✅ закрыто ADR-0439 |
| 6 | `GET /api/v1/admin/processes/active`, `GET /api/v1/admin/queues/summary` | новая capability (для Kafka/RabbitMQ — нет) | нет |
| 7 | `POST /api/v1/admin/sql/query` | read-only SELECT с валидацией + аудитом | сознательно не поднимался |

**Требует владельца:** решение по п. 7 (SQL-консоль — расширение поверх БД в
проде) и по п. 6 (инфраструктурные метрики процессов/очередей).


---

## 16. Повторный аудит волны 27 (ADR-0429): что закрыто кодом, что осталось

Три агента (workflow-движок, эргономика DSL, отказоустойчивость) + целевые
тесты нашли класс «тихого успеха». Закрыто кодом (ADR-0429):

* ошибка процессора → `exchange.status = failed` (было `completed` при
  `error` в теле) — 117 процессоров DSL;
* неуспешная публикация (`ok=False`) → шаг проваливается (было: маршрут
  «успешен», сообщение терялось без DLQ) — все sink-процессоры;
* transient-ошибки HTTP/MQ sink'ов доходят до `with_retry` (было: broad-except
  → `ok=False`, retry не срабатывал ни разу);
* неожиданное исключение в workflow-runner'е → инстанс переводится в
  `failed` (было: навсегда `running`, backup-poll по кругу);
* шаблон `guardrail_cost_budget` получил числовой источник и явные `target`-ы
  (было: `GuardrailValueTypeError` при запуске) + гейт «у guardrail-шага есть
  `target`»;
* теги шаблонов читаются из YAML-поля `tags:` (было: пустые теги у всех 18 —
  поиск по тегам не работал, регресс ADR-0424);
* ruff-гейт по `src/` снова зелёный (5 pre-existing ошибок).

Осталось (⚙️ инженерно, кроме отмеченного):

| # | Находка | Что нужно | Severity |
|---|---|---|---|
| 1 | ~~`memory.reflect` и `workflow.checkpoint.put` не зарегистрированы как activity~~ | регистрация во внутренних activity | ✅ закрыто ADR-0433 (реализованы + зарегистрированы в Worker'е) |
| 2 | ~~Компенсация откатывает разные шаги в Temporal- и pg-runner'е~~ | выровнять семантику (ADR) | ✅ закрыто ADR-0431 |
| 3 | ~~`idempotency_key` не доходит до внешнего вызова~~ | проброс ключа в заголовок activity | ✅ закрыто ADR-0431 |
| 4 | ~~Линтер `*.workflow.yaml` отсутствует (только route-DSL)~~ | `dsl lint` для workflow-спеки: spec + `collect_activities(validate=True)` + `file:step.field` | ✅ закрыто ADR-0433 (`tools/check_workflow_specs.py` + шаг в `lint.yml`) |
| 5 | ~~`workflow_setup.py` глотает ошибку загрузки workflow (`warning` + `str(exc)[:200]`)~~ | `logger.error` с путём файла и полным текстом | ✅ закрыто ADR-0434 |
| 6 | ~~`bulkhead`/`circuit-breaker` не подключены к DSL-процессорам~~ | подключение по аналогии с `core/api` | ✅ закрыто ADR-0436 |
| 7 | ~~`core/api/__init__.py` не экспортирует CB/RateLimiter/Bulkhead~~ | привести экспорт в соответствие с докстрингом | ✅ закрыто ADR-0434 |
| 8 | ~~Нет cookbook'а «как написать workflow YAML»~~ | `docs/cookbooks/07-write-workflow-yaml.md` | ✅ закрыто ADR-0434 |
| 9 | ~~`manage.py dsl --help` не показывает `generate`~~ | discoverability CLI-генератора | ✅ закрыто ADR-0434 (генератор подключён к `dsl_app`) |
| 10 | ~~`dsl/cli/lint.py` и `dsl/engine/dry_run.py` дублируют `dsl/workflow/dryrun.py`~~ | удалить дубли (deletion over addition) | ✅ закрыто ADR-0434 (3 линтера → 1; dry-run'и разных доменов разведены) |

**П. 2 и 3 закрыты решениями владельца** (ADR-0431): компенсация откатывает
только **выполненные** шаги (выровнено с Temporal-путём), ключ идемпотентности
пробрасывается во внешний вызов заголовком `Idempotency-Key` — контракт для
получателя (дедупликация по ключу) зафиксирован в ADR-0431.

**Осталось:** сводка очередей (`GET /api/v1/admin/queues/summary`) — общей
capability «метрики брокера» (Kafka/RabbitMQ) в кодовой базе нет; есть только
NATS-специфичный `GET /api/v1/admin/nats/consumers`. Панель портала остаётся
выключенной — решение (ввести брокер-агент или отказаться) за владельцем.

---

## 17. Решения владельца волны 28 (2026-11-09) — что закрыто кодом

Владелец согласовал все рекомендации (A/B/C/D → A). Реализовано:

| # | Решение | Статус |
|---|---|---|
| 1 | **Caller-aware capability** (namespace вызывающего вместо платформенного; безопасная деградация) | ✅ ADR-0430 |
| 2 | **SQL-консоль** (`POST /api/v1/admin/sql/query`) не поднимается | ✅ зафиксировано: панель выключена, threat model отложен |
| 3 | **7 отсутствующих эндпоинтов портала** — поднять только живые capability | ✅ ADR-0432: guardrails-метрики + webhook-планировщик; остальные — бэклог (§15) |
| 4 | **Capability-декларации обязательны + CI-гейт** (рэтчет, baseline легаси) | ✅ ADR-0430: `tools/check_route_capabilities.py` + шаг в `lint.yml` |
| 5 | **Идемпотентность внешних вызовов** — ключ в заголовке activity | ✅ ADR-0431 |
| 6 | **Семантика компенсации** — откатывать только выполненное (как в Temporal) | ✅ ADR-0431 |
| 7 | **Инфраструктурные долги** — единый пакет «инфра-решения» с владельцами | ✅ **чек-лист `docs/ops/infra-release-checklist.md` (ADR-0441)**; закрыто кодом: `.env:92` (парсинг compose), образ `gd-integration-tools:light` (пересобран, `/health` 200), Prometheus-правила (ADR-0440), `audit_clickhouse_enabled` в prod, service-DNS (ADR-0412), JWKS-алгоритмы, BYPASSRLS-guard, `jupyter.hub`-провайдер, OpenWebUI-контракт. Осталось за инфраструктурой (команды — в чек-листе): keypair+JWKS-сервис для RS256, развёртывание OpenWebUI, роль БД с `BYPASSRLS` для межtenant-снапшота, ClickHouse в проде (audit-трейл), решение владельца по `audit.write`-декларациям и `replica_dsn` |
| 8 | **Волна 28 = «стойкость»** | ✅ закрыто полностью: идемпотентность (ADR-0431) + компенсация (ADR-0431) + линтер workflow-спецификаций и внутренние activity (ADR-0433) |

---

## Связанные документы

* [ADR-0405](../adr/0405-route-capabilities-namespace-migration.md) — миграция capability-деклараций роутов.
* [ADR-0406](../adr/0406-pillow-13-blocker-and-criteria.md) — Pillow 13 / Streamlit 1.66.1.
* [ADR-0407](../adr/0407-production-values-contracts.md) — исполняемые контракты прод-значений.
* [ADR-0408](../adr/0408-workflow-dlq-contract-and-sla-alerting.md) — DLQ workflow и SLA-алертинг.
* [ADR-0409](../adr/0409-multi-tenant-snapshot-and-credit-pipeline-agents.md) — скоуп снапшота и честные агенты расширения.
* [ADR-0410](../adr/0410-order-dependent-pollution-final.md) — закрытие order-dependent загрязнения.
* [ADR-0412](../adr/0412-sidecar-dns-and-endpoint-contracts.md) — service-DNS для sidecar'ов и endpoint-контракты.
* [ADR-0413](../adr/0413-multi-tenant-snapshot-modes.md) — режимы межtenant-снапшота (закрывает кодовую часть §11).
* [ADR-0414](../adr/0414-workflow-step-audit-model.md) — модель аудита шагов workflow (закрывает §9).
* [ADR-0403](../adr/0403-workflow-sla-dlq-and-prod-validator.md) — SLA-алертинг, workflow-DLQ, прод-валидатор.
* [PROD_READINESS_GAPS.md](PROD_READINESS_GAPS.md) — реестр прод-готовности.
