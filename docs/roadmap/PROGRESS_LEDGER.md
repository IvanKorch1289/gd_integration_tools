# PROGRESS_LEDGER — единый реестр задач (source of truth)

> **Создан**: 2026-09-04 (координатор роя). Правила:
> - Статусы: `TODO` → `IN_PROGRESS` → `DONE` (с командой-доказательством); регрессия в DONE → `REOPENED` (только эта задача возвращается в цикл).
> - DONE-задачи повторно не анализируются. Не доверять STATUS.md без прямой верификации командами.
> - Перед стартом любой фазы — читать файл целиком.
> - **WIP-ограничение** (обновлено 2026-09-04, вечер): в дереве только `M docs/adr/WIKI.md` + `M uv.lock` (specifier cryptography<51, остаток M3-#4 параллельной сессии) + untracked docs-отчёты; 5 исходников (pii_tokenizer* и др.) закоммичены параллельной сессией (S90-S95). lock-файл менять только через `uv lock --upgrade-package <pkg>` (прецедент S55, план M3-#5).
> - **Мульти-сессия**: в репозитории работает параллельная сессия того же роя (S90-S95: ruff 159→0, M5-#2/5/6/7/8, M4 DSL, R1 fix). Координация — ТОЛЬКО через этот ledger: перед правкой отметить IN_PROGRESS, после — DONE с доказательством; проверять свежесть HEAD перед коммитом (git log -1).

---

## Майлстоуны

| ID | Майлстоун | Статус | Дата | Доказательство (verified команда/коммит) |
|---|---|---|---|---|
| M1 | Security P0 zero-out | **DONE** | 2026-08-25 | commit `57a396d84` (22/22 P0 closed); bandit -lll: 0 HIGH (SWARM_SYNTHESIS §6, 2026-09-02) |
| M2 | Мёртвый код + god-objects + custom→library | **DONE** (кроме R1 ниже) | 2026-09-03 | Sprint 87: M2-#11 55/55 `55be1c339`; ретро `a05ad0106` |
| M3 | Актуализация зависимостей (CVE) | **DONE** | 2026-09-01 | Sprint 58 `a2ce9ce42`: cryptography 50.0.1 (PYSEC-2026-3552 закрыт), tornado 6.5.8, pypdf 6.16.2; diskcache deferral ADR-0287 |
| M4 | Coverage до 70% gate (критичные пути) | **IN_PROGRESS** | 2026-09-04 | core/auth 79.0% (≥70% ✓, Sprint 88 `3101e1a45`); overall 30.8% — НЕ достигнут; `pyproject.toml:fail_under=60` |
| M5 | High-load hardening (10 задач) | **9/10 DONE** | 2026-09-04 | S88-S95 (сессия-2) + W1/W2 (`11684f3ed` — M5-#2 реально работает), W3 (`37156dbdb` — MQTT timeouts/backpressure); M5-#10: smoke-нагрузка 0% err (ниже), полный SLO-прогон — точка решения |
| M6 | Финальная верификация + закрытие плана | **PARTIAL** | 2026-09-04 | Функциональная матрица 13 эндпоинтов (ниже), Swagger 200; осталось: позитивные JWT-сценарии, брокерные протоколы (docker), SLO-нагрузка, STATUS.md sync |

---

## Верификация 2026-09-04 (координатор, прямые команды)

| Проверка | Результат | Базовая линия | Вердикт |
|---|---|---|---|
| `uv run python -m pytest --collect-only -q` | **16777 collected, 1 error** (чистый запуск) | 16243, 0 errors | P0 REGRESSION → R1 |
| `uv run ruff check src/` | **159 errors** (130 auto-fixable) | 0-6 | P1 → T2 |
| Working tree | 7 файлов WIP + uv.lock (cryptography specifier, M3-#4 остаток) | — | Не трогать |
| bandit/vulture/layers/outdated | Не перевыполнены в этой сессии | SWARM_SYNTHESIS 2026-09-02: 0 HIGH / 0 @90% / 0 new violations / 106 outdated | Переверить в Фазе A |

**Наблюдение**: при параллельном запуске pytest с другими процессами коллекция флакует (225 errors vs 1) — импорт-тайм побочные эффекты в тестах; фиксируется как P2-наблюдение (T5), не блокер.

---

## REOPENED

| ID | Задача | Причина (REOPENED) | Дата | Статус |
|---|---|---|---|---|
| R1 (=M2-#11 частично) | `workflow_subprocess.py:26` import-time DI-вызов | Sprint 87 false claim: ModuleRegistryError ломал коллекцию тестов | 2026-09-04 | **CLOSED** параллельной сессией (S95, lazy getter `_wf_factory()`); коллекция `16782 tests, 0 errors` (verified 2026-09-04) |
| M3 (частично) | cryptography в uv.lock остался 49.0.0 | S58 поднял версию до 50.0.1, но текущий lock/venv — 49.0.0 → PYSEC-2026-3552 вернулся; CI security (pip-audit job, blocking) красный. Плюс НОВОЕ: gitpython 3.1.58 — 4 CVE (PYSEC-2026-3785..3788, fix 3.1.59+) | 2026-09-04 | TODO → **DEP1** |
| M5-#2 | GracefulShutdownMiddleware **не зарегистрирован** | S91 «CLOSED» — false claim: middleware создан+экспортирован, но отсутствует в `build_default_registry()`/`setup_middlewares.py`; drain in-flight не работает. Плюс `_INFLIGHT_COUNTER` никто не инкрементирует (телеметрия всегда 0) | 2026-09-04 | TODO → **W1+W2** |
| M2 (неполнота) | god-объекты остались: `hitl_service.py` 507 LOC/21 метод, `services/security/facade.py` 453/22, `dsl/builders/base/__init__.py` 1422 | M2 «DONE» не покрывал их (retro S64 считал иначе). Не реопен закрытых задач — новый backlog: **S3** | 2026-09-04 | TODO → **S3** |

---

## TODO — backlog (Фаза A синтез 2026-09-04, 11 доменов; P0 → P2)

### P0 (блокеры)
| ID | Домен | Задача | Оценка |
|---|---|---|---|
| **A1** | di | **32 ключа DI-реестра отсутствуют в `INFRA_MODULES`** (module_registry.py: 45 статических, провайдеры резолвят 73 уникальных). Провайдеры S84-S87 вызывают `resolve_module()` с незарегистрированными ключами → ModuleRegistryError в runtime (S3/telegram/DB/sinks/vault/audit/workflow пути). Коллекция тестов недетерминирована из-за этого же. Фикс: добавить 31 валидированный ключ (find_spec OK); `infrastructure.cdc.registry` — мёртвый (модуля/`get_default_source` не существует) → не регистрировать, dead-code. Провайдер `get_workflow_factory_module_provider` дополнительно сломан (`resolve_module("workflow").factory` — пакет не экспортирует factory) → `resolve_module("workflow.factory")` | 2h |

**Статус A1**: параллельная сессия закрыла R1+часть A1 (коммит `4b31157d4`: 2 ключа — `clients.storage.s3_pool`, `workflow.factory`, lazy-провайдер, s3 factory contract). Остаток A1 (28 ключей) — **DONE** (эта сессия, коммит `f3eb7ddaf`, 2026-09-04). Доказательство: `pytest --collect-only` → `16782 collected, 0 errors`; workflow processors 30/30; DI unit 222 passed; validate_modules → только 4 ПРЕД-существующих висячих пути (не из A1) → P2-11.

**Новая находка (REOPENED-класс, 2026-09-04)**: `B-NEW-1` P1 — `tests/unit/core/di/providers/test_top10_providers_typing.py` 2 FAIL: `ImportError: cannot import name 'observability_bridge' from src.backend.core.di.providers` — модуль отсутствует после правок провайдеров S96 (`4b31157d4`). Не связан с A1 (воспроизводится на HEAD без diff A1). Домен параллельной сессии — передано через ledger.

**DEP1 — DONE** (закрыт коммитом `97230556d` параллельной сессии, содержимое lock = мой апгрейд; верификация: `uv export | pip-audit -r --no-deps` → только diskcache PYSEC-2026-2447 (ADR-0287); cryptography 50.0.1, gitpython 3.1.61 в lock). M3 повторно CLOSED.
| **DEP1** | deps | cryptography 49.0.0 → ≥50.0.1 в uv.lock (`uv lock --upgrade-package cryptography`, ADR-0288 уже разрешает <51) + gitpython 3.1.58 → 3.1.61 (4 CVE). Доказательство: `uv run pip-audit` → только diskcache (ADR-0287) | 1h |

### P1
| ID | Домен | Задача | Оценка |
|---|---|---|---|
| W1 | entrypoints | ~~GracefulShutdownMiddleware wire~~ **DONE `11684f3ed`** (2026-09-04): pure-ASGI переписан, order=880 outermost, drain() hooked в run_shutdown step 0, drain-баг (0 in-flight → нет флага) исправлен; 7 unit-тестов, middlewares suite 519 passed | 3h |
| W2 | entrypoints | ~~Инкремент _INFLIGHT_COUNTER~~ **DONE `11684f3ed`** (вместе с W1: инкремент/декремент в __call__, get_in_flight_count живой) | 1h |
| W3 | entrypoints | ~~MQTT per-message timeout + bounded queue~~ **DONE `37156dbdb`** (2026-09-04): message_timeout=30s, max_concurrent_messages=10, max_queued_incoming_messages=1000; publish-per-connection остался P2. Попутно B-NEW-2: 4 stale-теста починены (patch-target + enabled default) | 3h |
| C2 | core/auth | ~~mobile_jwt_redis wire~~ **DONE `c684d9280`** (2026-09-04, параллельная сессия): _build_mobile_jwt_verifier() единая сборка, mobile_jwt_protections_enabled flag → RedisRevocationStore + RedisRateLimiter подключены; 2 wiring теста | 3h |
| SEC1 | security | ~~pip-audit allowlist гигиена~~ **DONE `3d6962ec5`** (2026-09-04): -PYSEC-2026-3552, -2 stale mistune ID, .bak удалён, ADR-0290 addendum; остаток — 2 записи diskcache (ADR-0287) | 1h |
| T2 | repo-wide | ~~ruff 2 → 0~~ **DONE** (verified 2026-09-04, вечер: `uv run ruff check src/` → All checks passed — закрыто батчами S90-S97) | 0.5h |
| C1 | core | ~~session.py import-time Vault-вызов~~ **DONE `ad1ef2f89`** (2026-09-04): PEP 562 lazy `__getattr__`; verify: import-only без сети, резолв при первом доступе; 106 tests passed | 2h |
| C2 | core/auth | ~~mobile JWT protections~~ **DONE `c684d9280`** (2026-09-04): флаг `mobile_jwt_protections_enabled`, `_build_mobile_jwt_verifier()` (единая сборка), factory `build_verifier_with_protections` с Redis store/limiter (fail-CLOSED); 2 wiring-теста; mobile suite 114 passed | 3h |
| S1 | services | **REJECTED с обоснованием** (2026-09-04): ключ `decorators.caching` статический и валидируется validate_modules() — R1-класса бага нет; lazy-фикс потребовал бы ломать семантику декорирования классом. YAGNI; пересмотреть только при переименовании ключа | 0h |
| S2 | services | ~~webhook idempotency + DLQ O(N²)~~ **DONE `0edb11598`** (2026-09-04): Idempotency-Key стабилен на попытки + хранится в DLQEntry + переиспользуется при retry; `_dlq_remove_many` — один LRANGE; 5 тестов | 4h |
| S3 | services/dsl | **DONE** (3/3): S3-1 hitl_service `f846b45d8` (261 LOC); S3-2 security/facade `1bac090fd` (190 + миксины); S3-3 builders/base `6d68139ae` (1422→376 + _protocols.py 1095 чистой декларации) | 16h |
| F1 | frontend | ~~12 сайтов httpx в обход BaseAPIClient~~ **PARTIAL DONE S104-S106** (2026-09-04): page 23 internal API call migrated `b22b5feba`. Page 65 external URL ping documented as correct raw-httpx use case `edd96d035` (S106). Остальные 10+ pages — DEFERRED, need per-page review (some may legitimately use raw httpx для arbitrary external endpoints, не только internal API) | 4h |
| T3 | tests | M4: overall 30.8% → 70%, `fail_under 60→70` (план M4-#3..#7); pre_prod_check gate #01 сейчас FAIL | 32h |
| T4 | hardening | Kafka max_poll_records **DONE `12deed6fb`**; MQTT W3 **DONE `37156dbdb`**; M5-claims верифицированы выборочно (см. «Функциональная и нагрузочная верификация»). Остаток: полный SLO-прогон (prod-профиль + perf extras — точка решения) | 1h |
| T5 | core/dsl | ~~Import-time I/O аудит~~ **DONE `238c83c04`** (2026-09-04): `_TAP_EXECUTOR` — мёртвый код (0 использований), удалён. `retry.py:293` singleton и `pool_health.py:19` — без I/O, детерминированы (статические ключи реестра) — оставлены (YAGNI, отказ documented) | 2h |
| DOCS1 | docs | ~~Sync~~ **DONE `8fba2d465`** (2026-09-05): ARCHITECTURE/README/STATUS/PRODUCTION_READINESS_FINAL синхронизированы; СОЗДАН docs/security/AUTH_PROTOCOL_MATRIX.md (17×auth×доказательства) | 3h | (M5 4/10 vs факт, ruff 10 vs 2), ARCHITECTURE.md (12→17 протоколов, фантомные каталоги enterprise/legacy/web3/iot, ADR 27→252, allowlist 138→~37), PRODUCTION_READINESS_FINAL.md (M2/M3 DONE bump, ruff/tests baseline), README.md (17 протоколов, pages 69/95); создать docs/security/AUTH_PROTOCOL_MATRIX.md (мёртвая ссылка M5-#9) | 3h |

### P2 (не блокируют)
| ID | Задача |
|---|---|
| P2-1 | ~~11 SyntaxWarnings в 4 тест-файлах (`\`` invalid escape) → raw strings~~ **DONE S102 `3045c82b8`** (2026-09-04): 12 warnings → raw string docstrings (5 файлов); compileall verified 0 warnings |
| P2-2 | ~~6 unused except-var~~ **DONE S102 `95e63f0c6`** (2026-09-04): trace_storage.maxlen REAL micro-bug fixed (parameter теперь используется в deque init); transactional OutboxBackend/OutboxEvent — false positive (string annotations) |
| P2-3 | ~~Ручные retry-циклы → tenacity~~ **PARTIAL DONE S105** (2026-09-04): ai_rpa.py:130, llmcall_processor.py:177 (gateway path), notify_cascade.py:115 мигрированы на make_async_retry (3/4 sites). infra outbox/dispatcher.py:289 — **VERIFIED DEFERRED per documented reason**: модуль явно использует "in-line tenacity-подобный exponential backoff (без декоратора, чтобы сохранить контроль над per-attempt-state и транзакционностью)". Per-attempt state mutations (`event.retry_count`, `event.error_class`, `event.error_message`) + stopping.wait() race-conditions делают decorator-based retry нетривиальным. Documented exception per ledger note "есть обоснование" |
| P2-4 | ~~infra/clients/base.py:14 docstring учит анти-паттерну (aioredis без pool/timeout)~~ **DONE S102 `a020d0634`** (2026-09-04): example теперь показывает max_connections + socket_connect_timeout + socket_timeout |
| P2-5 | ~~rpa/system.py логирует полную команду shell~~ **DONE S102 `32c7c8cc0`** (2026-09-04): argv парсится через shlex.split, логируется только argv[0] (бинарь); полная команда через exchange.set_property('shell_command') для audit log |
| P2-6 | ~~pre_prod_check: фактически 36 гейтов, help заявляет 38 (нумерация #14/#29 пропущена)~~ **DONE S103 `ac7a625bd`** (2026-09-04): docstring + help text обновлены 38→36; grep verified 36 gate entries |
| P2-7 | ~~SSE handler: PII stream_filter fallback молча~~ **DONE S103 `f316a64eb`** (2026-09-04): warning-log + reference на FEATURE_PII_STREAMING_FAIL_CLOSED. ~~MQTT payload без size-guard~~ **DONE S103 `f316a64eb`**: max_payload_bytes guard (1 MiB default) + early drop с warning |
| P2-8 | CI: tests/perf k6/locust есть, но не видно CI-обвязки нагрузочного (нужно для M6-#5) — **VERIFIED S106** (2026-09-04): .github/workflows/perf.yml существует с k6-smoke profile + grafana/k6-action@v0.3.1; orchestrator wrapper вокруг results (для pre-prod-check gate) отсутствует — DEFERRED до M6-#5 |
| P2-9 | ~~stream.py StreamClient 20 методов (следить)~~ **MONITORING NOTE** (S103, 2026-09-04): 22 methods в StreamClient — не рефакторим (working code, touch только при изменениях). ~~di_bridge dsl-смертные ключи без потребителей в dsl~~ **VERIFIED**: 0 imports of di_bridge в dsl/, no dead refs to clean |
| P2-10 | frontend: широкий except Exception (39/37 страницы), shared/components.py 484 LOC (_RELATED_PAGES дублирует PAGE_METADATA), старые vulture (forms.py callback, 63_Вики force) не закрыты — DEFERRED (large frontend refactor, not autonomous-scope) |
| P2-11 | ~~INFRA_MODULES 4 пред-существующих висячих пути~~ **PARTIAL DONE** (2026-09-04): monitoring.health_check, repos.files, repos.orders, external_apis.action_bus. **S102** `83ae19f09` удалил все 4, **S107 `9d84ea26e`** восстановил monitoring.health_check (создал stub модуль для tech-роута после T7 P1 REGRESSION). validate_modules → 0 missing. Оставшиеся 3 (repos.files/orders, external_apis.action_bus) — корректно удалены (test-only consumers). |
| P2-12 | ~~.worktrees/ untracked каталог~~ **DONE S102 `83ae19f09`** (2026-09-04): /.worktrees/ added to .gitignore |

### Верифицированные метрики (2026-09-04, после S90-S95)
- pytest --collect-only: **16782 collected, 0 errors** (R1 закрыт S95)
- ruff: **2 errors** (было 159)
- bandit: **0 HIGH** severity (backend+extensions), HIGH-confidence 35 (asserts, LOW)
- cryptography в lock: **49.0.0** (регрессия M3 → DEP1); pip-audit: 8 CVE / 3 пакета
- purgatory 3.0.1 + tenacity 9.1.4 используются; custom CB/rate-limit в core/infra — нет
- M5-#9 auth coverage: **закрыт по факту** (cdc/filewatcher — require_admin; scheduler/email — без HTTP-поверхности; express — глобальный AuthRequiredMiddleware) — обновить только матрицу (DOCS1)
- Graceful shutdown: uvicorn-side работает, middleware drain — не подключён (W1)

## Спринт-план (текущий цикл)

1. ~~Фаза A~~ — DONE (11 доменов, синтез выше).
2. **Фаза B** (порядок): A1 → DEP1 → SEC1 → T2 → W1+W2 → DOCS1 → S1 → C1 → далее T3/T4 саб-спринтами.
3. Фаза C после каждого батча: ревью + коллекция/pytest + ретро здесь.
4. Финиш: M4 DONE (T3), M5 DONE (верификация 10/10), M6 DONE (pre-prod-check + нагрузочный + STATUS sync), 0 открытых P0/P1.

## DONE — задачи (закрыты, не переанализируются)

| ID | Задача | Закрыта | Доказательство |
|---|---|---|---|
| M2-#1..#17, #19..#26 | God-objects, dead code, DI-миграции (55 сайтов), vulture FP-батчи | S49-S87 | ретро Sprint 64 `fea658052`, S87 `a05ad0106` (55/55) |
| M3-#1..#6 | pip-audit reverification, tornado, pypdf, cryptography+ADR-0288, diskcache deferral | S55+S58 | `3ce5743ef`, `a2ce9ce42`, `d66286f31` |
| M3 (DEP1) | cryptography 50.0.1 + gitpython 3.1.61 в uv.lock | S96 | `97230556d` |
| M4-#1 (частично) | core/auth coverage 79% ≥ 70% | S88 | `3101e1a45` |
| M4 phase 1 | low-hanging coverage: core/enums/* (10.9→94.6%), core/types/* (43.2→93.2%), core/repositories/base (0→100%), core/dsl/variable_backend (33.9→73.1%), + REAL BUG fix (qualified_name alias clash) | S97 | `9cb2333c9`, `136357102` |
| M4 phase 2-5 | core/utils/* + services/audit/* + services/cache/* + observability/correlation + scaling | S98-S101 | `d9b59354f`, `8ee407dee`, `dad9a2275`, `d2a18ab13`, `3be394de7` |
| M5-#2 (W1+W2) | GracefulShutdownMiddleware wire + INFLIGHT_COUNTER increment + 7 unit tests | S96 | `11684f3ed` |
| C2 (M1-#22) | mobile_jwt_redis wire (RedisRevocationStore + RedisRateLimiter) | parallel S96 | `c684d9280` |
| R1 (P0 REGRESSION) | workflow_subprocess.py import-time DI → lazy getter; INFRA_MODULES keys (workflow.factory, clients.storage.s3_pool); s3 client factory contract fix; scan_file/ingest_file consumers updated | S96 | `4b31157d4` |
| P2-1 | 12 SyntaxWarnings → raw string docstrings (5 файлов) | S102 | `3045c82b8` |
| P2-2 | vulture @80 dsl 3 findings: trace_storage maxlen micro-bug fixed, transactional OutboxBackend/OutboxEvent false positive | S102 | `95e63f0c6` |
| P2-4 | infra/clients/base.py docstring aioredis anti-pattern → показаны max_connections + socket_connect_timeout + socket_timeout | S102 | `a020d0634` |
| P2-5 | rpa/system.py terminal_exec argv masked в logs (только argv[0] бинарь); полная команда через exchange.set_property('shell_command') для audit | S102 | `32c7c8cc0` |
| P2-11 | 4 dangling INFRA_MODULES keys (monitoring.health_check, repos.files, repos.orders, external_apis.action_bus) удалены; validate_modules → 0 missing | S102 | `83ae19f09` |
| P2-12 | /.worktrees/ добавлен в .gitignore | S102 | `83ae19f09` |

---

## Спринт-план (текущий цикл, точка финиша — done-критерии майлстоунов)

1. **Фаза A** (идёт): рой аналитиков по 10 доменам, сверка с ledger; синтез → этот файл.
2. **Фаза B**: T1 (P0) → T2 (P1) → T3/T4 по саб-спринтам; атомарные коммиты, `IN_PROGRESS`/`DONE` здесь.
3. **Фаза C**: ревью + функциональные тесты + ретро после каждого саб-спринта.
4. **Финиш**: M4+M5+M6 DONE, R1 закрыт, 0 открытых TODO, pre-prod-check и нагрузочный тест пройдены, STATUS.md синхронен.

---

## Батч 2026-09-04 (вечер) — итоги этой сессии

| ID | Статус | Коммит | Доказательство |
|---|---|---|---|
| A1 | DONE | `f3eb7ddaf` | 28 ключей; collect 16782/0 errors; workflow 30/30; DI 222 passed |
| DEP1 | DONE | `97230556d` (сессия-2) | pip-audit по export: только diskcache (ADR-0287) |
| SEC1 | DONE | `3d6962ec5` | allowlist 2 ID; ADR-0290 addendum; .bak удалён |
| W1+W2 | DONE | `11684f3ed` | 7 unit; middlewares 519 passed |
| C1 | DONE | `ad1ef2f89` | import-only без Vault; 106 passed |
| T5 | DONE | `238c83c04` | builders 565 passed |
| T2 | DONE | (S90-S97) | ruff: All checks passed |
| W3 | DONE | `37156dbdb` | mqtt 15/16 (1 pre-existing) |
| S1 | REJECTED | — | обоснование выше (YAGNI) |

Остаток backlog: B-NEW-1 (observability_bridge ImportError — сессия-2), B-NEW-2-остаток (test_stop_cancels_task AsyncMock-квирк), W3-P2 (MQTT publish per-connection), T3 (M4 coverage — мульти-спринт), T4 (верификация M5 claims + Kafka max_poll_records), DOCS1, S2, S3, F1, P2-1..P2-12.

## Фаза C — ревью батча 2026-09-04 (вечер): PASS

Ревьюер (отдельный агент, не автор): 6/6 коммитов PASS (f3eb7ddaf, 3d6962ec5, 11684f3ed, ad1ef2f89, 238c83c04, 37156dbdb), 0 P1.
Верификация ревьюера: 549 passed/1 pre-existing fail; ruff 0; collect 16921/0 errors; mypy 0 по изменённым файлам; order=880 outermost подтверждён по семантике Starlette LIFO.

| P2 из ревью | Решение | Коммит |
|---|---|---|
| drain-таймаут не согласован с k8s-бюджетом | Исправлено: `max(5, (graceful_shutdown_timeout−15)/2)` | `f804bfe10` |
| MQTT message-задачи переживают stop() | Исправлено: stop() отменяет in-flight поколения | `f804bfe10` |
| drain 503 мимо Prometheus/OTel/security-headers | Документировано, отложено (окно ≤7.5s) | — |
| Docstring module_registry («infrastructure-модулей») неточен | Исправлено | `f804bfe10` |

Остаток открытых задач (актуально после S96-S97 параллельной сессии): T3 (M4 overall coverage — мульти-спринт), T4 (верификация M5-claims + Kafka max_poll_records; M5-#10 load test и M6 functional verification НЕ могут быть «deferred до prod» — выполняются локально через tests/perf k6/locust + make dev-light), DOCS1 (STATUS/ARCHITECTURE/README sync), S2 (webhook idempotency), S3 (god-объекты), F1 (frontend httpx→BaseAPIClient), B-NEW-1 (observability_bridge — сессия-2), P2-хвост.

## T4/M6 функциональная и нагрузочная верификация (2026-09-04, вечер)

### M6-#3 функциональные пробы — PARTIAL (живой инстанс :8000, dev_light)
Публичные (200): /health, /docs (Swagger UI), /metrics, /asyncapi, /api/v1/auth/methods.
Защищённые → 401 (негативный auth PASS): /graphql, /ws, /soap, /mcp, /events/stream (SSE),
/api/v1/webhooks/test, /api/v1/admin/users, /api/v1/health/readiness.
Осталось для полного M6-#3: позитивные сценарии c JWT (step-up login), gRPC-reflection,
MQTT/MQ-broker, email/CDC/scheduler — требуют docker compose инфраструктуры.

### M6-#4 — Swagger UI /docs → 200 DONE

### M5-#10 нагрузочный — PARTIAL (smoke, httpx-драйвер 50 conc/30s)
- 1 worker: 80 RPS, errors 0%, p50 607ms p99 1196ms (очередь)
- 4 workers: 173 RPS, errors 0%, p50 205ms p99 1248ms
- solo p50 ≈ 10ms → цепочка лёгкая; латентность под нагрузкой = масштабирование
  воркеров + dev-профиль (audit + DEBUG body-logging на каждый запрос)
- **Точка решения (Фаза A)**: валидный SLO-прогон (p99<300ms @500RPS) требует
  prod-профиль + perf extras (k6/locust отсутствуют в venv; установка —
  `uv sync --extra perf` если extra существует, иначе отдельное решение)

### Новые находки
- **P2-13**: auth-allowlist содержит /readyz, /livez — роутов нет (404); фактический
  readiness (/api/v1/health/readiness) за auth → k8s-probe без токена не пройдёт.
  Решить: публичные readiness-алиасы ИЛИ убрать из allowlist (k8s сделает auth?)
- **P2-14** (наблюдение): dev_light пишет тело ответа в DEBUG-лог на каждый запрос —
  при prod-прогоне проверить стоимость audit-логирования в p99.

## Батч 2026-09-05 — C2, T4-Kafka, S2

| ID | Статус | Коммит | Доказательство |
|---|---|---|---|
| C2 | DONE | `c684d9280` | mobile suite 114 passed (2 wiring-теста); флаг opt-in, fail-CLOSED при Redis outage |
| T4 (Kafka) | DONE | `12deed6fb` | max_poll_records=100 (конструктор+registry kwargs); CDC unit 107 passed |
| S2 | DONE | `0edb11598`+`de503e7ca` | relay suite 14 passed (5 новых): ключ стабилен на попытки, DLQ retry reuse, батч-удаление |

Урок C2: MagicMock-флаги в тестах автосоздают truthy-атрибуты — каждый новый
флаг, читаемый продовым кодом, должен явно декларироваться в тестовых mock_flags.

## Батч 2026-09-05 (продолжение) — DOCS1 DONE

DOCS1 закрыт (агент-разработчик + верификация координатора). Файлы:
ARCHITECTURE.md (11 правок), README.md (2), STATUS.md (3, только шапка),
PRODUCTION_READINESS_FINAL.md (6), НОВЫЙ docs/security/AUTH_PROTOCOL_MATRIX.md
(17 протоколов × auth × файл:строка — закрыта мёртвая ссылка M5-#9).
Примечание: src/backend/entrypoints/sse/handler.py в дереве — WIP параллельной
сессии (S103, P2-7), в коммит DOCS1 не включён.

## Новая находка 2026-09-05 — T7 (P1) — CLOSED S107

**T7**: tech-роут `/api/v1/tech/*` смонтирован (routers.py:198) и его методы
(check_database/redis/s3/bucket/graylog/smtp) зовут
`get_healthcheck_session_provider()` → `resolve_module("monitoring.health_check")`,
но ключ удалён из реестра (S102 P2-11 — модуля не существовало в то время),
bootstrap-override отсутствует → **500 на каждый вызов эндпоинта**.

**Fix (S107 `9d84ea26e`)**:
- Создан `src/backend/infrastructure/monitoring/health_check.py` stub:
  - `HealthCheckService` class с async context manager
  - 8 check_* methods (database/redis/s3/s3_bucket/graylog/smtp/rabbitmq/all)
  - `get_healthcheck_service()` lazy singleton factory
- Восстановлен `monitoring.health_check` в `INFRA_MODULES` (с T7 fix comment).

**Status**: closed — tech-роут 500 → 200 (responses возвращают False/empty для
check_*; production-grade имплементация — S107+).

**Pre-existing test failures в test_helpermethods_fix.py (NEW-1 fix regression)**
НЕ связаны с T7 правкой (verified: fail и без неё через git stash).
**FIXED S108 `d11b6ec82`** (2026-09-04): helper proxy в BaseService.__init__
применён — `self.helper = repo.helper if repo is not None else None`
(stale type annotation `HelperMethods` оставлена для backward compat).
pytest 3/3 passed.

**NEW-1c FIXED S108 `658e4778a`** (2026-09-04): CrudMixin.list() method
реализован (delegates to repo.get_paginated, returns result['items']).
`_CRUD_METHODS` обновлён ('list' добавлен). pytest test_crud_mixin_list.py: 4/4 passed
(было 4 failed).

## Фаза C — ревью батча 2026-09-05 (C2/T4/S2/DOCS1): PASS, 1 P1 → исправлен

Ревьюер (отдельный агент): вердикты — C2 PASS с P1, T4 PASS, S2 PASS, DOCS1 PASS с P2.
Регрессия: 263 passed; ruff 0.

| Находка | Решение | Коммит |
|---|---|---|
| **P1**: wrapper rate-limit игнорировал решение limiter'а (DeviceRateLimiter → RateLimitDecision, RedisRateLimiter → tuple) — per-device throttle не отклонял | Исправлено: decision-resolve + reject + 3 теста (оба контракта + pass) | `486b51e4e` |
| P2: комментарий router «fail-closed» неточен (это fallback к bare-verifier) | Исправлен | `486b51e4e` |
| P2: AUTH_PROTOCOL_MATRIX webhook-citation вела на docstring, не на код | Исправлено: `infrastructure/sources/webhook.py:104,176` | `486b51e4e` |
| P2-наблюдение: неуспешный dlq_retry пушит новую DLQ-запись при живом оригинале | Задокументировано (ключ один → получатель дедуплицирует; ротация — отдельный backlog) | — |

**Коррекция клейма C2**: до фикса `486b51e4e` revocation работал, rate limit —
нет. Итог после фикса: обе защиты активны при `mobile_jwt_protections_enabled=True`
(revocation fail-CLOSED, per-device throttle 10/60s с реальным reject).

## T7 — CLOSED (Фаза A переоценка + Фаза B фикс, 2026-09-05)

**Решение (вариант (a))**: стаб S107 (hard-coded False — ложный «нездоров»
сигнал для мониторинга) заменён ретаргетом tech-сервиса на живой
HealthAggregator: check_database/redis/s3/bucket/smtp/rabbitmq →
check_single над ConnectorRegistry-компонентами (db_main, redis_cache,
s3_main, smtp_main, eventbus_main); graylog/logging_service не зарегистрирован
→ честный False; check_all_services → check_all + статус-маппинг.

**Попутно закрыто**:
- B-NEW-1 CLOSED: observability_bridge (удалён в S96) → тесты переписаны на
  core.observability.correlation (get_correlation_id, аннотация str)
- P2-11 CLOSED полностью: стаб + ключ monitoring.health_check + провайдер
  get/set_healthcheck_session_provider удалены; repos.files/orders тесты
  переписаны на инвертированный контракт (модули не существуют — evidence S102)

**Доказательство**: di+services+interfaces 489 passed (было 5 failed);
`pytest --collect-only` → 16966/0 errors; ruff `All checks passed`;
real-path smoke: check_database/graylog=False без инфраструктуры (не 500).
Коммит `a6d601d85`.

Остаток открытых: T3 (M4 coverage — сессия-2 ведёт S97-S106+), F1 остаток
(сессия-2, S104/S106), S3 (god-objects 16h), M5-#10 SLO-прогон (prod-профиль
+ perf extras — точка решения), M6 remainder (позитивные JWT + брокерные
протоколы — docker), P2-10 хвост.

## Батч 2026-09-05 (S3-1) — сплит hitl_service

S3-1 DONE `f846b45d8`: зоны — модели (hitl_models.py 127 LOC), хранилище
(hitl_signal_store.py 189 LOC: Protocol + InMemory), оркестратор
(hitl_service.py 261 LOC, HitlService 8 методов). resolve() декомпозирован
на _publish_resolved/_signal_workflow/_emit_audit — порядок сайд-эффектов
сохранён. Re-exports сохраняют обратную совместимость (все потребители
импортируют из hitl_service — не тронуты). Verify: 82 passed
(workflows+hitl_approval+endpoints), collect 16966/0 errors, ruff 0.

## Батч 2026-09-05 (S3-2) — сплит SecurityFacade

S3-2 DONE `1bac090fd`: facade_pii.py (110, PiiFacadeMixin + audit-helper),
facade_blacklist.py (203, JwtBlacklistMixin + InMemoryJwtBlacklist),
facade.py (190, ядро: capability/signatures/secrets/certs + singleton).
Re-export `_InMemoryJwtBlacklist` сохранён (тесты импортируют из facade).

**B-NEW-3 (P2, открыт)**: 9 pre-existing падений в facade-тестах
(test_security_facade_jwt, test_security_facade — ImportError
`core.api.security.verify_signature`, не-await вызовы в тестах)
— воспроизводятся идентично на HEAD до и после сплита (9/44 в обоих).
Домен параллельной сессии (S108 NEW-* серия). Отдельно от сплита.

---

## Батч 2026-09-05 — G-MYPY Phase B (14 атомарных коммитов)

| Cluster | Закрыто | Коммит |
|---|---|---|
| CL1 | security/facade verify_signature import (149→148) | `f44981a7a` |
| CL2 | facade_blacklist get_redis_client + has-type → getattr (148→146) | `407809a32` |
| CL3 | graphql/schema _serialize_exchange cast(JSON) (146→143) | `c3f35449d` |
| CL4 | APIClient.workflows/etc properties + dict access (143→138) | `c8f38203b` |
| CL5 | workflow_setup.register_ai_gateway_singleton + shim fallback (138→135) | `dd7fe4032` |
| CL6 | admin_plugins PluginLoader.get_instance → getattr (135→134) | `e6aec587b` |
| CL7 | express/telegram __aenter__/__aexit__ cluster (134→96, -38) | `4930372c5` |
| CL8 | data_quality post-load mixin injection (96→80, -16) | `fac732b49` |
| CL9 | outbox main_session_manager typed alias (80→66, -14) | `e36912a3c` |
| CL10 | get_global_registry import fix (66→61, -5) | `a5f37f679` |
| CL11 | _AIPolicyEnforcerProtocol _is_ai_policy_enforce (61→59, -2) | `83fcfbe32` |
| CL12 | workflow compiler flow.py imports (59→54, -5) | `44a4d7591` |
| CL13 | workflow compiler activity.py _build_retry_policy (54→53, -1) | `9eaebb40d` |
| CL14 | mobile_jwt asdict для декодированных claims (53→49, -4) | `328d5c77e` |

**Итог**: 14 атомарных коммитов, 149→49 (-100 errors, -67%), без регрессий.
ruff=0, collect=16966/0 errors сохраняются на всём протяжении.

**G-MYPY хвост (49 → закрытие следующим циклом или ADR-deferral)**:
- Самые крупные файлы: services/audit/clickhouse_audit_service (6),
  cdc/poll_backend (5), entrypoints/api/generator/legacy_aliases (5),
  cdc/listen_notify_backend (4), cdc/debezium_events_backend (4),
  cdc/cdc_client_adapter (4), cdc/source (4), rag_service/search_mixin (3),
  builder_service (2), gateway_adapter (2)
- Все ошибки — singletons или 2-of-cluster (get_global_registry кластер
  уже закрыт CL10). Каждая требует отдельного анализа file-by-file.
- ADR на остаток: см. `docs/adr/0289-mypy-partial-rationale.md` (запланировано).

---

## Батч 2026-09-05 (продолжение, +S165 цикл) — G-MYPY 19→20, G-PG-RUNNER, G-FUNCTIONAL

| ID | Статус | Коммит | Доказательство |
|---|---|---|---|
| CL15 | DONE | `96d7ec664` | search_mixin shadow-dups (49→46, -3) |
| CL16 | DONE | `d7e657ef9` | gateway_adapter cast+dedup (46→44, -2) |
| CL17 | DONE | `eeaa7c798` | builder_service Any import (44→43, -1) |
| CL18 | DONE | `166078b38` | clickhouse_audit DLQWriter canonical (43→40, -3) |
| CL19 | DONE | `576591494` | legacy_aliases handler sig unif (40→39, -1) |
| CL20 | DONE | `e11c27863` | cdc/poll_backend await None-narrow (39→38, -1) |
| ADR-0289 | DONE | `4d521e0a7` | mypy partial-rationale (38-residual accept) |
| G-PG-RUNNER | DONE | `1ced37572` | ADR-0291 + 4 ponytail comments; pg-runner deprecated |
| G-FUNCTIONAL | DONE | `b6e54b011` | FUNCTIONAL_TEST_REPORT.md (130 LOC, verified) |

**Итог mypy**: 149→38 (-111 errors, -74.5%) за 20 атомарных коммитов.
ruff=0, collect=16966/0 errors сохраняются. ADR-0289 фиксирует deferral
38-residual до S172+ (bulk-stub ``core.api.extensions`` facade).

## G-CI-GATES verification 2026-09-05

| Gate | Status | Замечание |
|---|---|---|
| `ruff check src/` | ✅ PASS | 0 errors |
| `mypy src/` | ⚠️ 38 errors | per ADR-0289 (deferred, не blocker) |
| `secrets-check` | ✅ PASS | informational: bloated venv (no blocker) |
| `deps-check` | ✅ PASS | informational: 5 unused deps (gitpython, langsmith, mistune, passlib, psycopg2-binary) |
| `check-python3-syntax` | ✅ PASS | 0 errors |
| `check-task-registry` | ❌ **PRE-EXISTING FAIL** | 14+ orphan-create-task violations (R-V15-11 — требует миграции `loop.create_task`/`asyncio.create_task` → `get_task_registry().create_task`). Verified pre-existing via `git stash`. Зафиксировано в финальном отчёте как known non-blocking-dev-gate (legacy debt). |
| `test-collection-check` | ✅ PASS | 16966 collected, 0 errors |

---

## Verified baseline 2026-09-05 (plan-mode координатор, прямые команды)

HEAD = `2ca8320ef` (поверх S3-2). План: `batgirl-plastic-man-valkyrie.md`.

| # | Метрика | Значение | Команда-доказательство |
|---|---|---|---|
| 1 | ruff check src/ | **0** | `uv run ruff check src/` → "All checks passed!" |
| 2 | pytest --collect-only | 16966 tests, 0 errors | `uv run python -m pytest --collect-only -q` (~21s) |
| 3 | bandit -r src/ -lll | 0 HIGH severity, 44 HIGH confidence | `Total issues (High: 0); Total issues (by confidence High: 44); nosec=40` |
| 4 | vulture @90 / @80 | 0 / 0 | `uv run vulture src/ --min-confidence {90,80}` |
| 5 | tools/check_layers.py | 0 new, 37 legacy allowlist | прямой вызов скрипта |
| 6 | layer allowlist size | **37** entries (42 строки всего) | `wc -l tools/check_layers_allowlist.txt` |
| 7 | mypy src/ | **149 errors in 68 files** | `uv run mypy src/ 2>&1 | tail -1` |
| 8 | coverage overall | .baselines:60% / ledger:30.8% overall; `pyproject.toml:fail_under=60` | `.baselines/coverage.json: coverage_percent: 60.0` |
| 9 | frontend `core.frontend_facade` | **13 .py файлов** | `grep -rln 'core.frontend_facade' src/frontend --include='*.py' | wc -l` |
| 10 | pg_runner busy-wait | подтверждён | `pg_runner_backend.py:238, 240, 336, 338` (`asyncio.sleep(interval)`) |
| 11 | RouteBuilder Protocol | 9 из 10 миксинов на `_RouteBuilderProtocol` | compliance/middleware/fluent/deps/config/feature/resilience/transport-sources/ip_restriction — все на Protocol |
| 12 | outdated packages | **115** (raw `uv pip list --outdated | wc -l`) | ledger говорит 106 для S96 — разница в post-S96 churn |
| 13 | bandit # nosec | 40 nosec + 12 specifically disabled | `Total lines skipped (#nosec): 40; ... skipped due to specifically being disabled: 12` |

### Top-5 mypy-кластеров (для G-MYPY Phase B, 149 ошибок)

1. `services/security/facade.py:133` — `core.api.security` has no `verify_signature` (1 ошибка, real miss → B-NEW-3)
2. `services/security/facade_blacklist.py:110` — `core.api.storage` has no `get_redis_client` (1 ошибка, **NEW WIP от S3-2 сплита**)
3. `entrypoints/graphql/schema.py:216` — return `dict[str,Any]` несовместимо с `JSON`
4. 6+ frontend pages — `"APIClient" has no attribute "workflows"; maybe "_workflows", "list_workflows", or "get_workflow"`
5. `plugins/composition/lifecycle/startup_phases/services.py:41` — `workflow_setup` has no `register_ai_gateway_singleton`
6. `entrypoints/api/v1/endpoints/admin_plugins/helpers.py:53` — `type[PluginLoader]` has no `get_instance`

### WIP в дереве (не трогать — координация через ledger)

```
M docs/adr/WIKI.md                              # WIP параллельной сессии
M src/backend/services/security/facade_blacklist.py  # partial fix В-NEW-3 (1 mypy err остаётся)
```

Следующий ledger entry фиксирует старт Phase B (G-CI-GATES).

## Фаза C — ревью S3-1/S3-2: PASS (оба коммита)

Построчная сверка с pre-image: hitl — порядок сайд-эффектов, except-контракты
и re-exports сохранены; security — MRO чист, поверхность 14/14, singleton
не задвоен, `_InMemoryJwtBlacklist` — тот же класс. 9 facade-падений
pre-existing (B-NEW-3), идентичны до/после сплита.

| Находка | Решение |
|---|---|
| P2: InMemoryJwtBlacklist.clear() — sync-with на asyncio.Lock → TypeError, глотался clear_blacklist | Исправлено `72e1872ef`: async with; test_clear_blacklist починился (9→1 pre-existing fail в security) |
| P2: фасад ре-экспортирует только underscore-имя | Совпадает с pre-image — не регрессия |

Итог S3 на этот момент: hitl_service DONE (261 LOC), security/facade DONE
(190 LOC). Остаток S3: builders/base 1422 (план M2-#21, отдельный спринт).

## Батч 2026-09-05 (S3-3) — сплит builders/base, S3 CLOSED (3/3)

S3-3 DONE `6d68139ae`: anatomy-открытие — god-module был на 75% протоколами:
`RouteBuilder` (37 миксинов MRO, ~265 LOC тела) + 23 `_*Protocol`-класса
(~1080 LOC чистой декларации контрактов M2-#16). Вынос протоколов в
`_protocols.py`; `__init__` (376 LOC ≤ 400 — done-критерий M2-#21 плана)
с ре-экспортом 23 имён (cycle_30/31 импортируют из base; `_shares_prefix`
нужна __getattr__ — импортирована). Контент-ассерты cycle_30/31 обновлены
на новый модуль (честно: тесты проверяли расположение, оно изменено сплитом).

Verify: builders+cycle 582 passed; collect 16966/0 errors; ruff 0.

**S3 ГОТОВ (3/3 god-объекта)**: hitl_service 261, security/facade 190,
builders/base __init__ 376 — все ≤ 400 LOC.

## Фаза C — ревью S3-3: PASS (0 P1, 0 P2)

Построчная сверка с pre-image: секция протоколов перенесена байт-в-байт
(22 класса + _shares_prefix; отличия — только перенос импортов в шапку и
комментарий → docstring). __init__ 1-349 байт-идентичны. Циклических
импортов нет (_protocols импортирует только typing). Runtime smoke:
runtime_checkable isinstance работает, ре-экспорт — тот же класс-объект.
Верификация ревьюера: 582 passed; collect 16966/0 errors; ruff 0.

**S3 ИТОГ**: 3/3 god-объекта закрыты и отревьюены (hitl 261, security 190,
builders/base __init__ 376 LOC). Остаток открытых полос: T3 (сессия-2),
M5-#10 SLO-прогон (точка решения), M6 remainder (docker), B-NEW-3
(сессия-2), F1 остаток (сессия-2), P2-10 хвост.
