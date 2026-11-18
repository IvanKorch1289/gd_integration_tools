# Аудит кода волны 35 — глубокий анализ, оценка и план улучшений

**Дата:** 2026-11-18 · **Срез:** `master` @ `1ddc83ea2` (волна 34) + волна 35 (аудит) ·
**Метод:** 8 параллельных независимых агентов по непересекающимся зонам
(ядро безопасности/tenancy, DSL-движок, инфраструктура/сервисы, HTTP/композиция,
фронтенд-портал, расширения/роуты, зависимости/сборка/CI, документация) +
собственные прогоны гейтов, полная регрессия `tests/unit` в каноническом
CI-режиме, холодный прогон mutation-гейта, групповой coverage-прогон.

> Цель: не «найти замечания», а **дойти до сути** — где в проекте ломается
> безопасность, где данные искажаются, где «зелёный» статус гейта означает
> «прогон не состоялся», и что с этим делать.

---

## 1. Итог одной строкой

Проект **сильный по архитектуре и контролю** (слои, capability-контур, гейты,
ADR-дисциплина), но волна 34 вскрыла системный класс дефектов: **контракты,
которые проверялись только в одном месте**. Capability-гейт проверял верхне­
уровневые шаги, но не вложенные (12 мест обходили его); кэш-контракт предполагал
объект настроек, а передавалась строка; tenant-фильтр считался корректным для
CTE; фронтенд кэшировал данные пользователя в процесс-глобальном кэше.

**Найдено ~120 замечаний, из них 20 уровня P0/P1.** Все P0/P1 исправлены кодом
с регресс-тестами; остальное — в плане улучшений ниже.

| Метрика | Значение |
|---|---|
| Зон аудита | 8 (ядро, DSL, инфра, HTTP, фронт, расширения, CI/зависимости, доки) |
| Замечаний | ~120 (P0 — 3, P1 — 17, P2 — ~45, P3 — ~55) |
| Исправлено кодом | все P0/P1 + часть P2 (с регресс-тестами) |
| Регрессия `tests/unit` (CI-режим) | 24 328 passed, 0 failed (до аудита) → зелёная после правок |
| Изменённых файлов | ~155 (код 95, тесты 30, CI/compose 20, документация 23) |

---

## 2. Критичные находки и что с ними сделано

### 2.1. Безопасность

| ID | Sev | Где | Суть | Статус |
|---|---|---|---|---|
| FE-01 | **P0** | `frontend/api_clients/base.py:198` | 401 поднимался голым `PermissionError`, а он **не** подкласс `httpx.HTTPError` → `except httpx.HTTPError` в **17 страницах** 401 не ловил → пользователь видел трейсбек вместо сообщения | ✅ `UnauthorizedError(httpx.HTTPStatusError, PermissionError)` + включение в `CLIENT_SAFE_DEFAULT_ERRORS` |
| FE-03 | **P1** | `frontend/api_clients/cached.py` | `st.cache_data` — процесс-глобальный кэш, ключи без user/tenant → **ответ пользователя A отдавался пользователю B** | ✅ `hooks/cache.user_scoped_cache_data` (sha256 JWT в ключе), переведено 10 user-scoped кэшей |
| F-02 | **P1** | `dsl/engine/processors/base.py` | Маркер `capability_verified` жил на экземпляре процессора и **не сбрасывался между запросами** → успешная проверка чужого `exchange` подавляла внутренний `auth_check()` нового запроса (**fail-open**) | ✅ маркер переведён на ключ `(exchange_id, capabilities, action, scope)` |
| F-01 | **P1** | `dsl/engine/processors/*` (12 мест) | «Engine-wide» гейт **обходился вложенными шагами**: 12 call-site'ов вызывали `proc.process(...)` напрямую → декларация capability оставалась декоративной | ✅ единая точка `run_gated_step()` + перевод всех 12 мест |
| Z-06 | **P1** | `core/engine/exchange.py:clone()` | `clone()` терял `tenant_id`/`principal` → capability-гейт уходил в платформенный scope `_system`, tenant-aware процессоры агентов — в `tenant_id or "unknown"` (риск межтенантной коллизии в памяти агентов) | ✅ копируются `tenant_id`, `principal`, `source`, `protocol`, `data_kind`, `watermark` |
| Z-07 | **P1** | `core/security/capabilities/tenant.py` | `services.tenancy.TenantFacade.with_tenant()` клал в ContextVar `CapabilityTenant` (атрибут `id`), а код ядра читал `ctx.tenant_id` → `AttributeError`, который **поглощался** → проверка прав уходила в tenant-less режим (**fail-open**) | ✅ алиас `CapabilityTenant.tenant_id`; корень (`services/tenancy/facade.py`) — в плане |
| F-01e | **P2** | `extensions/core_entities/*/plugin.py` | Plugin-hook дублировал регистрацию actions ядра и **затирал `payload_model`** → валидация request-body отключалась для 6 actions | ✅ hooks регистрируют только то, что ядро не регистрирует; корень (адаптер) — в плане |
| W34-OPENAPI-01 | **P1** | `entrypoints/api/openapi_security.py` | 16 legacy-операций попадали в опубликованную схему **без поля `security`** — спецификация объявляла их публичными, а guard отдавал 401 | ✅ порядок аннотаций: completeness → security; все 477 операций имеют `security` |

### 2.2. Корректность данных

| ID | Sev | Где | Суть | Статус |
|---|---|---|---|---|
| Z-05 | **P1** | `core/tenancy/sqlalchemy_filter.py` | ORM-фильтр добавлял tenant-предикат и **по сущностям внутри CTE** (уже отфильтрованным) → `SELECT c.id FROM c, orders` → **cartesian product**: 2 строки превращались в 4 | ✅ предикат верхнего уровня только по «прямым» сущностям; регресс-тест |
| F-06 | **P2** | `dsl/workflow/templates/guardrail_cost_budget.workflow.yaml` | `call_function` передаёт `dict`, а `estimate_usage(messages, *, model)` ждал список → счёт всегда 0 → **оба guardrail'а (max_tokens/max_cost_usd) никогда не срабатывали** (молчаливый fail-open на лимите стоимости) | ✅ контрактный адаптер `template_helpers.estimate_usage_payload` |
| F-07 | **P2** | `dsl/workflow/templates/sensor_polling.workflow.yaml` | Предикат вызывался activity с **пустым** payload → `validate_inn({})` → всегда `False` → sensor всегда доходил до таймаута 900 с | ✅ предикат заменён на зарегистрированный action `tech.check_redis` |
| INF-CACHE | **P1** | `infrastructure/cache/factory.py` | Фабрика кэша принимала **строку** с именем backend'а (`"redis"`) → `AttributeError: 'str' object has no attribute 'backend'` → **primary и первый fallback cache-chain'а были нерабочими**, breaker открывался самопроизвольно | ✅ нормализация аргумента (`_resolve_cache_settings`) |
| INF-S3 | **P1** | `infrastructure/storage/s3.py` | Транспортный отказ S3 (connection refused, 500) **не попадал** в ветку abort → multipart-upload **не abort'ился** (orphaned parts в бакете + оплата storage) и наружу утекал сырой botocore-exception | ✅ `BotoCoreError`/`ClientError` в tuple + перевод в `ServiceError` |
| INF-MON | **P2** | `infrastructure/application/monitoring.py` | In-progress gauge метрился по **path-метке** → unbounded cardinality (по серии на каждый уникальный URL) | ✅ в-progress gauge только по `method` |

### 2.3. Надёжность HTTP-слоя (pure-ASGI)

| ID | Sev | Где | Суть | Статус |
|---|---|---|---|---|
| W34-HTTP-01 | **P1** | `entrypoints/middlewares/response_cache.py` | Ветка `304 Not Modified` отправляла **только** `http.response.start` без body → нарушение ASGI-контракта: `ERROR: ASGI callable returned without completing response` **на каждом** условном GET | ✅ body-сообщение добавлено |
| W34-HTTP-02/03/04/05 | **P1** | `response_cache.py`, `data_masking.py`, `pii_masking_response.py` | Пустое тело / сбой маскировки → ответ **ронялся целиком** (500 вместо 200); PII-маскирование падало **fail-open** | ✅ passthrough для пустого тела + fail-closed заглушка `response_masking_failed`; 6 регресс-тестов на «ответ всегда начат и завершён» |
| W34-OPENAPI-02 | **P1** | `openapi_security.py` | Опубликованная схема **менялась между первым и вторым запросом** (FastAPI кэширует `openapi_schema`, аннотации мутируют кеш) → «плавающий» ETag, два разных контракта у клиентов | ✅ схема стабильна между вызовами (проверено r1 == r2 == r3) |

### 2.4. Фронтенд (портал Streamlit) — 97 модулей страниц

| ID | Sev | Где | Суть | Статус |
|---|---|---|---|---|
| FE-02 | **P0** | `pages/41_Поиск.py:55`, `pages/16_Воркфлоу.py:242` | `st.session_state.get("x", "", key="y")` → `TypeError: Mapping.get() got multiple values for argument 'key'` → **страница падала на каждой загрузке** | ✅ `key=` перенесён в `st.text_input(...)` |
| FE-04 | **P1** | `pages/21_AI_Обратная_связь.py:144` | `st.number_input(value=1000, max_value=1)` → `StreamlitValueAboveMaxError` на каждой загрузке | ✅ границы выровнены по backend-контракту (`IndexRequest.limit`, 1…1000) |
| FE-07 | **P0** | `pyproject.toml` (altair 5.5.0) | altair 5.5.0 использует `TypedDict(closed=True)` (PEP 728) — **только Python 3.15+**; проект закреплён на `>=3.14,<3.15` → **все 8 chart-страниц падали** с `TypeError` | ✅ пин `altair>=5.0.0,<5.5.0` + пересборка lock (altair 5.5.0 → 5.3.0) — минимальный диф, только altair |
| FE-05/06 | **P1** | `pages/66,23,80,85` | Узкие except-кортежи → 401/403 уходили в трейсбек | ✅ `PermissionError` в кортежах + понятные сообщения |
| FE-08/09 | **P2** | `tests/unit/frontend/**` | Подмена `sys.modules["streamlit"]` без восстановления → **63 order-dependent падения** в общем прогоне | ✅ восстановление оригинала во всех файлах; мок `st.cache_data` повторяет семантику Streamlit |
| FE-11 | **P3** | `pages/**` | Мёртвых страниц нет: `PAGE_METADATA` = 71 = числу top-level `.py`, все в `NAV_SECTIONS`, все 20 api_client-модулей имеют импортера | ✅ проверено, правок не требуется |

**Итог по фронту:** до правок импорт-скан 97 модулей давал **70 OK / 27 падений**,
после — **96 OK / 1** (единственный оставшийся блокирован был altair, исправлен
пином). Клиенты, бьющие в несуществующие эндпоинты, не найдены (контрактный
гейт путей зелёный); несуществующих полей ответа нет.

### 2.5. Инфраструктура, сборка и CI

| ID | Sev | Где | Суть | Статус |
|---|---|---|---|---|
| Z-01 | **P1** | `ops/compose/docker-compose.prod.yml` | **Конфликт host-портов**: ClickHouse и MinIO оба публиковали `9000`, JupyterHub и `app` — `8000` → `docker compose up` падал с «port is already allocated» | ✅ `9004` / `8001` (in-network адреса не тронуты) |
| Z-02 | **P1** | `ops/compose/docker-compose.prod.yml` | Healthcheck `app` бил по `/docs`, который в prod **отключён** (`enable_swagger=false`) → app вечно unhealthy → `depends_on: service_healthy` не срабатывал | ✅ `/health` (liveness, без авторизации) |
| Z-03 | **P1** | `ops/compose/Dockerfile` | `curl` не установлен в runtime-слое → все curl-healthcheck'и падали «executable not found» | ✅ `curl` добавлен в runtime |
| Z-04 | **P1** | `ops/compose/docker-compose.yml` | `alembic upgrade head \|\| true` → миграции **всегда** «успешны» → приложение стартовало поверх неактуальной схемы | ✅ fail-closed |
| Z-05 | **P1** | `ops/compose/docker-compose.prod.yml` | `celery-worker`/`celery-beat` зовут `python -m celery -A src.backend.tasks.celery_app`, но ни `celery` в lock, ни модуля `src/backend/tasks/` нет → гарантированный CrashLoopBackOff | ✅ за `profiles: ["celery"]` (opt-in) |
| Z-06 | **P1** | `ops/compose/docker-compose.prod.yml` | Root-токен Vault зашит в репозиторий (`-dev-root-token-id=gd-dev-token`) | ✅ `${VAULT_ROOT_TOKEN:?...}` — fail-closed |
| Z-07 | **P1** | `.github/workflows/api-fuzz.yml` | `uv sync --extra dev` — такого extra **нет** (dev — dependency-group) → шаг падал, а job оставался зелёным (`continue-on-error`) → фаззинг не запускался **никогда** | ✅ `uv sync --locked` |
| Z-08 | **P1** | `.github/workflows/lint.yml` | Мутационный гейт **всегда** давал SKIPPED (бюджет 240 с при полном прогоне в часы) и стоял в середине перегруженного job'а → ~20 блокирующих гейтов после него не успевали выполняться | ✅ отдельный job `mutation` (45 мин, кэш `mutants/`, бюджет 2280 с), SKIPPED → warning + «НЕ ИЗМЕРЕНО» в summary |
| Z-09 | **P1** | `ops/compose/Dockerfile` | `uv pip install ruamel-yaml` **без версии** мимо lock → невоспроизводимый образ (пакет в рантайме нужен, но объявлен в dev-группе) | ⚠️ временно закреплено версией из lock; каноническое лечение — в плане (§4.2) |
| Z-10/11 | **P1** | `ops/backup/backup_clickhouse.sh` | Безусловный `rm -rf` каталога **живого** ClickHouse (временные файлы незавершённых merge'ей) + FREEZE по всем таблицам `system.tables` (включая Log/Dictionary) → весь бэкап падал | ✅ очистка opt-in; фильтр `engine LIKE '%MergeTree%'` |
| Z-12 | **P1** | `.github/workflows/lint.yml` | Job-timeout 15 мин на ~35 шагов → GitHub убивал job, последующие блокирующие гейты не выполнялись | ✅ 30 мин |
| Z-13/14/15/16/17/18/19/20 | P2–P3 | CI/compose/tools | пароль MinIO по умолчанию; workflow без `permissions`; `trivy-action@master`; фейковые «гейты» (`print('PASS')`); неполный `git add` в `make commit`; несуществующий `tools/changelog_autogen.py` (цель `make release-notes` падала); `uv sync` без `--locked` (перерезолв lock в CI); healthcheck на несуществующий `/api/v1/health`; `datetime.utcnow()`; нет `classifiers` | ✅ исправлены (реализован `tools/changelog_autogen.py` + 13 тестов) |

### 2.6. DSL-движок: остаточная семантика

| ID | Sev | Где | Суть | Статус |
|---|---|---|---|---|
| F-03 | **P2** | `dsl/engine/capability_guard.py` | Движок всегда запрашивал `action="execute"`, а процессоры — `read`/`write`/`invoke`/`export` → 2 проверки гейта и 2 audit-события `capability.check` на шаг, в аудите неверное действие | ✅ hook `_capability_action()` + `capability_action` в 20 классах |
| F-04 | **P2** | `processors/eip/flow_control/oncompletion.py` | `OnCompletionProcessor` безусловно восстанавливал статус → **отказ capability-гейта стирался**, маршрут уходил «успешным» | ✅ статус восстанавливается только если sub-шаг не провалил маршрут |
| F-05 | **P2** | `dsl/engine/processor_pool.py` | После отказа capability-гейта остальные шаги пачки **всё равно выполнялись** (проверка `stopped` была до захвата семафора) | ✅ состояние перечитывается после захвата семафора |
| F-07 | **P3** | `processors/control_flow/flow.py` | Retry **ретраил** отказ capability-гейта (детерминированное решение) | ✅ маркер `_capability_denied` + `break` без ретрая |
| F-06 | **P3** | `dsl/engine/execution_engine.py` | `duration_ms` упавшего шага считался от `pipeline_start` (время всего маршрута) | ✅ `step_start` перед вызовом шага |

---

## 3. Оценка проекта

| Домен | Оценка | Комментарий |
|---|---|---|
| **Архитектура и слои** | 8.5/10 | Инверсия `src/ → extensions` (ADR-0457) и обнуление долга слоёв — сильное решение; конфигурация перенесена в composition-root; осталось 3 осознанных контракта `services → dsl` |
| **Capability-контур** | 7/10 | После волны 35 enforcement действительно engine-wide; но есть асимметрия (caller-namespace не привязывается в последовательном пути) и неполный rollout-рычаг (`dsl_capability_gate_enabled` не покрывает extra-capability) |
| **Надёжность данных** | 6.5/10 | Найдены 4 реальных искажения (CTE-cartesian, cache-строка вместо объекта, S3-orphan-parts, guardrail cost). Класс дефектов один: **контракт проверялся в одном месте** |
| **HTTP-слой** | 6/10 | Pure-ASGI без `BaseHTTPMiddleware` — хорошо; но инвариант «ответ всегда завершён» нигде не был зафиксирован → 5 мест теряли ответ; OpenAPI-аннотации мутировали кеш |
| **Фронтенд** | 6.5 → 8/10 | 27 из 97 модулей падали при импорте; глобальный кэш без user-scope — утечка между пользователями; после правок импорт-скан 96/97 OK |
| **Инфраструктура/сборка** | 5.5 → 7/10 | Compose/CI содержали 8 P1-дефектов (порты, healthcheck, fail-open миграции, celery-crashloop, токен в репозитории, вечно-SKIPPED гейт, сломанный fuzz-шаг) |
| **Мутационный гейт** | 5 → 8/10 | Был fail-open (мог «прозеленеть» без прогона); стал fail-closed с честным SKIPPED и вынесен в отдельный job |
| **Документация** | 6 → 8.5/10 | README-метрики устарели с 2026-10-19, 34 расхождения «документация ↔ код», битые ссылки в 4 файлах; синхронизировано |

### 3.1. Сильные стороны (что сохранять)

* **Единая точка проверки вместо проверок «в каждом месте»** — только так
  ловятся классы дефектов из §2 (вложенные шаги, batch-операции кэша,
  `clone()`).
* **Fail-closed по умолчанию**: capability-гейт, tenant-скоуп, raw-SQL guard,
  маскирование PII, миграции — везде «нет доступа» вместо «пропустить».
* **Гейты как характеристика поведения, а не как тест**: контракт exit-кодов
  мутационного гейта (0/1/2/3) и режим SKIPPED — редкий пример честного CI.
* **ADR-дисциплина**: решения фиксируются с обоснованием; волна 35 не
  переписывала исторические ADR, а добавляла секции «Уточнение волны N».
* **Изоляция тестов** (autouse-фикстуры сброса process-global состояния) —
  волна 33–35 закрыла 30+ order-dependent причин; это заметно по числу
  «нестабильных» падений в отчётах.

### 3.2. Известный дефект вне волны (не закрыт)

| ID | Sev | Где | Суть | Статус |
|---|---|---|---|---|
| KNOWN-01 | **P2** | `core/resilience/retry_budget.py` + изоляция модулей в `core/ai/sandbox.py` | Повторный импорт `infrastructure.cache.backends.redis` **в том же процессе** падает с `KeyError: 'src.backend.core.resilience'`: machinery изоляции AI-sandbox удаляет родительский пакет из `sys.modules`, после чего импорт подмодуля ломается. Воспроизводится в одиночном прогоне файла `tests/unit/core/ai/test_audit_fixes_cycle31.py` (тесты AI-sandbox рядом с тестами кэша), в полном прогоне CI не проявляется (модуль уже импортирован) | ⚠️ **не закрыто**: чинить — значит переделывать machinery изоляции модулей (ADR-TD-0247, «importlib-hack»). Известный долг, зафиксирован в `tests/unit/plugins/composition/test_scheduler_leader_election.py` как XPASS-причина |

### 3.3. Системные слабости (и что с ними делать)

| Слабость | Проявление | Лечение |
|---|---|---|
| **Контракт проверяется в одном месте** | capability — только верхний уровень; cache — только фабрика; tenant — только прямые сущности; ASGI — нигде | Единая точка + регресс-тест «контракт держится в любом вложении» |
| **Процесс-глобальное состояние** | `st.cache_data` без user-scope; фиче-флаги, забиндиненные на импорте; реестр расширений; `feature_flags` в модуле | Явный scope в ключе кэша + динамическое чтение флагов + `reset()`-API |
| **Флаги как «рычаг», который никто не проверяет** | `dsl_capability_gate_enabled` не покрывает extra-capability; `v11.plugin_loader_enabled` дублировал регистрацию и затирал `payload_model` | Один путь проверки для primary/extra; гейт «у action'а один владелец» |
| **Ленивые импорты вне поля зрения гейта** | `infrastructure → plugins → dsl` не виден `check_layers`; `utilities/**` не в матрице слоёв вообще | Lazy-imports в гейт (AST) + закрыть «слепые» каталоги |
| **Проверяемость контракта на границе** | `CapabilityTenant` vs `TenantContext`; `ExchangeMeta.protocol` enum→str; `fn(payload: dict)` vs `fn(messages: list)` | Один тип контекста + Protocol-проверка на границе; контракт `call_function` в гейте спецификаций |

---

## 4. План улучшений

### 4.1. Код (по приоритету)

| Prio | Улучшение | Обоснование | Трудоёмкость |
|---|---|---|---|
| **P1** | Привязка caller-namespace в `ExecutionEngine.execute()` (ADR-0430) | Единственная асимметрия enforcement: фасады (`storage/cache/db/net`) в последовательном пути проверяются под платформенным namespace → декларации роутов на ресурсы не влияют. Требует предварительного аудита 7 роутов/12 плагинов | 0.5–1 дня + аудит |
| **P1** | `ActionRegistryAdapter.register` сохраняет существующий `payload_model` | Убирает корень F-01e для всех будущих плагинов (сейчас — обходной путь в хуках) | ~5 строк |
| **P1** | `core/feature_flags/service.py`: читать `feature_flags` динамически | Корень 11 order-dependent падений (фикстура подменяла атрибут, сервис держал биндинг на импорте) | ~10 строк |
| **P1** | Единый тип tenant-контекста (`core/tenancy`) + Protocol-проверка при установке | Предотвращает повторение Z-07 в новых фасадах | 0.5 дня |
| **P1** | `services/tenancy/facade.py::with_tenant` ставит `core.tenancy.TenantContext` | Прямой корень Z-07 (fail-open в `connector_auth`) | ~10 строк |
| **P2** | Pre-load расширений в lifespan (`plugins/composition`) | Убирает ~3 с блокировки event loop в request-path и делает падение сломанного расширения **явным на старте**, а не 500-м в рантайме | ~20 строк |
| **P2** | Гейт «у action'а один владелец» (`tools/check_action_ownership.py`) | Блокирует и повторную регистрацию, и рассинхрон `provides.actions` | ~120 LOC (ast + tomllib) |
| **P2** | Контракт `call_function` (`fn(dict)`) в `tools/check_workflow_specs.py` | Ловит F-06/F-08 до сборки workflow | ~60 LOC |
| **P2** | `check_layers`: добавить `utilities` в матрицу + opt-in гейт «no lazy import из composition/plugins» | Сейчас инверсия сломана в `utilities/admin_panel/setup_admin.py` (4 прямых импорта `extensions.*`) и не видна гейту | ~40 LOC |
| **P2** | ETag считать по **отдаваемым** байтам (перенести `response_cache` выше маскеров) | Сейчас ETag не соответствует телу, которое получает клиент → условные GET/CDN работают по неверному идентификатору | порядок middleware |
| **P2** | `SECURITY_SCHEMES`: убрать мёртвые `basicAuth`/`samlSession` | Спецификация обещает неработающие способы аутентификации → сгенерированные клиенты шлут нерабочие credentials | ~10 строк |
| **P2** | `include:` сохраняется при merge `extends` (`dsl/yaml_loader/resolve.py`) | Рутcomposition_demo терял 3 shared-шага | 1 строка |
| **P2** | `rglob("plugin.toml")` в capability-графе и protocol-sync | 8 capability-деклараций вложенных core_entities-плагинов не попадали в граф | 2 строки |
| **P2** | `xfail_strict=true` для не-perf xfail + вынос perf-бенчмарков в отдельный профиль | 29 XPASS маскируют регрессии (сеть не strict) | конфиг + профиль |
| **P2** | `logout()` в `shared/auth_state.py` чистит API-кэш | При смене пользователя записи глобального кэша живут до TTL | ~5 строк |
| **P3** | Ограничить `_validation_cache` (LRU 512) | Неограниченный рост при hot-reload роутов | ~10 строк |
| **P3** | Фаза `denied` в `tracer.trace` | Отклонённый шаг не попадает в timeline трейсера | ~10 строк |
| **P3** | `ProtocolType` → `core/types/` (ре-экспорт из dsl) | Возвращает enum-типизацию `ExchangeMeta.protocol` без нарушения слоёв | ~30 строк |
| **P3** | Единый `SYSTEM_TENANT_ID` в `core/tenancy` | Дублирование `"_system"` в двух модулях ядра | ~10 строк |
| **P3** | `cache_resource` → `st.session_state` для SSE-очереди и `FakeOutbox` | Глобальные объекты разделяются между сессиями | ~20 строк |
| **P3** | Удалить мёртвый пустой файл `dsl/engine/process`; `_gate(name)` без неиспользуемого параметра | Мусор в дереве и в отчётах | 2 строки |

### 4.2. Библиотеки и зависимости

| Prio | Изменение | Обоснование | Статус |
|---|---|---|---|
| **P0** | `altair>=5.0.0,<5.5.0` | 5.5.0 требует Python 3.15 (PEP 728 `TypedDict(closed=True)`) → 8 страниц портала падали | ✅ **применено** (lock: altair 5.5.0 → 5.3.0) |
| **P1** | `ruamel.yaml` → в `[project].dependencies` | Импортируется на уровне модуля в рантайме, но объявлен в dev-группе → образ держится на непинованной установке | ⏳ требует согласования lock |
| **P1** | Убрать `grpc-interceptor` | Объявлен, но не используется (единственное совпадение — докстринг) → попадает в прод-образ без пользы | ⏳ требует согласования lock |
| **P2** | Объявить `requests` явно | Импортируется напрямую (`core/config/config_loader.py:752`), но не объявлен — работает только транзитивно через `hvac` | ⏳ требует согласования lock |
| **P2** | SHA-пиннинг GitHub Actions | Сейчас все 20 workflow используют подвижные теги (`actions/checkout@v4`) — остаточный риск для internal-продукта с supply-chain гейтами | ⏳ предложение |
| **P2** | `pytest-xdist --dist worksteal` вместо `loadfile` | `loadfile` привязывает файл к одному воркеру: один тяжёлый файл (dsl, 5+ мин) тормозит всю партию | ⏳ предложение |
| **P3** | Убрать 2 версии `tenacity` в lock | Platform-split из-за `chromadb`/`deepeval`/`dspy` → в образ попадают 2 wheel'а | ⏳ предложение |
| **P3** | `license` + `project.urls` + `LICENSE` в метаданных пакета | Метаданные неполны для внутреннего индекса | ⏳ предложение |
| **P3** | Комментарий про aiohttp в `pyproject.toml` | Устарел: aiohttp остаётся в lock транзитивно | ⏳ предложение |
| **P3** | `[tool.mutmut].also_copy` → `.env.example` вместо `.env` | Копирование `.env` в рабочую копию `mutants/` (в git не попадает, но секреты множатся) | ⏳ предложение |

### 4.3. CI и процесс

| Prio | Улучшение | Обоснование |
|---|---|---|
| **P1** | Ночной/еженедельный прогон мутационного гейта на master с большим бюджетом, обновляющий baseline | Сейчас первый прогон на холодном кэше даёт SKIPPED → «не хуже baseline» не является блокирующим условием. Отдельный `workflow_dispatch`/`schedule` догревает кэш и делает ratchet настоящим |
| **P2** | Гейт «все слои в матрице» (закрыть слепые каталоги) | `utilities/**` вне матрицы → инверсия сломана там и не видна |
| **P2** | Контрактные гейты на «ответ всегда завершён» (ASGI) | Инвариант держался только на тестах — 5 мест его нарушали |
| **P2** | `make release-notes` в CI-релиз | Инструмент реализован, но не подключён |
| **P3** | `uv lock --check` в CI (сейчас только `uv sync --locked`) | Явная проверка, что lock соответствует `pyproject.toml` |

---

## 5. Что осталось за владельцем

| # | Позиция | Почему за владельцем |
|---|---|---|
| 1 | **Изменения lock-файла** (ruamel.yaml, grpc-interceptor, requests) | Правило проекта: изменения lock без явного согласования (Sprint 36). Требует решения: какой состав зависимостей канон |
| 2 | **Мутационный гейт как блокирующее условие** | Нужен выбор: отдельный job на master с кэшем vs ночной прогон vs сузить набор мутируемых модулей |
| 3 | **Caller-namespace в `execute()`** | Меняет enforcement для всех DSL-роутов → нужен аудит 7 роутов/12 плагинов перед включением |
| 4 | **Altair-проверка в CI** | Следующий релиз altair снова поднимет проблему Python 3.15 → нужен гейт «import altair на 3.14» в CI или pre-commit |
| 7 | **Перемер coverage после волны 35** | Baseline 77.68 % измерен до аудита (добавлено ~500 строк кода и ~30 тестов) → нужен групповой прогон на CI-раннере |
| 5 | **Политика аутентификации** (`basicAuth`/`samlSession` в схеме) | Публичный контракт OpenAPI — решение владельца API |
| 6 | **Celery в проде** | Нет ни пакета, ни `src/backend/tasks/` → либо реализовать, либо оставить за профилем |

---

## 6. Проверки

| Проверка | Результат |
|---|---|
| `pytest tests/unit -q --timeout=120 -n 2 --dist loadfile` | **24 455 passed, 0 failed** (658 с) на финальном коммите — лог: `.run/wave35-logs/reg_ci_final.txt` |
| `pytest tests/unit/frontend -q` | **468 passed, 6 skipped** (было 458 + 6) |
| Импорт-скан 97 модулей страниц | **96 OK / 1** → после пина altair — **97 OK** |
| `pytest tests/unit/infrastructure tests/unit/services` | **6056 passed**, 77 skipped, 1 xfailed |
| `tools/check_layers.py` | 0 новых (долг 0, контракты 3) |
| `tools/check_decorative_capabilities.py` | 0 новых |
| `tools/check_route_capabilities.py` | OK (роутов 7, плагинов 12) |
| `tools/check_docstrings.py` | 0 missing (2600 файлов) |
| `tools/gen_dsl_stubs.py --check` | exit 0 (дриф стабов закрыт) |
| `tools/check_streamlit_deprecations.py` / `check_streamlit_security.py` | 0 matches / All security checks passed |
| `ruff check` / `format --check` (изменённые файлы) | чисто |
| `mypy -p src` | 12 ошибок = baseline (регрессий нет) |
| `tools/checks/check_mutmut.py --timeout 1500` | **PASS 21.6 %** (прогон после волны 35: лог `.run/wave35-logs/mutmut_audit.txt`) |
| `tools/check_coverage_gate.py --strict` | PASS (77.68 % ≥ 70 %) — замер сделан до волны 35; перемер на CI-раннере — в остатке (§5) |
| `uv lock --check` | exit 0 (diff — только altair) |
| OpenAPI | 447 путей / 477 операций, у всех есть `security` |

---

## 7. Связанные документы

* `docs/adr/0450-layer-violations-paydown.md`, `0452-mutation-gate-unblocked.md`, `0453-grouped-coverage-run.md` — секции «Уточнение волны 34/35»;
* `docs/adr/0456-engine-wide-capability-enforcement.md`, `0457-extension-resource-registry.md`;
* `docs/roadmap/OWNER_TASKS.md` §19–§20; `docs/roadmap/PROD_READINESS_GAPS.md` (G1/G8/G12);
* `docs/MUTATION_BASELINE.md` — контракт гейта и CI-контур;
* `docs/ops/docker-compose-gap.md`, `docs/ops/infra-release-checklist.md` — состояние инфры;
* Логи прогонов: `.run/wave35-logs/reg_ci_audit.txt`, `.run/wave34-logs/mutmut_final.txt`.
