# ADR-0412 — Service-DNS для sidecar'ов и endpoint-контракты (волна 23, кластер C2)

* Статус: Accepted (2026-11-02, волна 23, кластер C2 — sidecar-DNS и endpoint-контракты)
* Cycle: 182 (волна 23)
* Связан с:
  - ADR-0371 (прод-значения, оставленные осознанно: loopback-host'ы sidecar'ов, `open_webui`, `replica_dsn`),
  - ADR-0403 (прод-валидатор: проверки значений в `profile_merge.py`),
  - ADR-0407 (исполняемые контракты прод-значений: WAF-allowlist, AI-fallback, `replica_dsn`),
  - ADR-0375 (валидация merged-профиля; значения YAML = дефолты моделей)
* Затрагивает:
  - `config_profiles/base.yml`, `config_profiles/prod.yml`, `config_profiles/staging.yml`,
  - `src/backend/core/config/validator/profile_merge.py`,
  - `src/backend/core/config/waf.py`, `src/backend/core/config/ai.py` (дефолты моделей),
  - `deploy/k8s/service.yaml`, `deploy/k8s/configmap.yaml`,
  - `docs/config/SETTINGS_GUIDE.md`, `docs/roadmap/OWNER_TASKS.md`,
  - `tests/unit/core/config/test_adr0412_sidecar_dns.py`,
    `tests/unit/core/config/test_adr0412_deploy_manifests.py`

---

## Контекст

Три owner-задачи из `docs/roadmap/OWNER_TASKS.md` § 3 (3.2, 3.3, 3.4) висели
как «документированные ограничения», потому что требовали инфраструктуры.
Проверка кода показала, что часть из них — дефект конфигурации, а не
инфраструктурный факт:

1. **Sidecar'ы на loopback.** `waf.clamav_host` = `127.0.0.1` и OTel-экспорт
   на loopback. В k8s `127.0.0.1` — это **сам pod**, а не соседний
   контейнер: sidecar, вынесенный в отдельный Deployment, по loopback
   недоступен. Конфиг при этом не падает — он молча указывает на
   несуществующий сервис (AV-сканирование пропускается при `fail_open=true`,
   телеметрия не уходит). Loopback-записи в `waf.allow_hosts` prod/staging
   были «оправданы» этой же loopback-зависимостью — то есть мёртвая запись
   держала на себе мёртвую конфигурацию.
2. **OpenWebUI без endpoint'а.** `open_webui.base_url` = `http://localhost:3000`
   (тот же loopback). Провайдер исключён из `ai_providers.fallback_chain`
   prod-профиля, но endpoint в конфиге оставался бессмысленным: включить
   провайдера «как есть» было нельзя, а как включить правильно — не
   описано.
3. **DSN read-реплики.** `database.replica_dsn: null` — корректное
   прод-значение («реплика не развёрнута»), но формат DSN был известен
   только по одному примеру в комментарии `prod.yml`; в `base.yml`,
   `staging.yml`, `SETTINGS_GUIDE.md` и deploy-манифестах его не было.

Инфраструктура (Deployment'ы sidecar'ов, Service'ы, реплика) остаётся за
владельцем, но **контракт имён** (service-DNS) и **исполняемая проверка**
этого контракта — зона кода. ADR-0407 уже показал этот приём: «прод-значение
нельзя закрыть кодом» ≠ «прод-значение нельзя проверять кодом».

---

## Решение

### 1. Sidecar'ы адресуются по service-DNS (prod/staging)

* **Конфигурация.** `waf.clamav_host` = `clamd`,
  `app.opentelemetry_endpoint` = `http://otel-collector:4317` — дефолты в
  `config_profiles/base.yml`, явно продублированы в `prod.yml`/`staging.yml`.
  Значения конфигурируемы: env `WAF_CLAMAV_HOST` /
  `APP_OPENTELEMETRY_ENDPOINT` (env-префиксы моделей `WAF_` / `APP_`).
  Модельные дефолты (`core/config/waf.py`, `core/config/ai.py`) приведены к
  тем же значениям — иначе рассыпался бы контракт ADR-0375 «значения YAML =
  дефолты моделей» (гейт `test_yaml_group_coverage.py`).
* **Проверка (новое).** В prod/staging хост включённого sidecar'а не должен
  быть loopback — CRITICAL:
  * `waf.clamav_host_loopback_in_prod` (при `waf.clamav_enabled=true`);
  * `app.opentelemetry_endpoint_loopback_in_prod` (при заданном endpoint'е).

  Выключенный clamd и пустой OTel-эндпоинт (телеметрия выключена) проверку
  не проходят — это не endpoint'ы.
* **Allowlist.** Loopback-записи удалены из `waf.allow_hosts` prod/staging:
  оправдывать их было нечем, а `waf.allow_hosts_loopback_without_local_dependency`
  (ADR-0407) теперь срабатывает на любой loopback-записи в prod/staging.
  Соответственно из allowlist-а инвариантов
  (`tests/unit/core/config/test_profile_invariants.py`) убраны пути
  `waf.allow_hosts`, `waf.clamav_host`, `open_webui.base_url` — loopback в
  них теперь нарушение.
* **Deploy.** `deploy/k8s/service.yaml` — ClusterIP-Service `clamd` (3310),
  `otel-collector` (4317/4318), `open-webui` (3000) с селекторами по
  `app.kubernetes.io/name`. `deploy/k8s/configmap.yaml` — те же хосты
  (`WAF_CLAMAV_HOST`, `APP_OPENTELEMETRY_ENDPOINT`, `OPEN_WEBUI_BASE_URL`).

### 2. OpenWebUI: явный endpoint, провайдер вне цепочки до развёртывания

* **Endpoint.** `open_webui.base_url` (env `OPEN_WEBUI_BASE_URL`) — по
  умолчанию `http://open-webui:3000` (service-DNS), объявлен явно в
  `base.yml`, `prod.yml`, `staging.yml`.
* **Fallback-цепочка.** Провайдер **не** входит в
  `ai_providers.fallback_chain` prod/staging-профиля, пока сервис не
  развёрнут: откат на несуществующий endpoint выглядит как «LLM отвечает»
  (ADR-0407). В staging цепочка объявлена явно (раньше наследовалась из
  `base.yml` вместе с `open_webui`).
* **Процедура включения** (документирована в `SETTINGS_GUIDE.md`): развернуть
  Deployment + Service `open-webui` → проверить `curl
  http://open-webui:3000/api/v1/config` из pod'а → вернуть `"open_webui"` в
  `ai_providers.fallback_chain` → `validate-profile prod` → 0 CRITICAL.

### 3. DSN read-реплики: значение — факт, формат — контракт

* `database.replica_dsn` остаётся `null` («реплика не развёрнута») — это
  инфраструктурный факт, а не незаполненное поле; валидатор (ADR-0407)
  трактует `null` как допустимое значение.
* **Шаблон DSN** задокументирован в комментариях `base.yml`/`prod.yml`/
  `staging.yml`, в `SETTINGS_GUIDE.md` и закомментированным примером в
  `deploy/k8s/configmap.yaml`:
  `postgresql+asyncpg://<user>:<pass>@<replica-host>:5432/<db>`.
  В `data` ConfigMap его нет: DSN содержит пароль (Secret/Vault).
* Непустое значение — только реальный (не loopback) хост реплики
  (`database.replica_dsn_invalid`), значение маскируется в дампах
  (ADR-0378 / ADR-0381).

---

## Альтернативы

* **Оставить loopback и считать sidecar'ом в том же pod'е.** Отклонено:
  конфигурация обслуживает развёртывание, где sidecar'ы вынесены в
  отдельные Deployment'ы (Service-DNS); `127.0.0.1` в pod'е — это сам pod,
  и AV-сканирование/телеметрия молча деградируют. Для pod-совместного
  sidecar'а loopback корректен — но это другой сценарий развёртывания,
  который можно выразить через `WAF_CLAMAV_HOST=127.0.0.1` в dev.
* **Только документация (без проверки валидатора).** Отклонено: ADR-0407
  показал, что комментарий в YAML не удерживает инвариант — «зелёный»
  `validate-profile` не означал «конфиг корректен».
* **Переименовать код `ai_providers.fallback_chain_localhost`** (ADR-0403)
  в «более общий» вид. Отклонено: код нарушения — публичный контракт
  (документация, дашборды); его семантика не менялась, а изменился лишь
  дефолт endpoint'а провайдера. Существующие гейты сохраняют проверку
  loopback-правила (фикстура в тестах теперь задаёт loopback явно).
* **Добавить в модель флаг «сервис развёрнут»** (`open_webui.deployed`).
  Отклонено: конфигурационный флаг, который обязан совпадать с reality,
  — источник нового класса расхождений; факт «сервис не развёрнут» выражен
  составом fallback-цепочки и процедурой включения.
* **Перенести Service-объекты в отдельный файл** `deploy/k8s/service-sidecars.yaml`.
  Отклонено: договорённость репозитория — один `service.yaml` на набор
  Service'ов; отдельный файл добавил бы ещё одну точку синхронизации.

---

## Последствия

* `manage.py validate-profile prod` → 0 CRITICAL, 1 WARNING
  (`waf.clamav_fail_open_in_prod`, pre-existing); `... staging` → 0 CRITICAL,
  0 WARNING. Exit code 0 в обоих случаях.
* Локальный dev без Kubernetes требует явного переопределения:
  `waf.clamav_enabled: false` (или `WAF_CLAMAV_HOST=127.0.0.1`) и
  `app.opentelemetry_endpoint: ""` (`dev_light` уже переопределяет).
  Дефолты `base.yml` ориентированы на k8s-окружение.
* `Service`-объекты sidecar'ов объявлены, но их Deployment'ы — инфраструктурная
  часть: без них `clamd`/`otel-collector`/`open-webui` не резолвятся, и
  приложение деградирует (fail-open по clamd, отсутствие телеметрии).
* Факт «OpenWebUI не развёрнут» выражен конфигурацией (провайдер вне
  fallback-цепочки), а не отдельной проверкой валидатора: до развёртывания
  добавление провайдера в prod-цепочку не даёт CRITICAL — но и не даёт
  «успешного» ответа (endpoint не резолвится).

---

## Проверка

* `tests/unit/core/config/test_adr0412_sidecar_dns.py` — контракт валидатора
  (prod/staging: loopback → CRITICAL; service-DNS → OK; выключенный clamd
  не проверяется), ключи «модель ↔ YAML» (каждый затронутый YAML-ключ —
  поле pydantic-модели; env-имена выводятся из env-префиксов), значения по
  умолчанию (service-DNS), `open_webui` вне fallback-цепочки,
  `replica_dsn: null` и задокументированный шаблон DSN.
* `tests/unit/core/config/test_adr0412_deploy_manifests.py` — Service для
  `clamd`/`otel-collector`/`open-webui` (порт + selector) и те же хосты в
  `deploy/k8s/configmap.yaml`; DSN реплики — только закомментированным
  примером.
* `python manage.py validate-profile prod|staging` → exit 0, 0 CRITICAL.
* Гейты: `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` (baseline 41); `tools/checks/mypy_budget.py`
  (бюджет 30); `ruff`; `tools/check_docstrings.py` → 0.

---

## Открытое (owner-задачи)

1. **Deployment'ы sidecar'ов** (prod/staging). Владелец: эксплуатация.
   Критерии: `clamd` и `otel-collector` развёрнуты с лейблами
   `app.kubernetes.io/name: clamd` / `otel-collector`; `kubectl get svc
   clamd otel-collector` — ClusterIP в namespace приложения; из pod'а
   приложения `nc -z clamd 3310` и `nc -z otel-collector 4317` — успех.
2. **OpenWebUI.** Владелец: эксплуатация/AI-платформа. Критерии: сервис
   развёрнут и отвечает; провайдер возвращён в `ai_providers.fallback_chain`
   prod-профиля; `validate-profile prod` → 0 CRITICAL.
3. **DSN read-реплики.** Владелец: DBA/эксплуатация. Критерии: выдан
   async-DSN реплики; `database.replica_dsn` (или `DB_REPLICA_DSN`) указывает
   на реальный host; `snapshot.enabled: true` в prod включён по runbook'у.
4. **Режим отказа clamd.** Владелец: эксплуатация/безопасность. Критерий:
   в prod выбран `waf.clamav_fail_open: false` (fail-closed) либо осознанно
   оставлен `true` с принятым риском (сейчас — WARNING
   `waf.clamav_fail_open_in_prod`).

---

## Связи

* ADR-0371 — прод-значения, оставленные осознанно (источник owner-задач).
* ADR-0375 — merged-валидация профиля; значения YAML = дефолты моделей.
* ADR-0378 — маскирование секретов в дампах.
* ADR-0381 — `replica_dsn` как секрет (`SecretStr`).
* ADR-0403 — прод-валидатор: JWT-алгоритм и AI-fallback.
* ADR-0407 — исполняемые контракты прод-значений.
* `docs/config/SETTINGS_GUIDE.md` — «Sidecar-DNS и endpoint-контракты (ADR-0412)».
* `docs/roadmap/OWNER_TASKS.md` § 3 — реестр owner-задач по прод-значениям.
