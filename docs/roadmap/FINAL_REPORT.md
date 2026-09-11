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
