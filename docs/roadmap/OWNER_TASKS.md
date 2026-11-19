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
| 6 | `GET /api/v1/admin/processes/active` | — | ✅ закрыто ADR-0439 |
| 6б | `GET /api/v1/admin/queues/summary` | **закрыто решением владельца 2026-11-16**: capability «метрики брокера» (Kafka/RabbitMQ) не создаём — брокер-агент без потребителя; панель честно сообщает, доступен только NATS-специфичный `GET /api/v1/admin/nats/consumers` | ✅ закрыто |
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

**Закрыто решением владельца (2026-11-16):** сводка очередей
(`GET /api/v1/admin/queues/summary`) не вводится — capability «метрики
брокера» (Kafka/RabbitMQ) в кодовой базе нет, а брокер-агент — новая
подсистема без потребителя. Панель портала сообщает об этом явно; доступен
только NATS-специфичный `GET /api/v1/admin/nats/consumers`.

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
| 7б | ~~**ORM-tenant fail-closed**~~ — **закрыто ADR-0448 (вариант А, решение владельца 2026-11-16)**: контекста нет → платформенный scope; `tenant_id=_system` → кросс-tenant явно; `tenant_id=""` → fail-closed; реальный tenant → фильтр | ✅ закрыто |
| 8 | **Волна 28 = «стойкость»** | ✅ закрыто полностью: идемпотентность (ADR-0431) + компенсация (ADR-0431) + линтер workflow-спецификаций и внутренние activity (ADR-0433) |

---

## 18. Волна 33 (2026-11-17) — передача полномочий: что закрыто

| # | Пункт | Статус |
|---|---|---|
| 1 | **ORM tenant-скоуп** (вариант А) | ✅ ADR-0448: контекста нет / `_system` → платформенный scope; пустой tenant → fail-closed (+ обход UNION/CTE закрыт в волне 33) |
| 2 | **Capability-контур** | ◐ ADR-0449 + ADR-0451: долг легаси-форм **36 → 0**, allowlist гейта пуст; **enforcement — на уровне процессоров, не движка** (см. открытые позиции ADR-0449) |
| 3 | **audit.write** | ✅ ADR-0454: capability реально enforced в `AuditProcessor` (отказ без декларации, проверка scope), объявлена во всех 5 роутах с этим шагом |
| 4 | **Mutation-гейт** | ✅ ADR-0452: разблокирован (обвязка + синхронизация workspace), baseline 21.6 %, гейт в CI |
| 5 | **Coverage-перемер** | ✅ ADR-0453: `tools/run_coverage_grouped.sh` починен (имя частей, порог на группе, пустые группы, исключение `chaos`/`integration`), CI и `make coverage-grouped` |
| 6 | **Межслойные нарушения** | ◐ ADR-0450: baseline 41 → **40** (рэтчет: долг 37 + контракты 3; гейт блокирует рост и стейл-записи), план инверсии по доменам зафиксирован |
| 7 | **Инфраструктура (6 действий)** | ◐ ADR-0455: генератор JWKS keypair и SQL-роль снапшота **доведены до применимости** (проверено прогонами: PG 16.15, отказ «внутри репозитория», ротация ключа); чек-лист — с реальными env-именами (`SEC_*`, `DB_*`) и командами. За владельцем: keypair+секрет-менеджер, JWKS-сервис (https), роль БД+DSN снапшота, внешний ClickHouse, OpenWebUI, JupyterHub, `DB_REPLICA_DSN` |
| 8 | **CVE-гейт** (найдено волной 33) | ✅ Гейт не доходил до отчёта (конфликт пинов `click` в `uv export`) → дедуп по имени пакета; **23 CVE в 6 пакетах закрыты** обновлениями lock (filelock 4.2.10, pypdf 7.1.0, soupsieve 4.1.1, opentelemetry 1.45.2, joserfc 1.8.0, dnspython 2.9.2, deepeval 4.3.4) → `make cve-gate`: PASS, 0 unignored |

---

## 19. Волна 34 (2026-11-17/18) — закрытие долгов волны 33

| # | Пункт | Статус |
|---|---|---|
| 1 | **Межслойные нарушения** | ✅ **ADR-0457**: долг **37 → 0**. Инверсия через core-реестр ресурсов расширений (`core/extension_registry.py` + `extensions/*/resources.py`): `src/` больше не импортирует `extensions.*` — ни entrypoints (18), ни dsl (7), ни services (3). Отдельно: инверсия `core → services.ai` (6) и `infrastructure/workflow → dsl` (4). Итог по гейту: **долг 0 + 3 осознанных контракта** `services → dsl` (ADR-0348, вариант C) |
| 2 | **Capability-контур (engine-wide)** | ✅ **ADR-0456**: проверка capability шага перенесена из процессоров в движок (`dsl/engine/capability_guard.py`) — отказ = `failed` + `stopped`, шаг не выполняется. Закрыта открытая позиция №1 роевого отчёта волны 33 |
| 3 | **`function.call` в манифестах** | ✅ capability объявлена в `routes/jupyter_hub_run` и `routes/osint_agent`; `function.call` — public в vocabulary (как `audit.write`): плагина-владельца нет, runtime-контроль не ослаблен |
| 4 | **Mutation-гейт** | ✅ гейт переведён в fail-closed: контракт exit-кодов (0/1/2/3), SKIPPED с причиной вместо «пустого» PASS, починены stats-файл, кэш вердиктов (`mutants/**/*.meta`), PATH-бинарник и обёртка под mutmut 3.x. Baseline **21.6 % переподтверждён холодным прогоном** (killed 247 / total 1142) |
| 5 | **Coverage-перемер** | ✅ grouped-прогон переведён в канонический CI-режим (`-n 2 --dist loadfile`, без OOM); baseline перемерен: **77.68 %** line-rate (branch 75 %), приведено к метрике гейта |
| 6 | **Инфраструктура (6 действий)** | ◐ **кодовая часть закрыта**: в `ops/compose/docker-compose.prod.yml` добавлены сервисы `clickhouse`, `open-webui`, `jupyterhub` (pinned-образы, healthcheck, без секретов в compose); профиль prod и `.env.example` приведены к реальным env-именам; новый гейт `make infra-readiness` проверяет конфигурацию всех 6 пунктов. **За владельцем**: развёртывание (keypair+JWKS https, роль БД + DSN снапшота, ClickHouse/OpenWebUI/JupyterHub в кластере, `DB_REPLICA_DSN`) |
| 7 | **CI-режим (xdist)** | ✅ найден корень падения `polars` в CI-режиме: `_module_installed()` считал пакет «не установленным», когда в `sys.modules` лежал stub → cleanup сносил подмодули → циклический импорт `polars.lazyframe`. Полный граф polars кэшируется один раз на воркер |

**Проверки волны 34:** регрессия `tests/unit` в каноническом CI-режиме
(`-n 2 --dist loadfile`) — **0 failed**; OpenAPI — **447 путей** (не изменилось);
гейты: layers (0 новых), decorative capabilities (0 новых), route capabilities,
docstrings (0 missing), ruff, mypy (12 = baseline), mutation, coverage.

---

## 21. Волна 36 (2026-11-18) — доработка по плану аудита волны 35

| # | Пункт плана (`artifacts/current_audit/CODE_AUDIT_2026-11-18.md` §4) | Статус |
|---|---|---|
| 1 | **P1-1** caller-namespace в последовательном пути | ✅ привязка добавлена (fail-safe); аудит 7 роутов/12 плагинов: `GRANT→DENY` невозможен; ADR-0430 «Уточнение волны 36». Требует подтверждения владельца: фактическое изменение enforcement для фасадных capability |
| 2 | **P1-2** `ActionRegistryAdapter` не затирает `payload_model` | ✅ сохранение `payload_model`/`input_model`/`permissions`; конфликт → fail-closed `ValueError`; 9 тестов |
| 3 | **P1-3** фиче-флаги читаются динамически | ✅ `core/feature_flags/service.py` + `core/tenancy/feature_flag_scope.py` (тот же кэш-баг); приоритеты не изменились |
| 4 | **P1-4/P1-5** единый tenant-контекст | ✅ канон `core/tenancy/context.py` (`TenantContext` с `principal_id`, `CapabilityTenant` — фасад, `normalize_tenant_context()` fail-closed); `with_tenant` ставит канонический контекст; 15 тестов |
| 5 | **P2-2** гейт «у action'а один владелец» | ✅ `tools/check_action_ownership.py` (fail-closed, `--json`/`--strict`): 134 actions / 134 регистрации / 12 плагинов; шаг в `lint.yml`; 9 тестов |
| 6 | **P2-3** контракт `call_function` | ✅ `tools/check_workflow_specs.py`: движок передаёт `dict` — сигнатура, требующая список/скаляр, отвергается |
| 7 | **P2-4** инверсия в `utilities` | ✅ `utilities/admin_panel/setup_admin.py` берёт admin-view из core-реестра (4 импорта `extensions.*` убраны); гейт на lazy-импорты — не сделан |
| 8 | **P2-5** ETag по отдаваемым байтам | ✅ `response_cache` перенесён внешне обоих маскеров; ETag = хеш фактически отданного тела; 304 без тела; 8 тестов |
| 9 | **P2-10** `logout()` чистит API-кэш | ✅ best-effort очистка кэша + session state; **замечание:** кнопки выхода в портале нет — фикс не сработает, пока её не добавят |
| 10 | **P3** LRU `_validation_cache` (512), единый `SYSTEM_TENANT_ID`, удаление мёртвого `dsl/engine/process` | ✅ |
| 11 | Регрессы волны 36 | ✅ FK `orders.order_kind_id → orderkinds.id` (модели orderkinds импортируются в моделях заказов); удалён мёртвый модуль регистрации actions в `entrypoints/api/generator/` с конфликтующим `payload_model` |
| 12 | Открыто (требует решения владельца) |

---

## 22. Волна 36 (продолжение) — локализация открытых находок

| # | Позиция | Результат |
|---|---|---|
| 1 | «Стриминговый ответ обрезается до первого чанка» | ✅ **опровергнуто**: реальная цепочка middleware отдаёт все чанки (5/5, 200). Находка — артефакт измерения бесконечного SSE-потока (`/events/stream`: `while True` + heartbeat) блокирующим клиентом. Закрыто регресс-тестом `test_streaming_passthrough.py` |
| 2 | PII-редирекция в SSE падала **fail-open**, а escape-hatch `FEATURE_PII_STREAMING_FAIL_CLOSED` не существовал | ✅ флаг реализован (`core/config/features/security.py`), fail-closed режим в `sse/handler.py`, 5 тестов |
| 3 | KNOWN-01: повторный импорт падал с `KeyError` по родительскому пакету | ✅ **закрыто**: локализован цикл импортов `core.resilience.__init__ → rate_limiter → infrastructure.resilience → coordinator → core.resilience`; на Python 3.14 — `_DeadlockError` (per-module импорт-лок), ошибка глушилась `emit_audit_safe` → **терялись события аудита**. Фикс: ленивый re-export пакета (PEP 562) |
| 4 | `gateway.verify_request is auth_selector.verify_request` (order-dependent) | ✅ **закрыто**: шим `auth_selector` переведён на ленивый re-export через канонический фасад `core.auth.gateway` |
| 5 | `Bulkhead`/`get_bulkhead` в `core.resilience.__all__`, но не импортируются | ✅ убраны из API core (канон — `infrastructure.resilience.bulkhead`) |
| 6 | P2-8 capability-граф не видел вложенные расширения | ✅ обход по `rglob("plugin.toml")`: 12 плагинов (было 8), 3 теста |
| 7 | Остальные открытые пункты плана | 📍 **локализованы до file:line** — `artifacts/current_audit/LOCALIZATION_2026-11-18.md` §4 (pre-load расширений, `basicAuth`/`samlSession`, `xfail_strict`, фаза `denied` в трейсере, `ProtocolType`, `cache_resource`, `Cache-Control: public`, host-glob vs URL) | pre-load расширений в lifespan; мёртвые `basicAuth`/`samlSession` в схеме; `rglob(plugin.toml)` в capability-графе; `xfail_strict` + perf-профиль; фаза `denied` в трейсере; `ProtocolType` → `core/types`; `cache_resource` → `session_state`; 9 библиотечных правок (почти все — lock, требует согласования); `Cache-Control: public` для аутентифицированных ответов; стриминговая регрессия HTTP-цепочки (pre-existing) |

---

## 20. Волна 34 (2026-11-18) — сверка документации с кодом

Зона: `docs/**`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `.claude/**`,
`artifacts/current_audit/**`. Правки — только в документации; `src/`, `tests/`,
`tools/`, `.baselines/` не тронуты.

| # | Пункт | Статус |
|---|---|---|
| 1 | **Гейты документации** | ✅ прогнаны фактически: `tools/check_docstrings.py` → **exit 0, 0 missing** (полный обход дерева); `tools/checks/check_service_docs.py` → exit 0; `tools/build_adr_index.py` → 400 ADR, 0 коллизий, индекс без диффа; `tools/check_v11_artefacts.py` → был **красный** (`docs/reference/capabilities.md` устарел) → пересобран (`make capability-catalog`) → **exit 0** |
| 2 | **README: блок «Текущие метрики»** | ✅ был устарел с 2026-10-19 (actions 124, OpenAPI 414/142, тестов 22 389, layer «debt: 37 legacy; contract: 4») — CI-гейт `docs-current-metrics-check` был **красный**; перегенерировано: actions **132**, OpenAPI **447/146**, тестов **25 639**, layer **debt 0 / contract 3**. Значения тестов/файлов дрейфуют вместе с параллельной работой — блок нужно перегенерировать перед коммитом |
| 3 | **CLAUDE.md** | ✅ путь гейта слоёв `tools/checks/check_layers.py` → `tools/check_layers.py` (×2); несуществующие цели `make service-schema` / `make perf` → `make check-service-docs` / `make perf-gate`; `make docs` → `make docs-mkdocs`; статус docstring-гейта «1 отсутствующий» → **0 missing**; путь `ResponseValidatorProcessor` (`validation/response.py` → `validate_response.py`); корень импорта расширений `gd_integration_tools.core.*` → `src.backend.core.*`; exception для workflow → `src.backend.sdk`; версия V22 → **V23** |
| 4 | **AGENTS.md** | ✅ корень импорта расширений (`gd_integration_tools.core.*` → `src.backend.core.*`), testkit-пакет (`gd_integration_tools.testkit.*` → `testkit.*`) |
| 5 | **ADR волны 33, устаревшие к волне 34** | ✅ ADR-0450 — добавлена таблица фактического итога (долг 37 → **0**, 3 контракта `services → dsl`); ADR-0452 — добавлены 7 дефектов обвязки и контракт exit-кодов 0/1/2/3; ADR-0453 — добавлены перемер **77.68 %** и приведение baseline к метрике гейта. Решения не переписывались |
| 6 | **`docs/roadmap/PROD_READINESS_GAPS.md`** | ✅ G1 — coverage 74 % → **77.68 %** (ADR-0453), уточнён остаток; G12 (capability не проверяется в рантайме) — **закрыт** (ADR-0456, enforcement в движке); G8 — зафиксирован объём выполненной сверки и остаток |
| 7 | **Индексы** | ✅ `docs/adr/INDEX.md` — пересобран, без диффа (400 ADR); `docs/adr/WIKI.md` — пересобран (был от 2026-09-30 со 288 ADR → **397**); `docs/reference/capabilities.md` — пересобран; `docs/index.md` — «190+ ADR» → **400**, устаревшая таблица «Status (S164)» заменена ссылками на источники правды, диаграмма слоёв приведена к канонической |
| 8 | **Битые ссылки и якоря** | ✅ `docs/analysis/index.md` (4 ссылки на несуществующие файлы), ADR-0087/0088 (неверная глубина `../../../src/` → `../../src/`), `docs/ARCHITECTURE.md` (несуществующий якорь `#stability-matrix`, «190+ ADR» → 400, `core.storage.facade` → `services.storage.facade`, несуществующие `route.use_auth()`/`route.use_secret()`); якоря с кириллицей в `docs/ai/AGENT_GUIDE.md` и `docs/workflows/index.md` — проставлены явные `{#…}` (mkdocs генерировал пустые `_N`) |
| 9 | **`mkdocs build --strict`** | ⚠️ предупреждений было **32**, стало **27**: 7 ссылок ведут на файлы вне `docs/` (`README.md`, `CHANGELOG.md`, `.security/*.policy.md`, `.shared/context/TECH_DEBT.md`, `src/**`) — они корректны при чтении репозитория, но не резолвятся в собранном сайте; 20 — разделы nav объявлены каталогами, а mkdocs 1.6 резолвит только файлы. **Требует правки `mkdocs.yml` (вне зоны документации)** |
| 10 | **Волна 35: CI/compose — отражено в документации** | ✅ `docs/MUTATION_BASELINE.md` — мутационный гейт вынесен в отдельный job `mutation` (`timeout-minutes: 45`, `MUTATION_GATE_TIMEOUT=2280`) с кэшем `mutants/` через `actions/cache`; прежнее утверждение «в CI гейт честно даёт SKIPPED, нужен отдельный job **или** кэш `mutants/`» больше не верно. ✅ `docs/ops/docker-compose-gap.md` — таблица «сервисы прода отсутствуют» заменена фактической (`clickhouse`, `open-webui`, `jupyterhub` — волна 34; `celery-worker`/`celery-beat` — за opt-in `profiles: ["celery"]`, т.к. пакет `celery` не объявлен в extras/uv.lock, а модуль с точкой входа `celery_app` в дереве отсутствует) |

**Осталось за владельцем:**

| # | Позиция | Что нужно |
|---|---|---|
| 1 | **mkdocs nav** | В `mkdocs.yml` заменить 20 записей вида `- Section: dir/` на явный перечень файлов (или подключить плагин section-index) — иначе `make docs-mkdocs` (`mkdocs build --clean --strict`) падает. Вне зоны правки документации |
| 2 | **Ссылки из `docs/**` на файлы репозитория** | 7 ссылок на `README.md`/`CHANGELOG.md`/`.security/*`/`.shared/*`/`src/**`. Варианты: `validation.links.not_found: ignore` в `mkdocs.yml` (осознанно) либо перенос этих документов в `docs/` |
| 3 | **Исторические ADR и отчёты спринтов** | 662 упоминания несуществующих путей в 308 файлах документации (455 уникальных путей; напр. `tools/checks/check_layers.py`). Переписывать историю нельзя — решение: глобальная пометка «документ — снимок на дату» + автоматический гейт «упоминания путей» с allowlist исторических файлов |
| 4 | **`ARCHITECTURE.md` (корень)** | Содержит `tools/checks/check_layers.py` (несуществующий путь). Вне зоны правки документации |

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
