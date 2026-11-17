# Инфраструктурный чек-лист релиза (ADR-0441)

Пакет «инфра-решения»: по каждому пункту указано, что уже сделано кодом
(и где это зафиксировано), что остаётся за инфраструктурой и как проверить
готовность. Владелец: владелец платформы (внешняя команда) + владелец
продукта (решения по умолчанию).

Легенда статусов:

* **код готов** — кодовая часть сделана и покрыта тестами;
* **нужно действие** — операционная задача (ключи, роли БД, запуск сервиса);
* **не закрывается кодом** — требует инфраструктуры/решения владельца.

Имена env-переменных в чек-листе сверены с исходниками настроек:
`SEC_` (`core/config/security.py`), `DB_` (`core/config/database.py`),
`CLICKHOUSE_` (`core/config/clickhouse.py`), `OPEN_WEBUI_` (`core/config/ai.py`),
`JUPYTER_HUB_` (`core/config/services/jupyter_hub.py`).

---

## 1. `.env:92` — docker compose не парсит `.env` (нужно действие)

**Симптом.** `docker compose …` падает с ошибкой парсинга `.env`: строка 92 —
разделитель без `#`, compose считает её «KEY=VALUE» без `=`.

**Почему не чинится кодом.** `.env` содержит секреты и по правилам проекта
(AGENTS.md) не читается агентами — правка выполняется владельцем.

**Действие владельца** (одна строка, без вывода содержимого):

```bash
# закомментировать строку-разделитель (если это разделитель, а не KEY=VALUE)
sed -i '92s/^\([^#].*\)$/# \1/' .env
# проверить, что compose больше не падает на парсинге
docker compose -f ops/compose/docker-compose.light.yml config --quiet
```

**Проверка.** `docker compose … config` завершается без ошибки парсинга.

---

## 2. Образ `gd-integration-tools:light` от 18.08 (нужно действие)

**Состояние.** Dockerfile (`ops/compose/Dockerfile`) пересобирается из
рабочего дерева; сборка использует кэш Docker-слоёв и локальный кэш `uv`.
Без доступа к PyPI сборка воспроизводима только при неизменных
`pyproject.toml`/`uv.lock` (иначе нужен кэш wheels).

**Действие владельца.**

```bash
# локальный стенд (dev-light, без Temporal SDK — LiteTemporalBackend)
docker build --network=host -f ops/compose/Dockerfile -t gd-integration-tools:light .
# prod-образ: extra `workflow` (temporalio) обязателен (ADR-0442)
docker build --network=host -f ops/compose/Dockerfile \
  --build-arg UV_EXTRAS="dev-light sources-cdc workflow" \
  -t gd-integration-tools:1.0.0 .
docker image inspect gd-integration-tools:light --format '{{.Created}} {{.Id}}'
docker compose -f ops/compose/docker-compose.light.yml up -d --force-recreate app workflow-worker
```

**Проверка.** `docker image inspect` показывает свежую дату; после старта
`GET /health` → 200, `GET /ready` → 200 (либо 503 с перечнем отсутствующих
сервисов), в логах нет `Traceback` на импортах.

---

## 3. Prometheus-правила SLA/DLQ (код готов)

**Код.** `deploy/helm/gd-integration-tools/templates/prometheusrule.yaml`
(ADR-0440): алерты `WorkflowSlaHardBreach`, `WorkflowSlaSoftBreach`,
`WorkflowDlqNoWriter`, `WorkflowDlqPublishError` + recording rule
`workflow:sla_hard_breach_ratio:rate5m`. Метрики:
`workflow_sla_compliance_total{level}`, `workflow_dlq_publish_total{status}`.

**Действие владельца.**

```bash
helm upgrade --install gd deploy/helm/gd-integration-tools \
  --set prometheusRule.enabled=true
```

**Проверка.** `kubectl get prometheusrule` показывает правило; в Prometheus
`up{job=~"gd.*"} == 1`, а тестовое правило срабатывает на тестовом breach.

---

## 4. `audit.write` в `routes/*/route.toml` (закрыто кодом)

**Состояние.** Capability `audit.write` **enforced**: `AuditProcessor`
вызывает `auth_check()` до записи в sink (ADR-0454). Роут без декларации
получает fail-closed отказ; scope запроса — `audit:<action>`, декларация
роутов — `audit:*`.

**Что сделано кодом.** Декларацию `audit.write` получили все пять роутов с
шагом `audit`: `composition_demo`, `health_proxy_demo`, `hello_route`,
`jupyter_hub_run`, `test_route_w1`.

**Проверка.**

```bash
python tools/check_route_capabilities.py
python tools/check_decorative_capabilities.py --ci
python -m pytest tests/unit/dsl/engine/capability/test_audit_write_capability_adr0454.py -q
```

---

## 5. `audit_clickhouse_enabled` в проде (код готов)

**Код.** Флаг выставлен явно в `config_profiles/prod.yml`
(`features.audit_clickhouse_enabled: true`) — раньше действовал неявный
default.

**Нужно действие.** В prod должен быть доступен ClickHouse. С волны 34 в
`ops/compose/docker-compose.prod.yml` **есть сервис `clickhouse`**
(pinned-образ, healthcheck, DDL audit-трейла накатывается при первом
старте) — можно использовать его; альтернатива — внешний DSN (собственный
сервис в k8s). Профиль по умолчанию: `clickhouse.enabled=false`,
`clickhouse.host=localhost`, `clickhouse.http_port=8123` — с `localhost` в
prod писать нельзя. В prod-профиле (волна 34):
`clickhouse.enabled=true`, `clickhouse.host=clickhouse`,
`clickhouse.http_port=8123`.

```bash
# вариант A — сервис из compose.prod (пароль — из секрет-хранилища)
export CLICKHOUSE_PASSWORD=<из секрет-хранилища>

# вариант B — адрес внешнего ClickHouse (env-префикс CLICKHOUSE_)
export CLICKHOUSE_ENABLED=true
export CLICKHOUSE_HOST=clickhouse.internal.example.ru
export CLICKHOUSE_HTTP_PORT=8123
```

**Проверка.**

```bash
python -c "from src.backend.core.config.validator.profile_merge import validate_profile_config; print(validate_profile_config('prod'))"
# — пусто (ошибок профиля нет)
docker compose -f ops/compose/docker-compose.prod.yml exec app \
  python -c "import urllib.request; print(urllib.request.urlopen('http://clickhouse.internal.example.ru:8123/ping', timeout=5).read())"
# — b'Ok.\n'
```

В логах не должно быть `clickhouse_connect_failed`.

---

## 6. JWKS RS256 + keypair (код готов, нужна инфраструктура)

**Код.** Валидация JWT поддерживает асимметричные алгоритмы
(`core/auth/jwt_backend_helpers.py::_ASYMMETRIC_ALGS`), JWKS-бэкенд
собирается в `core/di/providers/auth.py::_build_jwks_cache_or_none`
(сам кэш — `core/auth/jwks_cache.py`). Для prod нужен **keypair** и
endpoint JWKS.

**Нужно действие.**

```bash
# keypair (ADR-0455): генератор в репозитории — ключи НЕ пишем в git.
# Каталог внутри репозитория (включая его корень) отклоняется генератором.
python tools/generate_jwks_keypair.py --out-dir /run/secrets/jwt --kid prod-1
# → jwt-private.pem (0600) → secret-менеджер; jwks.json → ConfigMap/Secret
# JWKS — сервис, отдающий {"keys":[...]} по service-DNS (только https!)
```

Проключи в проде (env-префикс `SEC_`):

```bash
export SEC_ALGORITHM=RS256
export SEC_JWKS_URL=https://idp.internal.example.ru/.well-known/jwks.json
```

`SEC_JWKS_URL` обязан быть **https**: `http://` отклоняется
`JwksConfigurationError` (SSRF-guard, `core/auth/jwks_cache.py`).

**Проверка.** Токен, подписанный приватным ключом, принимается сервисом;
токен с чужим ключом — отклоняется. Проверка самого JWKS-документа:

```bash
python - <<'PY'
import json, pathlib
doc = json.loads(pathlib.Path("/run/secrets/jwt/jwks.json").read_text())
print("kid:", doc["keys"][0]["kid"], "alg:", doc["keys"][0]["alg"])
PY
```

---

## 7. Service-DNS для sidecar'ов (код готов)

**Код.** ADR-0412: loopback-записи удалены, sidecar'ы адресуются по
service-DNS (`app.opentelemetry_endpoint: http://otel-collector:4317`,
`waf.clamav_host`).

**Проверка (внутри контейнера app).**

```bash
docker compose -f ops/compose/docker-compose.prod.yml exec app \
  python -c "import socket; print(socket.gethostbyname('otel-collector'))"
```

---

## 8. OpenWebUI endpoint (код готов, нужен сервис)

**Код.** Провайдер `ai_providers.open_webui` с `base_url:
http://open-webui:3000` (ADR-0412); в `fallback_chain` prod **не включён**,
пока сервис не развёрнут (иначе откат ушёл бы на несуществующий endpoint).
Env-префикс — `OPEN_WEBUI_` (`core/config/ai.py`).

**Нужно действие.** Развернуть OpenWebUI в сети compose/k8s, задать
адрес/ключ и только после этого добавить провайдера в `fallback_chain` prod.
С волны 34 в `ops/compose/docker-compose.prod.yml` **есть сервис
`open-webui`** (pinned-образ, healthcheck, `WEBUI_SECRET_KEY` — из
секрет-хранилища); в `fallback_chain` prod провайдер **не** включён —
включать только после реального развёртывания (иначе откат ушёл бы на
несуществующий endpoint).

```bash
export OPEN_WEBUI_BASE_URL=http://open-webui:3000
export OPEN_WEBUI_API_KEY=<из секрет-хранилища>
export OPEN_WEBUI_SECRET_KEY=<из секрет-хранилища>
```

**Проверка (из контейнера app).**

```bash
docker compose -f ops/compose/docker-compose.prod.yml exec app \
  python -c "import urllib.request; print(urllib.request.urlopen('http://open-webui:3000/api/version', timeout=5).status)"
# — 200
```

---

## 9. `replica_dsn` (решение владельца)

**Код.** ADR-0407: `replica_dsn: null` — допустимое прод-значение
(реплика не обязательна). Валидатор профиля проверяет формат, если значение
задано. Env-префикс — `DB_` (`core/config/database.py`).

**Нужно действие (опционально).** При появлении реплики задать
`DB_REPLICA_DSN`; до этого — оставить `null`.

```bash
export DB_REPLICA_DSN='postgresql+asyncpg://user:pass@replica.internal:5432/appdb'
```

**Проверка.** Значение подхватывается настройками (в выводе — маскированное):

```bash
python -c "from src.backend.core.config.settings import settings; print(settings.database.replica_dsn)"
```

---

## 10. BYPASSRLS для межtenant-снапшота (код готов, нужна роль БД)

**Код.** Роль готова в репозитории (ADR-0455): `ops/sql/bypassrls_role.sql` —
роли `snapshot_service` (NOLOGIN, BYPASSRLS) и `snapshot_service_login`
(LOGIN), `GRANT SELECT` на таблицы снимка (`orderkinds`, `users`, `orders`,
`certs`, `cert_history`). Скрипт идемпотентен и приводит атрибуты к канону
при каждом применении.

**Код.** `infrastructure/resilience/snapshot_job.py` — fail-closed: перед
выборкой проверяется наличие `BYPASSRLS` у роли; риски и режимы описаны в
`docs/ops/snapshot-bypassrls-role.md` (предпочитается `per-tenant` — он RLS
не обходит вовсе).

**Нужно действие.**

```bash
# пароль — из секрет-хранилища, в репозитории не хранится
psql -v snap_password="$SNAP_DB_PASSWORD" -v snapshots_db=appdb \
     -f ops/sql/bypassrls_role.sql
# DSN снапшот-job'у: snapshot.service_dsn / env SNAPSHOT_SERVICE_DSN
```

**Проверка.**

```bash
psql -tAc "SELECT rolname, rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname LIKE 'snapshot_service%';"
# snapshot_service|f|t
# snapshot_service_login|t|f
psql -tAc "SELECT table_name FROM information_schema.role_table_grants WHERE grantee='snapshot_service' ORDER BY 1;"
# cert_history / certs / orderkinds / orders / users
```

Без роли снапшоты просто не создаются (fail-closed) — это безопасно.

---

## 11. `jupyter.hub` capability (код готов)

**Код.** Провайдер capability `jupyter.hub` живёт в расширении
`extensions/jupyter_hub/` (ADR-0415 — расширения не могут импортировать
core напрямую), клиент — `core/clients/jupyter_hub.py`. Параметры —
yaml-группа `jupyter_hub`, env-префикс `JUPYTER_HUB_`
(`core/config/services/jupyter_hub.py`).

**Нужно действие.** Развернуть JupyterHub в кластере и указать его URL и
токен в профиле. С волны 34 в `ops/compose/docker-compose.prod.yml` **есть
сервис `jupyterhub`** (pinned-образ 4.x, healthcheck, конфиг
`ops/compose/jupyterhub/jupyterhub_config.py`); в prod-профиле:
`jupyter_hub.enabled=true`, `jupyter_hub.base_url=http://jupyterhub:8000`.
Токен обязателен: без `JUPYTER_HUB_API_TOKEN` профиль fail-closed
(валидатор `JupyterHubSettings`), escape-hatch — `JUPYTER_HUB_ENABLED=false`.
Аутентификация хаба сейчас `DummyAuthenticator` — до публикации порта
заменить на корпоративный IdP (OIDC/LDAP).

```bash
export JUPYTER_HUB_ENABLED=true
export JUPYTER_HUB_BASE_URL=https://jupyter.internal.example.ru
export JUPYTER_HUB_API_TOKEN=<из секрет-хранилища>
```

**Проверка.**

```bash
docker compose -f ops/compose/docker-compose.prod.yml exec app \
  python -c "import urllib.request; print(urllib.request.urlopen('https://jupyter.internal.example.ru/hub/api/health', timeout=5).status)"
# — 200
```

---

## 12. Гейт готовности инфраструктуры (волна 34)

**Код.** `tools/check_infra_readiness.py` — fail-closed проверка **конфигурации**
(без обращения к живой сети и без чтения Vault) по 6 пунктам этого
чеклиста: JWKS (https-требование), режим снапшота `service-role` +
`service_dsn`, ClickHouse, OpenWebUI (+ согласованность `fallback_chain`),
JupyterHub, `database.replica_dsn`.

```bash
make infra-readiness              # exit 0 — конфигурация согласована
make infra-readiness ARGS=--strict  # предупреждения тоже блокируют
.venv/bin/python tools/check_infra_readiness.py --profile prod --json
```

Семантика: **fail** (exit 1) — небезопасное или несогласованное значение
(`http://` в JWKS-URL, loopback-хост ClickHouse, `service-role` без
валидного DSN); **warning** (exit 0, блокирует только `--strict`) —
невыполненное инфра-действие или отсутствующий секрет (секреты живут в
Vault, поэтому их отсутствие в CI — не ошибка конфигурации).

Гейт не подключён к CI-пайплайнам (только `Makefile`) — решение о
подключении за владельцем.

---

## Итог

| # | Пункт | Статус |
|---|---|---|
| 1 | `.env:92` | ✅ **исправлено** (разделитель закомментирован, compose работает) |
| 2 | Образ от 18.08 | ✅ **пересобран** (ADR-0442: extras через build-ARG; prod требует extra `workflow`) |
| 3 | Prometheus-правила SLA | **код готов** (ADR-0440) |
| 4 | `audit.write` в роутах | ✅ **закрыто кодом** (ADR-0454: enforcement в процессоре + декларации 5 роутов; волна 34 — engine-wide enforcement, ADR-0456) |
| 5 | `audit_clickhouse_enabled` | ✅ сервис `clickhouse` добавлен в `compose.prod` (волна 34); альтернатива — внешний DSN; нужен пароль |
| 6 | JWKS RS256 + keypair | код готов (ADR-0455); нужны keypair, JWKS-сервис (https) и `SEC_JWKS_URL`/`SEC_ALGORITHM` |
| 7 | Service-DNS sidecar'ов | **код готов** (ADR-0412) |
| 8 | OpenWebUI | ✅ сервис `open-webui` добавлен в `compose.prod` (волна 34); нужен `OPEN_WEBUI_API_KEY`/`OPEN_WEBUI_SECRET_KEY`; в `fallback_chain` prod включать после развёртывания |
| 9 | `replica_dsn` | решение владельца (null допустим); env — `DB_REPLICA_DSN` |
| 10 | BYPASSRLS | код готов (ADR-0455: `snapshot_service`/`snapshot_service_login`); нужна роль БД и DSN снапшота |
| 11 | `jupyter.hub` | ✅ сервис `jupyterhub` добавлен в `compose.prod` (волна 34); нужен `JUPYTER_HUB_API_TOKEN` + замена `DummyAuthenticator` на IdP |
| 12 | Гейт готовности инфры | ✅ **код готов** (волна 34): `make infra-readiness` — проверяет конфигурацию 6 пунктов; в CI не подключён |
