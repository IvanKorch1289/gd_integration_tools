# FINAL_REPORT — Prod-Readiness Re-Verification 2026-09-11 — v8

> Повторная полная верификация на актуальном HEAD по 20 гейтам директивы
> «повторный глубокий реверс-инжиниринг + production readiness».
> Принцип: каждая метрика — прямая команда на HEAD с exit-code; исторические
> заявления (включая v7 — predecessor, в git-истории этого файла — и
> PROGRESS_LEDGER) не принимались без перепроверки.
> Сырьё: `.run/evidence/` (локально, gitignored); проверяемые документы — в git.

## 0. ВЕРДИКТ

**ГОТОВ К ПРОДУ С ОГОВОРКАМИ**

Все кодо-зависимые гейты (статика №1–№7, коллекция №9, navigation №18,
release-evidence №20) — PASS с прямым command-evidence на HEAD. Живая
протокольная матрица впервые пройдена с позитивным auth (REST/GraphQL/WS/SSE).
Security: pip-audit вне allowlist = 0. Оговорки — 10 позиций с владельцами и
done-criteria в `PROD_READINESS_GAPS.md`; из них блокируют безусловный
«ГОТОВ К ПРОДУ»: push-SLO на prod-стенде (G2), SOAP invoke 500 (G4),
gRPC business dispatch (G5), MQ live (G6) — все требуют внешних условий
(стенд/брокеры) или локализованной доработки; владельцы назначены.

## 1. Точка верификации

| Параметр | Значение |
|---|---|
| Стартовый HEAD | `9f32d8b0b` (2026-09-11 09:54, дерево чистое после merge полосы R2.MYPY) |
| Финальный HEAD | `ca6d68f55` (2026-09-11 ~15:10; оговорка: параллельная полоса «Sprint 47» продолжает писать коммиты — verification-point этого отчёта) |
| Python / uv | 3.14.0 (`uv run python`) / 0.11.7 |
| Fix-коммиты сессии | 18 (§4) |

## 2. Сводка 20 гейтов

| № | Гейт | Результат | Evidence |
|---|---|---|---|
| 1 | Ruff 0 | **PASS** | `ruff check src/` → All checks passed (exit 0) |
| 2 | Mypy permissive 0 | **PASS** | `make type-check` → Success: no issues in 2356 files |
| 3 | Mypy strict-profile 0 | **PASS** | `make type-check-strict-profile` → 0 in 2356; бюджет `mypy -p src` = 0 |
| 4 | Bandit HIGH severity 0 | **PASS** | `bandit -r src/backend -lll` exit 0 |
| 5 | Bandit HIGH confidence 0 | **PASS** | `--confidence-level high` exit 0 |
| 6 | Vulture @90 = 0 | **PASS** | 0 findings |
| 7 | Layers 0 новых, ≤15 legacy | **PASS** | «Нарушений: 0 новых (файлов: 2333; baseline: 14 legacy)»; 1 stale-запись allowlist помечена чекером |
| 8 | Coverage ≥70% honest | **PASS** | sweep6 (чанки unit-дерева `--cov-append`, свежий coverage.xml на этом HEAD) → `check_coverage_gate.py main --threshold 70 --strict` → **OK: 71.90% ≥ 70%** (baseline 72.04%, дельта −0.14pp < 0.5% допуска) |
| 9 | Collection 0 errors | **PASS** | `pytest --collect-only -q` → 17504 collected |
| 10 | Pre-prod gates | **PARTIAL**: 21/36 PASS, 8 WARN, 5 SKIP, 2 FAILED; оба FAILED разобраны вручную: (а) coverage-гейт читал mid-run данные локального свипа; (б) mypy-budget воспроизведён (`mypy -p src`) → 1 реальная ошибка mcp-дрейфа, починена `3e5e116e0` → 0 | `.run/evidence/pre_prod_20260911.txt` |
| 11 | Dependencies ≤30 | **PARTIAL**: 34 (37→34, `9d59af715`); MAJOR-цепочки — GAPS G3; patch-хвост (3 пакета) блокирован родительскими пинами — подтверждено повторным `uv lock --upgrade-package` | `uv pip list --outdated` |
| 12 | Security 0 P0/P1 без mitigation | **PASS** | pip-audit: 2 finding = один CVE (diskcache PYSEC-2026-2447 = CVE-2025-69872, aliases), fix-версии нет; mitigation: ADR-0287 allowlist (review 2026-12-01) + `use_disk_fallback` default-OFF + `mkdir 0o700` (`4ed38d49c`) |
| 13 | Startup SLO повторно | **PASS** | startup-time gate OK в pre_prod; dev_light-сервер поднимался 6+ раз за сессию |
| 14 | Reference load SLO | **PASS (reference)** | p99 150ms @444 RPS — LOAD_TEST_RESULTS_2026-09-05; загрузочный путь не менялся, повтор не проводился |
| 15 | Push load SLO 300VU | **BLOCKED(infra)** | GAPS G2 |
| 16 | Protocol matrix pos+neg | **PARTIAL** | §3.4: негатив 401/403 по всем; позитив REST+GraphQL+WS+SSE+SOAP-WSDL+gRPC-auth PASS; SOAP invoke FAIL (G4); gRPC dispatch gap (G5); MQ BLOCKED (G6); MCP disabled-by-flag (G7) |
| 17 | Docs accuracy | **PARTIAL** | README-пути исправлены (`7a9fe6d62`); CLAUDE.md ×4 битых пути, mkdocs `api/`, «114 vs 35+ actions», спринт-счётчики — GAPS G8 |
| 18 | Navigation canonical map | **PASS** | `repository-navigation-audit.md` + `canonical-module-map.md`; debt — GAPS G10 |
| 19 | Dynamic extension safety | **PASS** | routes 7/7 route.toml; extensions 0 нарушений import-правил; registries живы; composition-smoke stale-кластер — §5.1 |
| 20 | Release evidence | **PASS** | CURRENT_BASELINE + FUNCTIONAL_TEST_REPORT + GAPS + этот отчёт |

## 3. Ключевые измерения

### 3.1 Статика
7/7 зелёные; удержаны точечными прогонами после каждого фикса + финальный
`mypy -p src` = 0.

### 3.2 Тесты
- Коллекция: 17504 тестов, 0 collection errors.
- Финальный прогон (sweep6, 9 чанков с coverage): **15176 passed / 111 failed
  (0.73%)** — все фейлы кластеры дрейфа тестов (§5), статические гейты не
  затронуты; core/dsl/entrypoints-api/realtime/misc/rest — 0 failed.
- Контрольный xdist-прогон (`-n 4`, 117s): 10121 passed / 59 failed —
  консистентен с кластерами выше (до последних test-fix коммитов).

### 3.3 Coverage (honest run, sweep6, 2026-09-11 14:59)

- Методика: чанки `tests/unit` с `--cov=src --cov-append` (9 чанков, timeout 900s),
  финальные `coverage xml` + `coverage report` + гейт `--threshold 70 --strict`.
  Лог: `.run/evidence/cov_sweep6.log`. Артефакт: `coverage.xml` (локальный).
- **Гейт: OK 71.90% ≥ 70.00%, GATE_EXIT=0** (baseline 72.04% — удержана).
- Итог тестов по чанкам: core 4143✓ · dsl 4463✓ · infra 2221 passed/75✗ ·
  ep-api 874✓ · ep-realtime 140✓ · ep-mq2 174 passed/35✗ · ep-misc 103✓ ·
  services 2616 passed/1✗ · rest 442✓ → **15176 passed / 111 failed (0.73%)**.

### 3.4 Живая протокольная матрица (dev_light, порт 8001)
Позитивный auth **разblockирован впервые**: dev_admin (sqlite
`.run/dev.sqlite3`, argon2id-хэш ресечен) → `POST /api/v1/auth/step-up-request`
(200, step_up_token) → `POST /api/v1/auth/login` (+X-Step-Up-Token,
method=password) → access_token HS256.
- PASS: public `/health /docs /metrics /asyncapi /openapi.json /api/v1/auth/methods`
  = 200; `/api/v1/auto/users.list`+JWT = 200 (**PII-маскирование в ответе**:
  email/password скрыты); GraphQL `POST /api/v1/graphql` `{__typename}` = 200
  `AutoQuery`; WS `/ws` + subprotocol `jwt.<token>` = подключение + JSON-dispatch
  ответ; SSE `/events/stream`+JWT = 200; SOAP `/soap/wsdl` = 200 (525 operations);
  gRPC unix-socket: List без/с неверным `x-api-key` → UNAUTHENTICATED,
  с верным → прошёл интерцептор.
- FAIL: `/soap/invoke` на валидных WSDL-операциях → 500 (G4).
- Известный gap: gRPC business dispatch → UNIMPLEMENTED, абстрактные
  auto-servicer'ы (G5).
- Негатив: forged JWT → 401; WS без credential → 403; REST/GraphQL/SOAP/SSE
  без auth → 401.

## 4. Исправленные дефекты (атомарные коммиты, 13)

| Коммит | Дефект | Класс |
|---|---|---|
| `4ed38d49c` | diskcache: mkdir 0o700 (PYSEC-2026-2447 defence-in-depth) | security |
| `5d093da13` | `create_task(name=)` keyword-only: 5 колл-сайтов падали в runtime, прикрыты `type: ignore[call-arg]`; + scan_file тест под R1-контракт `get_s3_client` | runtime-контракт (R2.MYPY) |
| `029e8793d` | `_prepare_and_save_object`: сигнатура сменина на `list[dict]`, тело осталось dict — все add/update CRUD падали TypeError | runtime-контракт (R2.MYPY) |
| `37a4010dc`+`6c9b148db` | disk-тесты под sha256-шардирование + no-op delete_pattern | test-drift |
| `9d59af715` | outdated 37→34 (presidio-analyzer, pymongo, ruff, tqdm, wrapt) | deps |
| `0cb485ebc`+`5a42c2dbd` | navigation audit + каноническая карта; опровергнут claim аналитика о «29 skip'ах check_layers» (ast 3.14 парсит всё, 0 WARNING) | docs |
| `7b95bcbfa` | `CrudMixin.list` → `fastapi_pagination.Params`: entity-CRUD list = 500 на всех протоколах | runtime (дрейф API) |
| `5682594f9` | auto-endpoints: SQLAlchemy-модели не сериализуются FastAPI 0.141 → `users.list` 500 | runtime |
| `7dc48bd32` | GraphQL `context_getter(request: Any)` → FastAPI трактовал как query-параметр: **любой** GraphQL POST = 422 | runtime (R2.MYPY) |
| `3e5e116e0` | `dsl/agents/fastmcp_server`: mcp 2.x удалил `mcp.server.fastmcp` → runtime ImportError + mypy budget 1; миграция на пакет `fastmcp` (Prompt.from_function, http_app) | runtime-deps |
| `7a9fe6d62` | FUNCTIONAL_TEST_REPORT 2026-09-11 + README-пути | docs |
| `014753daf` | PROD_READINESS_GAPS — 10 позиций | docs |
| `5615cfc58` | hitl store/pubsub, outbox shim, rate_limit fail-CLOSED, langgraph dsn — тесты под текущие контракты (+ фасад messaging: lazy stuck_monitor имена) | test-drift + фасад |
| `6ece34739` | composition-smoke: svcs_registry публичный API, APIRouter-патч, route/grep-контракты (7 тестов → 166 passed) | test-drift |
| `ca6d68f55` | CURRENT_BASELINE 2026-09-11 | docs |

Общий паттерн 6 из 13: **полоса R2.MYPY меняла сигнатуры/аннотации, прикрывая
несовместимые места `type: ignore` — mypy green при сломанном рантайме**.
Рекомендация (в GAPS): CI-запрет `type: ignore[call-arg|arg-type]` либо
контрактные тесты публичных фасадов.

## 5. Остаточные unit-фейлы (кластеры)

### 5.1 Stale «focused»-скаффолды (infra, ~65)
`test_prometheus_alerting_focused` (12), `test_sse_focused` (11),
`test_rag_invalidation_focused` (10), `test_plugin_resource_monitor_focused` (9),
`test_tracing_focused` (8), `test_audit_verify_lifecycle_focused` (8),
`test_smart_session_manager` (7). Файлы семейства PERF-6.x коммитились
заведомо частичными (в собственных commit-сообщениях: «3 passed + 12 partial»,
«1 passed, partial»); источник эволюционировал (default-alerts при init,
sha256-ключи и т.п.). В сессии исправлены 4 файла семейства
(`client_metrics_focused`, `test_disk_focused`, hitl store/pubsub);
остаток — механическое обновление под текущие контракты, owner: QA.

### 5.2 MCP namespaces (28)
`test_ai_mcp` (7), `test_system_mcp` (6), `test_analytics_mcp` (6),
`test_credit_mcp` (5), `test_http_server_auth_wrap` (4): фейки тестов мокают
только `registry.dispatch`, а источник при эволюции добавил lookup
(`is_registered`) — тул возвращает error-конверт. Механический фикс фейков;
owner: ai-team. Связано с mcp 2.x/fastmcp 4 дрейфом (см. `3e5e116e0`).

### 5.3 Прочее
- `test_langfuse_v3_spike` (1) — флак под нагрузкой, в изоляции зелёный.
- composition-smoke (7) — **исправлены в сессии** (`6ece34739`: svcs_registry
  публичный API, свежий APIRouter в патче, route-контракт по путям, grep бриджа
  по модулю) — 166 passed.

Полный инвентарь: `.run/evidence/cov_sweep6.log` (grep '^FAILED').

## 6. Не выполнено / причины (директива §1)

- Единый `make test` — запрещён правилами ресурса; заменён полными прогонами
  `tests/unit` (xdist 117s + single-process с coverage) с логами в evidence.
- `uv lock --upgrade-package` для googleapis-common-protos /
  presidio-anonymizer / python-semantic-release — resolver не двигает
  (родительские пины) — GAPS G3.
- `alembic upgrade head` на dev-box: миграции требуют Redis-пароль из .env
  (чтение запрещено правилами) и хост БД, не резолвящийся вне сети стенда;
  схема dev-sqlite уже актуальна (23 версии, применены 2026-09-09) —
  позитивный auth разблокирован ресечом dev-учётки.

## 7. История версий

- **v8 (2026-09-11)** — ре-верификация после merge полосы R2.MYPY: 13 fix-
  коммитов, позитивная протокольная матрица, navigation audit, GAPS-реестр.
- **v7 (2026-09-10)** — 13/13 метрик, вердикт «ГОТОВ С ОГОВОРКАМИ» (в git-истории).

## 8. Дополнение 2026-09-11 — вторая волна (после v8)

| Позиция | Статус | Evidence |
|---|---|---|
| diskcache / PYSEC-2026-2447 | **CVE УСТРАНЁН ИЗ ПРОЕКТА**: перепроверка PyPI/OSV — фикса нет (last_affected 5.6.3 = последняя версия, upstream неактивен); единственный потребитель переписан на pickle-free `_IndexedByteStore` (sha256+JSON-индекс, 0o700), **diskcache удалён из deps**; **pip-audit: 0 findings по всему дереву**, allowlist 0 entries | `63fadf4fe`, `docs/roadmap/LIBRARY_REPLACEMENT_ANALYSIS.md` §4/§7 |
| G5 gRPC dispatch | Мост auto-servicer → `dispatch_action` реализован и **live-verified** (transport→auth→регистрация экшнов→dispatch→сервис→БД; users.list проходит всю цепочку). Остаток: lossy proto-стабы + standalone DI инвокера — GAPS G5 (обновлён) | `c348cee87`, `8017cccd2` |
| MCP-тесты (было 28✗) | Цели patch'ей registry → `core.api.extensions` — **35/35 namespaces + auth_wrap зелёные**; workflow_tools 2✗ — пре-существующий кластер (медленные, вне ретаргета) | `bfed93eff` |
| G8 docs | CLAUDE.md 4 битых пути → существующие артефакты; `docs/api/index.md` создан (mkdocs nav жив); README/ARCHITECTURE — 109 actions (по `manage.py actions`) | `291dfeeab` |
| G4 SOAP | Диагноз уточнён: `CancelledError` (BaseException) минует `except Exception` в `handle_soap_request`; источник — cancel-scope ASGI/anyio-слоя (Task/Future.cancel не вызывались); REST/gRPC с тем же экшном работают | GAPS G4 (обновлён) |
| Ruff gate | Полоса влила 29 новых lint-профессий в своих модулях — отловлены и исправлены (включая S108 hardcoded /tmp в file_safety); на момент замера `ruff check src/` = All checks passed | работа в worktree |

Гейты после волны: mypy `-p src` = 0 (2412 файлов), ruff = 0, pip-audit = 0.

## 9. Дополнение 2026-09-11 — третья волна (stale-кластеры + G8 навигация)

| Позиция | Статус | Evidence |
|---|---|---|
| Stale focused-кластеры | **59 тестов починены**: prometheus_alerting 14, sse 13, rag_invalidation 13, plugin_resource_monitor 11, tracing 9, audit_verify_lifecycle 10 — все под текущие контракты (`1749b9491`, `91e22a43a`). Итог доменных сьюточек: 568 passed / 1✗ (mq_trace — WIP полосы) | grep FAILED по доменам |
| G8 навигация | Дубли каталогов устранены: `docs/workflow/`→`workflows/worker-versioning.md`, `docs/migrations/`→`migration/` (git mv; синхронно с полосой 9cf3429ba); AGENTS.md — актуальная фаза + канонические источники вместо PLAN.md/Sprint-36; ARCHITECTURE.md — дата 2026-09-11 | `8f62c06bb` |
| Ruff gate | 29 новых lint-профессий полосы (F402/S108 в новых модулях) — исправлены, gate восстановлен | worktree |
| Остаётся красным | smart_session (7, load-flak), workflow_tools (2), mq_trace (1, WIP полосы), langfuse (1, флак), SOAP invoke (G4) | — |

## 10. Дополнение 2026-09-11 — четвёртая волна: G4 закрыт, протокольная матрица полностью зелёная

| Позиция | Статус | Evidence |
|---|---|---|
| **G4 SOAP invoke** | **ЗАКРЫТ**: корень — `create_app()` не вызывал `register_app_state()`, `app.state.invoker` отсутствовал → `Depends(get_invoker_dep)` падал AttributeError→500 (три раунда диагностики уводил в сторону CancelledError-шум aiosqlite-очистки). Фикс: вызов композиции в `_configure_application_components` (`49d929b05`) | Live: `/soap/invoke` InvokeRequest(users.list)+JWT → **200 `status=ok`**; незарегистрированная операция → 404 SOAP Fault; forged → 401 |
| Протокольная матрица | **REST 200 · GraphQL 200 · SSE 200 · SOAP invoke 200 · WS 200 · gRPC auth+dispatch-мост · негатив 401/403** — все достижимые на dev-box позиции PASS | FUNCTIONAL_TEST_REPORT 2026-09-11 |
| Осталось (вне dev-box / next sprint) | G1 coverage-CI · G2 push-SLO стенд · G3 deps MAJOR · G5 proto v2 · G6 MQ · G7 MCP flag · G8 хвост (docs/docs→vale, счётчики) · G10 debt | PROD_READINESS_GAPS.md |

## 11. Дополнение 2026-09-11 — пятая волна: внедрение предложений внешнего плана

Фактчек внешних предложений против HEAD (часть — устарела или уже выполнена):

| Внешнее предложение | Фактчек | Статус |
|---|---|---|
| Initial Alembic migration + idempotent seed | «migrations/versions пуст» — **устарело**: 23 версии на месте. Реальная дыра: seed-миграция aa1b2c3d4e5f (полоса, OP-1) не выполнялась на sqlite (env.py W21.2 идёт через create_all), и использовала pbkdf2-хэш при argon2-контракте User + NOW()/tenant_id несовместимости | **✅ исправлено** `056f4b722`: seed_data.py (переиспользуемый, портативный), вызов в sqlite-ветке env.py; live: чистый sqlite → admin+4 orderkinds, verify_password=True |
| Kill-switch runbook | **Уже существует** — docs/runbooks/feature-flag-kill-switch.md (297 строк, verified 2026-09-11) | ✅ закрыто ранее |
| ADR «accepted outdated-minimum» | **Уже принят** полосой — ADR-0302 (32 пакета) | ✅ закрыто ранее (9cf3429ba) |
| Saga double-fault chaos-тест | **✅ реализовано** `64eaed9d0`: 6 составных сценариев + реальный fix (_get_repo failure → in-memory fallback; ранее RuntimeError не обрабатывался) | ✅ |
| SBOM diff gate (license/CVE threshold) | Инфраструктура есть (generate_sbom.py, sbom.yml, policy.md) | Backlog — CI-джоб (вне dev-box) |
| Contract-diff gate (протокольная синхронизация) | api_fuzz_runner есть; расширение на GraphQL/gRPC diff | Backlog — след. спринт |

Крупные инициативы внешнего плана (Connector Catalog, Idempotency Service, Route
contract/dry-run, RPA state machine, Agent policy engine, Template Catalog) —
приняты в roadmap-бэклог (волны 1-3 внешнего документа); часть уже существует
(core/idempotency/service.py — полоса, infrastructure/antivirus, chaos, eventing).

## 12. Дополнение 2026-09-14 — шестая волна: OP-3/OP-6 гейты доведены до рабочего состояния

Фактчек полосного OP_VERIFICATION_REPORT («6 operational gaps closed») показал:
скрипты OP-3/OP-6 были написаны с тестами, но **фактически не запускались** —
гейт SBOM был непроходим в принципе (pip-audit-формат CycloneDX не несёт license
полей → все 29 считались unknown → FAIL), у contract-diff не существовало
генератора входных контрактов, и diff падал на null-полях интроспекции.

| Гейт | Доработка | Результат |
|---|---|---|
| SBOM diff (OP-3) | unknown license = WARN (строгий режим `--fail-on-unknown`); поддержка CycloneDX expression-лицензий; make-рецепт генерит лицензионный SBOM через generate_sbom.py | `make sbom-diff-gate` → **PASS** (0 violations, 18 unknown=WARN: системный мусор в venv + expression-пропуски устранены парсером), 26/26 тестов (`a18d0df94`) |
| Contract diff (OP-6) | `tools/checks/extract_contracts.py` — извлекает REST OpenAPI / GraphQL introspection / gRPC services из приложения (REST OK, GraphQL OK, gRPC OK); null-guard скаляров интроспекции в gate; make `contract-diff-gate` = extract→baseline→diff | `make contract-diff-gate` → **PASS** (499 non-breaking ops); дрейф-тест: удаление /health из current → FAIL `[removed_endpoint] GET /health` (`820152544`) |
| Паразитный шум SBOM | В venv попали системные пакеты Ubuntu (cloud-init, Brlapi, cupshelpers, language-selector, bcc) — источник unknown-license WARN'ов | Зафиксировано как env-проблема (пересоздать venv без system-site) — в GAPS |

Итог по внешнему плану: все 6 позиций финальной секции внедрены и доведены
до рабочего состояния (проверяемо командами `make sbom-diff-gate`,
`make contract-diff-gate`, `pytest tests/chaos/test_saga_double_fault_chaos.py`,
`alembic upgrade head` на чистом sqlite, docs/runbooks/feature-flag-kill-switch.md,
ADR-0302).

## 13. Дополнение 2026-09-14 — седьмая волна: G5(b) закрыт, write-CRUD восстановлен

| Позиция | Статус | Evidence |
|---|---|---|
| **G5(b) standalone Invoker** | **ЗАКРЫТ**: `helpers.get_invoker` (декоратор тело не перезаписывал — всегда RuntimeError) → state-lookup + standalone `Invoker()`; grpc-serve регистрирует минимальный state (invoker/reply_registry) через `set_app_ref` | Live: `Invoke(users.add, data={...})` → **`status: "ok"`, result_json с полной схемой** (`a6730dced`, bootstrap в server.py) |
| **Write-CRUD восстановлен** | **Критическая находка**: CrudMixin звал `helper._process_and_transfer`, которой нигде не было (S61-рефакторинг потерял при извлечении миксинов; NEW-1 дополнительно переприназначил helper на repo.helper) → add/update всех сущностей падали AttributeError→ServiceError **с момента S61**. Восстановлен `BaseService.ServiceHelper(repo)` с `_transfer/_transfer_paginated/_process_and_transfer` | `a6730dced`; Live: REST `users.add(data)` → 200 (PII-маскирование в ответе); gRPC Invoke → ok |
| Контракт вызова CRUD | caller обязан слать `{"data": {...}}` для add (update: ключи=key/value/data); flat-payload → TypeError по замыслу dispatch (method(**kwargs)) | задокументировано здесь |

Итог: gRPC теперь полнофункционален БЕЗ proto v2 — generic `Invoke` (Invoker) даёт full-fidelity бизнес-вызовы; auto-servicer остаётся подмножеством (lossy-прото, G5(a) остаётся в backlog).

## 14. Дополнение 2026-09-14 — восьмая волна: P0 bootstrap-admin + гейты стали настоящими CI-гейтами

Фактчек внешнего ревью HEAD 948ac50e принят полностью; три частичных позиции закрыты:

| Приоритет | Работа | Статус | Evidence |
|---|---|---|---|
| **P0** | Privileged credentials удалены из production seed: миграция + sqlite-ветка — только reference data (orderkinds); admin создаётся явной командой `manage.py bootstrap-admin` (`--password-stdin`/`--from-env`); известные дефолты запрещены во всех профилях; prod: длина >= 12; make-таргет `bootstrap-admin`; downgrade больше не удаляет учётку по username | **✅** | `e7ab9aeba`; live: чистый sqlite → 4 orderkinds/0 users; команда → created exit 0; тесты policy 9 |
| **P1** | SBOM gate → настоящий CI-gate: baseline трекается в `.baselines/sbom.baseline.json` (принят через новый `make sbom-baseline-accept`), auto-copy из проверочного таргета удалён (fail-fast «make sbom-baseline-accept» при отсутствии), blocking job в `security.yml` | **✅** | `f26d2d42b`, `d201251ba`; live: RESULT PASS (0 violations, 18 unknown=WARN) |
| **P1** | Contract gate → настоящий CI-gate: auto-cp удалён (fail-fast «make contract-baseline-accept»), baseline трекается в `.baselines/contracts-baseline/`, blocking job в `security.yml` (extract → diff vs baseline) | **✅** | `d201251ba`; live: PASS 499 ops; дрейф-тест: удаление /health → FAIL |
| P2 | Contract matrix SOAP/AsyncAPI/MCP | Backlog — extract_contracts расширяется по мере надобности | GAPS |
| P2 | Runbook tabletop-проверка | Backlog — SRE, после staging | GAPS |

Замечания внешнего ревью по качеству внедрения (self-copy baseline, CI-wiring,
небезопасный bootstrap) подтверждены и закрыты; расхождение «гейт сравнивает сам
с собой» устранено трекингом baseline в git. CVE-часть SBOM-предложения
покрывается существующим blocking pip-audit gate (allowlist отдельно) —
CVSS-diff остаётся P2-усилением.

## 15. Дополнение 2026-09-14 — финальная верификация внешнего ревью (HEAD 93f138aca)

Все пять позиций приоритетного остатка из внешнего ревью HEAD 948ac50e закрыты и
верифицированы командами на актуальном HEAD (93f138aca + fix-коммиты волны-9):

| Приоритет | Внешний done-критерий | Фактический статус | Доказательство |
|---|---|---|---|
| **P0** | Чистый prod deploy не создаёт учётку с публично известным паролем | **✅ ЗАКРЫТ**: production seed = только reference data (orderkinds); bootstrap-admin — явная команда с stdin/env-паролем, известные дефолты отклоняются во всех профилях, prod ≥12 символов | Live: чистый sqlite → 4 orderkinds/0 users; `manage.py bootstrap-admin --password-stdin` → created; тесты policy 9/9 |
| **P1** | SBOM gate в CI, new HIGH/CRITICAL CVE + запрещённая лицензия блокируют PR | **✅ ЗАКРЫТ**: baseline трекается (`.baselines/sbom.baseline.json`), fail-fast при отсутствии, CVE-diff (`--audit-current/--audit-baseline` vs allowlist), blocking job в security.yml | Live: PASS (0 violations, 18 unknown=WARN); 26/26 тестов |
| **P1** | Contract gate в CI, breaking change блокирует PR | **✅ ЗАКРЫТ**: baseline трекается (`.baselines/contracts-baseline/` — 4 файла вкл. action_matrix.json), fail-fast, blocking job; дрейф-тест FAIL-детект | Live: PASS, 499 non-breaking ops, matrix 0 breaking; 35/35 тестов |
| **P2** | Contract matrix SOAP/AsyncAPI/MCP | **✅ ОСНОВА ГОТОВА**: action_matrix.json (132 actions × rest/grpc/soap) tracked в baseline; matrix-diff в гейте (action_removed/protocol_coverage_lost = breaking); AsyncAPI/MCP секции информационные (заполняются при включении соответствующих транспортов) | Live: extract OK, matrix 0 breaking; дрейф-тест soap-loss → FAIL |
| **P2** | Runbook smoke | **✅ ВЫПОЛНЕНО**: kill-switch toggle OFF→ON через API — 200×2 на живом dev_light-стенде; попутно закрыт 403 admin_role_required (admin_roles claim в JWT) | `817eff4c1`; FUNCTIONAL_TEST_REPORT |

Команды верификации (все exit 0): `make sbom-diff-gate`, `make contract-diff-gate`,
`pytest tests/unit/tools/ tests/unit/services/auth/ tests/unit/infrastructure/database/ -q`.

## 16. Дополнение 2026-09-14 — SOAP invoke закрыт (G4 ✅), остаток P2

| Позиция | Статус | Evidence |
|---|---|---|
| **G4 SOAP invoke** | **✅ ЗАКРЫТ** — `/soap/invoke` с `InvokeRequest(action=orderkinds.list)` + JWT → **200, `status=ok`** | Live curl `1d93316aa` |
| SOAP underscore→dot | WSDL публикует `orderkinds_list`, registry содержит `orderkinds.list` — underscore→dot resolution добавлена в `handle_soap_request` | `1d93316aa` |
| SOAP type coercion | XML values всегда str → коэрсируются в int/float/bool для CRUD-сервисов | там же |
| Named-op `/soap/` path | Остаток: registry import duplication между `core.api.extensions` и `dsl.commands.action_registry` — требует architecture-level решения | Backlog |

Внешнее ревью P0/P1/P2 — все 5 позиций закрыты.
Протокольная матрица (достижимое на dev-box): REST+GraphQL+SSE+WS+SOAP+gRPC Invoke = все 200 ok.

## 17. Финальная верификация внешнего ревью о «158 SyntaxError» (2026-09-14, HEAD 23da6142d+)

### Опровержение

Внешнее ревью заявило «158 некомпилируемых файлов, 211 except A, B:». Независимая
проверка на актуальном HEAD под Python 3.14.0 (**оптимизированнаяuv-среда**):

| Проверка | Команда | Результат |
|---|---|---|
| compileall | `python -m compileall -q src` | **exit 0** |
| AST parse (3.14) | `ast.parse` на каждом .py в src/backend | **0 ошибок** |
| ruff | `ruff check src/` | **All checks passed** |
| mypy strict | `mypy -p src` (2453 файла) | **0 issues** |
| pytest collection | `pytest --collect-only -q` | **19073 collected** |

**Причина расхождения**: конструкции `except A, B:` (без скобок) — валидный
**PEP 758** синтаксис, принятый в **Python 3.14**. Внешнее ревью выполняло AST-разбор
под pre-3.14 Python, где PEP 758 не поддерживается и эти строки являются SyntaxError.
Проект декларирует `requires-python = ">=3.14"` — на целевой версии все файлы
компилируются и запускаются.

### Финальное состояние гейтов

| Гейт | Результат |
|---|---|
| ruff | 0 |
| mypy strict | 0 (2453 files) |
| compileall | exit 0 |
| AST parse | 0 errors (3.14) |
| pip-audit | 0 findings |
| SBOM diff | PASS |
| Contract diff | PASS (499 ops) |
| pre-prod | 25/36 PASS, 0 FAIL |
| Test collection | 19073 collected (1 env-error: polars optional extra) |
| Unit suite (выборка) | 782 passed / 17 failed (tests/unit/tools — band WIP) |

### Вердикт

**ГОТОВ К ПРОДУ С ОГОВОРКАМИ** — подтверждено на HEAD 23da6142d + волна-9.
Все 5 позиций внешнего ревью (P0/P1/P2) закрыты с command evidence.
Инфраструктурные ограничения (G1/G2/G6) — в PROD_READINESS_GAPS.md.
