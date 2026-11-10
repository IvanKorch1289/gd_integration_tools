# Инфраструктурный чек-лист релиза (ADR-0441)

Пакет «инфра-решения»: по каждому пункту указано, что уже сделано кодом
(и где это зафиксировано), что остаётся за инфраструктурой и как проверить
готовность. Владелец: владелец платформы (внешняя команда) + владелец
продукта (решения по умолчанию).

Легенда статусов:

* **код готов** — кодовая часть сделана и покрыта тестами;
* **нужно действие** — операционная задача (ключи, роли БД, запуск сервиса);
* **не закрывается кодом** — требует инфраструктуры/решения владельца.

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

## 4. `audit.write` в `routes/*/route.toml` (решение владельца)

**Состояние.** Capability `audit.write` **не enforced**: процессор аудита не
задаёт `required_capability`, а ADR-0414 делает capability opt-in для
workflow-шагов. Объявлять её в роутах сейчас означало бы декоративную
декларацию (её отметит гейт `check_decorative_capabilities`).

**Решение по умолчанию (рекомендация):** не объявлять до появления
enforcement; при включении enforcement — объявить `audit.write` в роутах,
использующих шаг `audit` (роуты с шагом audit: `composition_demo`,
`health_proxy_demo`, `hello_route`, `test_route_w1`).

**Проверка (после решения).** `python tools/check_route_capabilities.py` —
без нарушений; `python tools/check_decorative_capabilities.py --ci` — чисто.

---

## 5. `audit_clickhouse_enabled` в проде (код готов)

**Код.** Флаг выставлен явно в `config_profiles/prod.yml`
(`features.audit_clickhouse_enabled: true`) — раньше действовал неявный
default.

**Нужно действие.** В prod должен быть доступен ClickHouse (сервис
`clickhouse` в `docker-compose.prod.yml` либо внешний DSN) — иначе трейл
audit-событий не пишется.

**Проверка.** `python -c "from src.backend.core.config.validator.profile_merge import validate_profile_config; print(validate_profile_config('prod'))"`
— пусто; в логах нет `clickhouse_connect_failed`.

---

## 6. JWKS RS256 + keypair (код готов, нужна инфраструктура)

**Код.** Валидация JWT поддерживает асимметричные алгоритмы
(`core/auth/jwt_backend_helpers.py::_ASYMMETRIC_ALGS`), JWKS-бэкенд есть в
`core/auth/auth_selector.py`. Для prod нужен **keypair** и endpoint JWKS.

**Нужно действие.**

```bash
# keypair для прод-JWT (в vault/secret-менеджере, не в репозитории!)
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out jwt-private.pem
openssl rsa -pubout -in jwt-private.pem -out jwt-public.pem
# JWKS — сервис, отдающий {"keys":[...]} по service-DNS
```

Проключи в проде: `JWT_JWKS_URL`, `JWT_ALGORITHM=RS256` (проверить точные
имена в `docs/config/SETTINGS_GUIDE.md`).

**Проверка.** Токен, подписанный приватным ключом, принимается сервисом;
токен с чужим ключом — отклоняется.

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

**Нужно действие.** Развернуть OpenWebUI в сети compose/k8s и только после
этого добавить провайдера в `fallback_chain` prod.

---

## 9. `replica_dsn` (решение владельца)

**Код.** ADR-0407: `replica_dsn: null` — допустимое прод-значение
(реплика не обязательна). Валидатор профиля проверяет формат, если значение
задано.

**Нужно действие (опционально).** Задать `DATABASE_REPLICA_DSN` (или
аналогичный env) при появлении реплики; до этого — оставить `null`.

---

## 10. BYPASSRLS для межtenant-снапшота (код готов, нужна роль БД)

**Код.** `infrastructure/resilience/snapshot_job.py` — fail-closed: перед
выборкой проверяется наличие `BYPASSRLS` у роли; процедура выдачи роли и
риски описаны в `docs/ops/snapshot-bypassrls-role.md`.

**Нужно действие.** Создать роль/пользователя с `BYPASSRLS` и выдать DSN
снапшот-job'у (либо не выдавать — тогда снапшоты просто не создаются, что
безопасно).

---

## 11. `jupyter.hub` capability (код готов)

**Код.** Провайдер capability `jupyter.hub` живёт в расширении
`extensions/jupyter_hub/` (ADR-0415 — расширения не могут импортировать
core напрямую), клиент — `core/clients/jupyter_hub.py`.

**Нужно действие.** Развернуть JupyterHub в кластере и указать его URL в
профиле (`jupyter_hub.*`).

---

## Итог

| # | Пункт | Статус |
|---|---|---|
| 1 | `.env:92` | ✅ **исправлено** (разделитель закомментирован, compose работает) |
| 2 | Образ от 18.08 | ✅ **пересобран** (ADR-0442: extras через build-ARG; prod требует extra `workflow`) |
| 3 | Prometheus-правила SLA | **код готов** (ADR-0440) |
| 4 | `audit.write` в роутах | решение владельца (рекомендация: не объявлять до enforcement) |
| 5 | `audit_clickhouse_enabled` | **код готов** (ADR-0441) |
| 6 | JWKS RS256 + keypair | код готов, нужна инфраструктура |
| 7 | Service-DNS sidecar'ов | **код готов** (ADR-0412) |
| 8 | OpenWebUI | код готов, нужен сервис |
| 9 | `replica_dsn` | решение владельца (null допустим) |
| 10 | BYPASSRLS | код готов, нужна роль БД |
| 11 | `jupyter.hub` | **код готов** (ADR-0415) |
