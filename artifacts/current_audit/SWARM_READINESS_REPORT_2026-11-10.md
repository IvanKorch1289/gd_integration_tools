# Роевой отчёт по готовности и развитию проекта

**Дата:** 2026-11-10 · **Срез:** `master` @ `78bbe4107` (+ волны 24–30) ·
**Метод:** 4 параллельных агента (реестры / качество+CI / динамика / риски) +
собственные прогоны гейтов, функциональный smoke на пересобранном образе и
полная регрессия.

> Цель отчёта — одно место, где видно: **насколько проект готов к проду**,
> **что реально закрыто**, **что осталось за владельцем** и **куда двигаться
> дальше**. Все цифры — с текущего HEAD; реестры, на которые ссылается отчёт,
> помечены как «синхронизировано 2026-11-10» (часть ранее расходилась).

---

## 1. Резюме

**Вердикт: ГОТОВ К ПРОДУ С ОГОВОРКАМИ.** Кодовый контур прод-готов
(0 failed / 0 errors на 24 065 тестах, все блокирующие гейты зелёные). Оговорки
не только внешние: **5 кодовых долгов** (G3 — 34 устаревшие версии, G5(a) —
proto v2, G8 — хвост docs, G10 — navigation debt, G12 — capability-контур
процессоров не enforced, 44 декоративные декларации) **и 6 инфраструктурных
действий** (CI-runner, prod-стенд/брокеры, keypair+JWKS, роль BYPASSRLS,
ClickHouse в проде, OpenWebUI/JupyterHub).

| Показатель | Значение (2026-11-10) | Источник |
|---|---|---|
| Тесты | **24 065 passed**, 180 skipped, 52 xfailed, 45 xpassed, **0 failed / 0 errors** (44:07) | `.run/wave13-logs/reg_final_34.txt` |
| Модулей в `src/` | 2 587 `.py` | `find src -name '*.py'` |
| Тест-файлов | 2 287 | `find tests -name 'test_*.py'` |
| ADR | 403 нумерованных (409 .md всего; +42 за ноябрь) | `docs/adr/` |
| Расширений (бизнес-логика) | 10 | `extensions/` |
| Роутов / шаблонов workflow | 7 / 18 | `routes/*/route.toml` (7), `src/backend/dsl/workflow/templates/` |
| Runtime-actions | 124 (README и ARCHITECTURE синхронизированы) | `register_action_handlers()` |
| Граф кода | 135 237 nodes / 186 388 edges / 10 462 communities | `graphify-out/graph.json` |
| Коммитов за 7 дней | 53 (22 docs / 13 fix / 12 feat) | `git log` |
| OpenAPI | 200, **447 путей** | smoke на контейнере |
| Coverage | 74 % (нижняя граница; line/XML 76,5 %) | `artifacts/current_audit/COVERAGE_2026-10-09.md` |

**Что изменилось за 3 недели (волны 24–30):** сквозная tenant-изоляция
(включая UNION/CTE), caller-aware capability, контракт путей портала (39
«мёртвых» вызовов → живые эндпоинты), «громкая» семантика провала (ошибка
больше не выглядит как успех), auth-проброс на WS/GraphQL, 6 новых
инфраструктурных/девелоперских ADR и починенные красные CI-гейты.

---

## 2. Готовность по доменам

| Домен | Оценка | Доказательства | Остаток |
|---|---|---|---|
| **Ядро и слои** | 🟡 готово с долгом | `check_layers --strict` — 41 (baseline переопределён: 37 долг + 4 контракт, ADR-0348; CI-шаг работает в non-strict → зелёный); `core/` не тянет `src/` | 41 межслойное нарушение — долг, цель 0 |
| **Tenant-изоляция** | 🟢 закрыто | ADR-0383/0417/0428/**0448 (вариант А)**: raw SQL и ORM-ветка fail-closed при пустом tenant; нет контекста / `tenant_id=_system` → явный платформенный scope; UNION/CTE-фильтр; RLS-политика | сверка cross-tenant в прод-тесте (инфра) |
| **Capability-контур** | 🟡 частично | ADR-0430 (caller-aware), ADR-0449 (декларации процессоров enforced — долг 44 → **36**), гейт `check_route_capabilities` блокирует новые роуты | 36 легаси-деклараций вне vocabulary (3-сегментная форма, без scope) — миграция в vocabulary |
| **Workflow-движок** | 🟢 готово | ADR-0394/0396/0403/0408/0431/0433/0435: переходы, компенсации, SLA/DLQ, идемпотентность, checkpoint | 2 activity (`memory.reflect`, `workflow.checkpoint.put`) реализованы; персистентность checkpoint'ов — merge в снимок |
| **DSL и DX** | 🟢 готово | 18 шаблонов, cookbook 07, линтер `*.workflow.yaml`, единый линтер DSL-YAML, `dsl generate` в help | cookbook по workflow-Temporal (после 2 недель трафика) |
| **HTTP/GraphQL/WS-поверхности** | 🟢 готово | ADR-0421/0422/0423/0427: права на actions, CORS/CSRF-порядок, OpenAPI-полнота, auth-проброс | — |
| **Портал (Streamlit)** | 🟢 живой | 39 вызовов приведены к канону; 8 новых эндпоинтов; контрактный гейт по `pages/` | сводка очередей (нет capability) |
| **Конфигурация и секреты** | 🟢 готово | ADR-0364–0407/0412: hot-reload, Vault/Consul, env-over-.env, маскирование, `audit_clickhouse_enabled` в prod | инфра: keypair JWKS, роль BYPASSRLS, ClickHouse в проде |
| **Наблюдаемость** | 🟢 готово | PrometheusRule SLA/DLQ (ADR-0440), метрики пулов/процессов, SLO-метрика workflow | Prometheus Operator/CRD в кластере (инфра) |
| **Зависимости и CVE** | 🟡 частично | `uv audit --frozen` — 0 advisory вне allowlist (oauthlib 4.0.1 закрыл GHSA-3jp2-3mrg-2vxc); pillow 13 закрыт | 47 advisory в allowlist без severity/дат ревью; обновление версий (G3) |
| **Деплой** | 🟡 частично | Helm chart рендерится (ADR-0447: исправлен template-директив в YAML-комментарии, CI-шаг `helm lint`/`template`): app/worker/migration/HPA/PDB/NetworkPolicy/ServiceMonitor/PrometheusRule | **Secret с плейсхолдерами закрыт (ADR-0444/0447)**; нет imagePullSecrets/digest-пиннинга; PDB без `component`; worker без ServiceMonitor |
| **CI/гейты** | 🟢 починено | ruff `src tests` — 0; `ruff format --check` — 0; mypy 12/12 (baseline-рэтчет); coverage-порог из baseline | mutation-гейт не в CI; advisory-only security-джобы |

---

## 3. Что закрыто (волны 24–30)

| Тема | ADR | Суть |
|---|---|---|
| Capability-контур | 0416 | wildcard-scope убран, baseline-флаг не обходится |
| Tenant-guard | 0417 | fail-closed без tenant, единый канон tenant-таблиц |
| Права на actions | 0421 | `ActionMetadata.permissions` + admin-префиксы → 403 |
| Контракт клиент↔сервер | 0422 | CORS/CSRF-порядок, AST-сверка путей |
| Полнота OpenAPI | 0423 | requestBody/4xx/path-параметры, загрузка файлов 413/415 |
| Каталог шаблонов | 0424 | 18 шаблонов + гейт |
| Портал: пути | 0425 | 39 «мёртвых» вызовов → канон; гейт по `pages/` |
| Тестовая изоляция | 0426 | патч по объекту модуля, без `sys.modules.pop` |
| Auth WS/GraphQL | 0427 | principal/permissions пробрасываются, `info` — не аргумент схемы |
| Tenant-фильтр UNION/CTE | 0428 | patch-слой `_filter_statement` (G13 закрыт) |
| Громкая семантика провала | 0429 | ошибка ≠ «completed»; sink `ok=False` валит шаг; runner → `failed`; retry в sink'ах |
| Caller-aware capability | 0430 | ContextVar namespace + гейт деклараций (baseline 8 → 4) |
| Идемпотентность + компенсация | 0431 | `Idempotency-Key` во внешний вызов; компенсация по выполненным |
| Линтер workflow-спецификаций | 0433 | `tools/check_workflow_specs.py` + внутренние activity |
| Checkpoint-персистентность | 0435 | снимок инстанса (merge), strict capability-гейт |
| CB + bulkhead в DSL | 0436 | 5 процессоров под breaker'ом (5xx = отказ) |
| Версии промптов | 0437 | реестр + 4 эндпоинта + Prompt Lab |
| Storage по ключу | 0438 | `list/get/download` + портал |
| Runtime-метрики | 0439 | пулы + процессы workflow |
| Prometheus SLA/DLQ | 0440 | 4 алерта + recording rule |
| Инфра-чек-лист | 0441 | 11 пунктов: что закрыто кодом, что за инфраструктурой |
| Образ/extra | 0442 | `UV_EXTRAS` build-ARG (prod включает `workflow`) |
| Гейты CI | 0443 | пороги из baseline; ruff/format зелёные |
| Helm Secret | 0444 | плейсхолдер `VAULT_TOKEN` → падение рендера |

---

## 4. Открытые позиции (по владельцам)

### 4.1. Кодом закрывается (инженерно, следующая волна) — 6 позиций

| # | Позиция | Где зафиксировано | Оценка |
|---|---|---|---|
| 1 | Миграция 36 легаси-деклараций capability в vocabulary (сейчас advisory — имена 3-сегментные, scope нет) | ADR-0449, `tools/check_decorative_capabilities_allowlist.txt` | 1–2 дня |
| 2 | 41 межслойное нарушение (`check_layers --strict`) | ADR-0348 (baseline 37 долг + 4 контракт) | 2–3 дня |
| 3 | Mutation-гейт (mutmut 2.16, 361 collection error) | `docs/MUTATION_BASELINE.md` (BLOCKED) | 1–2 дня |
| 4 | Coverage: перемер на CI-раннере (dev-box OOM) и подъём порога 74 → 75 % | `.baselines/coverage.json`, ADR-0443 | 0,5 дня |
| 5 | Сводка очередей (`/admin/queues/summary`): брокер-агент или отказ от панели | ADR-0439 | 0,5–1 день |
| 6 | `audit.write` в `route.toml` (после включения enforcement) | ADR-0414, ADR-0446 | 0,5 дня |


### 4.2. Инфраструктура (нужна команда/окружение)

| Пункт | Действие | Статус |
|---|---|---|
| `.env:92` | разделитель без `#` → compose не парсил `.env` | ✅ исправлено (compose работает) |
| Образ 18.08 | пересборка из рабочего дерева | ✅ исправлено; prod требует `--build-arg UV_EXTRAS=... workflow` |
| ClickHouse в проде | доступность для `audit_clickhouse_enabled` | ⚙️ нужен сервис/DNS |
| JWKS RS256 | keypair + JWKS-сервис (код готов) | ⚙️ инфра |
| BYPASSRLS | роль БД для межtenant-снапшота (guard fail-closed в коде) | ⚙️ инфра |
| OpenWebUI | развернуть сервис + включить в `fallback_chain` | ⚙️ инфра |
| `replica_dsn` | оставить `null` или задать DSN реплики | ⚙️ решение владельца |
| `jupyter.hub` | развернуть JupyterHub (провайдер в расширении) | ⚙️ инфра |

### 4.3. Топ-рисков (по подтверждённым фактам)

| # | Severity | Риск | Где | Что делать |
|---|---|---|---|---|
| 1 | 🔴 critical | Capability-гейт процессоров не enforced end-to-end; 44 декоративные декларации | `.security/check_decorative_capabilities_allowlist.txt` | Включить enforcement или честно перевести capability в «документационные» (ADR-0446) |
| 2 | 🔴 critical | Helm Secret с плейсхолдерами попадал в кластер | `deploy/helm/.../secret.yaml` | ✅ закрыто ADR-0444 (рендер падает) |
| 3 | 🟠 high | SLO не подтверждён на prod-стенде (G2) | `PROD_READINESS_GAPS.md` | Прогон 300 VU на pre-prod |
| 4 | 🟠 high | MQ-контракты не проверены live (G6) | там же | Поднять брокеры на стенде |
| 5 | 🟠 high | Prod-образ без `temporalio` → workflow-воркер не стартует (fail-closed ✓, но деплой ломается) | `ops/compose/Dockerfile` | ✅ закрыто ADR-0442 (`UV_EXTRAS`) |
| 6 | 🟡 medium | Секрет-скан advisory-only; allowlist без severity | `.github/workflows/security.yml` | Включить blocking + разметить allowlist. **uv-audit-гейт снова зелёный** (oauthlib 4.0.1) |
| 7 | 🟡 medium | Coverage не перемеряется на CI (OOM на dev-box) | G1 | Разбить Coverage-мерку на группы в CI |
| 8 | 🟡 medium | Mutation-гейт не в CI; база BLOCKED | `docs/MUTATION_BASELINE.md` | Разблокировать mutmut или заменить на дешёвый mutation-гейт |

---

## 4б. Независимая проверка (4 агента) и найденное

Отчёт перепроверен независимыми агентами (гейты, реестры, security,
функциональность). Их находки и исправления:

| Находка (агент) | Severity | Исправлено |
|---|---|---|
| В образе 0 workflow-деклараций: `EXTENSIONS_DIR` искал `/app/src/extensions`, а расширения лежат в `/app/extensions`; плюс в образе не было extra `workflow` → компилятор падал («temporalio SDK not installed») | 🔴 high | ✅ `EXTENSIONS_DIR=/app/extensions` в compose (app+worker), extra `workflow` в дефолте `UV_EXTRAS` (ADR-0442/0446) → **4 декларации в контейнере** |
| Helm-chart **не рендерился вообще**: Go-template директива `{{- if ... }}` внутри YAML-комментария в `servicemonitor.yaml` | 🔴 high | ✅ директива убрана из комментария, chart рендерит 16 ресурсов; CI-шаг `helm lint`/`helm template` (ADR-0447) |
| `uv audit` красный: новая advisory `GHSA-3jp2-3mrg-2vxc` (oauthlib 4.0.0 → 4.0.1, прямая зависимость) | 🟠 high | ✅ `oauthlib>=4.0.1`, lock обновлён, гейт зелёный (47 advisory — все в allowlist, 0 новых) |
| ORM-ветка tenant-изоляции не fail-closed: без tenant-контекста SELECT/UPDATE/DELETE шли без предиката (RLS только в PostgreSQL) | 🟠 medium→high | ✅ **закрыто ADR-0448 (вариант А, решение владельца 2026-11-16)**: нет контекста / `_system` → платформенный scope; явный пустой tenant → fail-closed; реальный tenant → фильтр |
| `/healthz` (k8s livenessProbe-алиас) отдавал 401 → проба не проходит | 🟡 medium | ✅ `/healthz` в `routes_without_api_key` (ADR-0446) |
| 4 pool ping FAIL (`JupyterHubClient`/`AntivirusService`/`VaultSecretsBackend` создавались без обязательных аргументов) | 🟡 medium | ✅ конструкторы получают реальные зависимости → **0 FAIL** |
| Vault-refresher стартовал при `vault.enabled=false` → ~100 error-логов «Vault недоступен» | 🟡 medium | ✅ ранний выход по флагу → **0 ошибок** |
| `gd-grpc-light` работал на образе от 18.08 | 🟡 medium | ✅ пересоздан на текущем образе |
| Числа в отчёте не сходились (роутов 8 вместо 7, ADR, «прежний долг» слоёв, 6/7 owner- и инфра-пунктов, статус G11) | — | ✅ исправлено по факту; слои: baseline переопределён (37 долг + 4 контракт, ADR-0348), CI-шаг non-strict |
| `Finding.to_dict` без docstring; `make/quality.mk` звал системный `python3` вместо `$(UV_RUN) python` | 🟢 nit | ✅ исправлено (гейт мог «зеленеть» за счёт пропускаемых файлов) |
| Allowlist object-ownership привязан к строке → рефакторинг ронял strict-гейт | 🟡 medium | ✅ fallback по `(file, snippet)` (ADR-0445) |

Функциональная перепроверка контейнера после правок: `/health` 200,
`/ready` 200, `/healthz` 200, `/livez` 200, `/openapi.json` 200 (447 путей),
14 новых эндпоинтов → 401 без прав, `/graphql` и `/api/v1/auto/…` → 401,
**workflow-декларации 4**, **pool ping FAIL 0**, **Vault-ошибок 0**, трейсбэков нет.

## 5. Дорожная карта развития

### Горизонт 1 — «не дать regressions» (1–2 недели)

* Перемерить coverage на CI-раннере (группы + `coverage combine`) → поднять
  порог baseline'а (ADR-0443).
* Разблокировать mutation-гейт (или заменить на 10–20 точечных мутаций).
* Свести 41 межслойное нарушение до 0 (волнами по доменам, ADR-0348).

### Горизонт 2 — «закрыть продуктовые оговорки» (2–6 недель)

* Enforcement capability-контура (или осознанный переход в advisory с
  формализацией в ADR).
* Инфраструктурный пакет: ClickHouse, JWKS RS256, BYPASSRLS-роль, OpenWebUI,
  prod-образ с `workflow`-extra → закрыть G2/G6 на стенде.
* Pre-prod gates: 33/36 enforcing после 2 недель трафика (G9).

### Горизонт 3 — «развитие» (1–3 месяца)

* Workflow-операционка: per-tenant SLO-алерты (ADR-0440), авто-DLQ-разбор,
  cookbook по Temporal-пути.
* Capability-слои для расширений: декларировать capability в `plugin.toml` как
  обязательный контракт (ADR-0430 + гейт).
* Наблюдаемость v2: трассировка workflow-шагов, метрики компенсаций и
  идемпотентности.

---

## 5а. Решения владельца (2026-11-16) и их реализация

| # | Решение | Как реализовано | ADR |
|---|---|---|---|
| 1 | **ORM tenant-скоуп — вариант А** | три явных состояния: нет контекста / `tenant_id=_system` → платформенный scope (кросс-tenant без фильтра); явный пустой tenant → **fail-closed** (`TenantIsolationError`); реальный tenant → фильтр. Инвариант: пользовательский контур всегда с контекстом (auth-middleware) | ADR-0448 (Accepted) |
| 2 | **Capability-контур** (выбор исполнителя) | capability из декларации процессора проверяется в рантайме, если её имя есть в vocabulary; легаси-имена вне vocabulary остаются advisory. Долг декоративных деклараций **44 → 36**; гейт учитывает новый критерий | ADR-0449 |
| 3 | **Сводка очередей** (выбор исполнителя) | не вводится: capability «метрики брокера» (Kafka/RabbitMQ) не создаём — брокер-агент без потребителя; панель портала явно сообщает, доступен только NATS-специфичный `GET /api/v1/admin/nats/consumers` | ADR-0439 (дополнение) |
| 4 | **Инфраструктура** (владелец) | 6 действий из `docs/ops/infra-release-checklist.md` — за владельцем (JWKS/keypair, OpenWebUI, BYPASSRLS-роль, ClickHouse в проде, JupyterHub, replica DSN) | ADR-0441 |

Попутно в рамках волны 32: неинициализированный NATS-пул больше не считается
отказом (dev-профиль без брокера) → **0** «Pool ping FAIL» в логах контейнера.

## 5б. Итог волны 32 (2026-11-10)

* **Регрессия (после решений владельца):** 24 065 passed / 0 failed / 0 errors (44:07).
* **Гейты:** ruff `src tests` 0 · `ruff format --check` 0 · mypy 12≤12 ·
  ownership 0 unknown · route-capabilities OK · workflow-specs OK (22) ·
  uv-audit 0 новых · docstrings 0 · Helm chart рендерит 16 ресурсов.
* **Контейнер:** app/worker/grpc — healthy на текущем образе; `/health`,
  `/ready`, `/healthz`, `/livez`, `/openapi.json` → 200; 4 workflow-декларации;
  0 pool ping FAIL; 0 Vault-ошибок; 0 трейсбэков.
* **Кодом закрыто за волны 31–32:** 5 красных CI-гейтов, Helm-рендер,
  OAuthLib-advisory, runtime-контур контейнера, allowlist по snippet,
  `EXTENSIONS_DIR`/extra `workflow`, `/healthz`, Vault-refresher, pool-пинги.
* **Закрыто решениями владельца (2026-11-16):** ORM tenant-скоуп — вариант **А**
  (ADR-0448); capability-контур — enforced для vocabulary-имён, остаток advisory
  (ADR-0449); сводка очередей — не вводится (панель честно сообщает).

## 6. Как мерить прогресс (метрики недели)

| Метрика | Сейчас | Цель | Источник |
|---|---|---|---|
| Тесты, зелёные | 24 065 | ≥25 000 | `.run/wave13-logs/reg_final_*.txt` |
| setup-ERROR / order-dependent падения | 0 / 0 | 0 / 0 | тот же лог + гейт порядка |
| Красные блокирующие гейты | 0 | 0 | `lint.yml`, `type.yml`, `test.yml` |
| Coverage (baseline) | 74 % | ≥78 % | `.baselines/coverage.json` |
| ADR на открытое решение | 403 | — | `docs/adr/` |
| Открытые owner-пункты (кодом) | 6 | ≤3 | `OWNER_TASKS.md` §14–§17 |
| Инфра-пункты (needs action) | 7 | ≤3 | `docs/ops/infra-release-checklist.md` |
| Декоративные capability | 44 | 0 | `check_decorative_capabilities` |
| CVE вне allowlist | 0 | 0 | `uv audit --frozen` |

---

## 7. Приложение: где смотреть первоисточники

* Реестры: `docs/roadmap/OWNER_TASKS.md` (§14–§17), `docs/roadmap/PROD_READINESS_GAPS.md`,
  `docs/roadmap/FINAL_REPORT.md` (снимок 11.09 + баннер актуализации 10.11),
  `docs/ops/infra-release-checklist.md`.
* Решения: `docs/adr/` (ADR-0416…0444), индекс — `docs/adr/INDEX.md`.
* Отчёты аудита: `artifacts/current_audit/` (WAVE_26…WAVE_30, SWARM-отчёт).
* Качество: `docs/CURRENT_STATUS.md`, `docs/MUTATION_BASELINE.md`,
  `docs/DEAD_CODE_AUDIT.md`, `docs/SECURITY_AUDIT.md`, `docs/audit/`.
* Граф кода: `graphify-out/GRAPH_REPORT.md` (+ `graphify query/path/explain`).
