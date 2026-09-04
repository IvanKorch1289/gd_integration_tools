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
| M5 | High-load hardening (10 задач) | **TODO** | — | 0/10 (Sprint 88 ретро); план: PRODUCTION_READINESS_FINAL.md §M5 |
| M6 | Финальная верификация + закрытие плана | **TODO** | — | 0/N; план: PRODUCTION_READINESS_FINAL.md §M6 |

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
| W3 | entrypoints | MQTT handler: per-message timeout + bounded queue (сейчас медленный action блокирует весь цикл); publish — новое соединение на каждое сообщение (P2) | 3h |
| SEC1 | security | ~~pip-audit allowlist гигиена~~ **DONE `3d6962ec5`** (2026-09-04): -PYSEC-2026-3552, -2 stale mistune ID, .bak удалён, ADR-0290 addendum; остаток — 2 записи diskcache (ADR-0287) | 1h |
| T2 | repo-wide | ruff 2 → 0 (остаток после S91 батча 159→0) | 0.5h |
| C1 | core | `core/database/session.py:28` import-time `_get_main_session_mgr()` → сетевой вызов Vault при каждом импорте модуля (источник флака/задержек). Lazy-фикс | 2h |
| C2 | core/auth | `mobile_jwt_redis.py` (Redis revocation + rate limiter, M1-#22) не подключён в `entrypoints/api/mobile/router.py` — защиты мертвы в проде; встроенный `DeviceRateLimiter` not multi-pod safe | 3h |
| S1 | services | `dadata.py:15` import-time `get_response_cache_provider()` — последний import-time DI в services; lazy-фикс по паттерну R1 | 1h |
| S2 | services | webhook_relay: outbound retry без Idempotency-Key (дубли доставки); dlq_retry O(N²) LRANGE-обход | 4h |
| S3 | services/dsl | God-объекты вне M2: hitl_service 507/21, security/facade 453/22, builders/base 1422 (сплит по плану M2-#21) | 16h |
| F1 | frontend | 12 сайтов httpx в обход BaseAPIClient (нет retry/JWT/центр. конфига) + страница 23 читает os.environ напрямую | 4h |
| T3 | tests | M4: overall 30.8% → 70%, `fail_under 60→70` (план M4-#3..#7); pre_prod_check gate #01 сейчас FAIL | 32h |
| T4 | hardening | M5 остаток: 9/10 закрыто параллельной сессией (S90-S95); верифицировать claims + закрыть пробелы (Kafka max_poll_records, MQTT W3) | 4h |
| T5 | core/dsl | Import-time I/O аудит: `_TAP_EXECUTOR` (content_mixin.py:32), `retry.py:293` singleton, `pool_health.py:19` — module-level ресурсы; tests/ чист (инвентарь пуст) | 2h |
| DOCS1 | docs | Sync: STATUS.md (M5 4/10 vs факт, ruff 10 vs 2), ARCHITECTURE.md (12→17 протоколов, фантомные каталоги enterprise/legacy/web3/iot, ADR 27→252, allowlist 138→~37), PRODUCTION_READINESS_FINAL.md (M2/M3 DONE bump, ruff/tests baseline), README.md (17 протоколов, pages 69/95); создать docs/security/AUTH_PROTOCOL_MATRIX.md (мёртвая ссылка M5-#9) | 3h |

### P2 (не блокируют)
| ID | Задача |
|---|---|
| P2-1 | 11 SyntaxWarnings в 4 тест-файлах (`\`` invalid escape) → raw strings |
| P2-2 | 6 unused except-var (infrastructure) — войдут в ruff-батчи; vulture @80: dsl 3 (trace_storage `maxlen` игнорируется — микробаг, eip/transactional dead imports) |
| P2-3 | Ручные retry-циклы → tenacity: dsl ai_rpa.py:130, notify_cascade.py:115, llmcall_processor.py:177; infra outbox/dispatcher.py:289 (есть обоснование — опционально) |
| P2-4 | infra/clients/base.py:14 docstring учит анти-паттерну (aioredis без pool/timeout) |
| P2-5 | rpa/system.py логирует полную команду shell (`cmd=%s`) — маскировать argv, оставив argv[0] |
| P2-6 | pre_prod_check: фактически 36 гейтов, help заявляет 38 (нумерация #14/#29 пропущена) |
| P2-7 | SSE handler: PII stream_filter fallback молча (добавить warning-лог); MQTT payload без size-guard |
| P2-8 | CI: tests/perf k6/locust есть, но не видно CI-обвязки нагрузочного (нужно для M6-#5) |
| P2-9 | stream.py StreamClient 20 методов (следить); di_bridge dsl-смертные ключи без потребителей в dsl |
| P2-10 | frontend: широкий except Exception (39/37 страницы), shared/components.py 484 LOC (_RELATED_PAGES дублирует PAGE_METADATA), старые vulture (forms.py callback, 63_Вики force) не закрыты |
| P2-11 | INFRA_MODULES: 4 пред-существующих висячих пути (validate_modules): monitoring.health_check, repos.files, repos.orders, external_apis.action_bus — ModuleNotFoundError вместо RegistryError при resolve; find real paths или удалить ключи |
| P2-12 | .worktrees/ untracked каталог в корне — инвентаризировать и убрать/игнорировать |

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
| M5-#2 (W1+W2) | GracefulShutdownMiddleware wire + INFLIGHT_COUNTER increment + 7 unit tests | S96 | `11684f3ed` |
| R1 (P0 REGRESSION) | workflow_subprocess.py import-time DI → lazy getter; INFRA_MODULES keys (workflow.factory, clients.storage.s3_pool); s3 client factory contract fix; scan_file/ingest_file consumers updated | S96 | `4b31157d4` |

---

## Спринт-план (текущий цикл, точка финиша — done-критерии майлстоунов)

1. **Фаза A** (идёт): рой аналитиков по 10 доменам, сверка с ledger; синтез → этот файл.
2. **Фаза B**: T1 (P0) → T2 (P1) → T3/T4 по саб-спринтам; атомарные коммиты, `IN_PROGRESS`/`DONE` здесь.
3. **Фаза C**: ревью + функциональные тесты + ретро после каждого саб-спринта.
4. **Финиш**: M4+M5+M6 DONE, R1 закрыт, 0 открытых TODO, pre-prod-check и нагрузочный тест пройдены, STATUS.md синхронен.
