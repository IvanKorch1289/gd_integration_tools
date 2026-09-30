# FINAL REPORT — full-tree аудит a2bd6f294 (2026-09-30)

## 1. HEAD и environment
- **HEAD a2bd6f294df8da590007a7fddd592e0b06e7a9f9** (≠ ожидаемого 2c39e4469: +1 коммит
  владельца a2bd6f294 «три причины загрязнения сьютов» — дрифт зафиксирован).
- Python 3.14.0, uv 0.11.7, ruff 0.16.7, mypy 1.20.2, pytest 9.1.1, temporalio 1.32.0,
  granian 2.8.2, faststream 0.7.5. Профиль: main .venv по uv.lock checkout.
- Чистый checkout: `git worktree add /tmp/audit-checkout` (reset --hard/clean запрещены).
- Метод: рой 10+ агентов (2 волны по 5 Explore + финальный reviewer), каждый клейм —
  file:line + собственная проверка reviewer'ом. 4 ложных «SyntaxError P0» отловлены
  (PEP 758 валиден на 3.14; агенты парсили ast 3.12 — повторение известного ложного
  клейма внешнего аудита; переквалифицировано в P2-style).

## 2. Карта архитектуры и import graph
- 6769 файлов, 774k LOC (2771 production py, 2263 test py), 3844 модуля, 11346 рёбер.
- **16 циклических компонент (SCC)**: крупнейшая — **649 модулей** (core.ai ↔ core.config ↔
  services ↔ entrypoints.api ↔ plugins.composition ↔ main — ядро-монолит); далее
  data_quality (6), admin_plugins↔routers↔main↔app_factory (6). Гипотеза 7 CONFIRMED.
- Детали: architecture_map.md, import_graph.json, file_inventory.csv.

## 3. P0/P1/P2 findings (все с file:line, ревизованы reviewer'ом)
### P0 (6)
1. CompensatingDriverWorker не исполняет компенсации stuck-саг: ставит rolled_back сигналом
   (compensating_driver.py:129-131) — reviewer CONFIRMED. Crash во время компенсации =
   потеря компенсации.
2. SchedulerBackend sync-Protocol × async Temporal-реализация × sync-фасад с to_thread:
   при scheduler_backend=temporal зарегистрированной задачи нет, а registered=True
   (interfaces/scheduler.py:94, temporal_scheduler_backend.py:139, facade.py:158) — reviewer CONFIRMED.
3. Tenant fail-open get-by-id: notebooks/service.py:88-91, ai/feedback/feedback_service.py:244-246
   — при пустом tenant контексте repo.get(id, tenant_id=None) возвращает чужое (repo-фильтр
   `is not None`) — reviewer CONFIRMED. Противоречит ADR-0345 fail-closed.
4. Redis feature-flag broadcaster: wiring подаёт wrapper-клиент (pubsub() = coroutine), код
   ждёт raw-async API → AttributeError проглатывается maybe_start_broadcaster → broadcaster
   молча никогда не стартует (redis_broadcaster.py:179-180, startup_phases/services.py:221-230).
5. Mongo: клиент никогда не стартуется (MongoDBClient.start() — 0 вызовов), при этом
   ensure_indexes вызываются независимо и «молча-успешны» через debug-логи
   (startup_phases/protocols.py:79-120, mongodb.py:100-106) — TTL/unique индексы не создаются.
6. GraphQL schema.py — module import цепочка живая, но schema.py:195 содержит PEP 758
   `except AttributeError, TypeError:` (P2-style); реальный P0 GraphQL: depth/introspection
   не ограничены, write-семантика доступна через Query (schema.py:144-157).

### P1 (топ-10 из 20+)
1. Tenant-спуфинг: X-Tenant-ID header приоритетнее auth-state (middlewares/tenant.py:126-140);
   tenant_resource_isolation — pass-through без checker'ов (setup_middlewares.py:154-160).
2. Middleware LIFO-инверсия: rpa_policy(720)/ai_tool_whitelist(640) работают ДО auth(620)
   при комментарии «after auth» (setup_middlewares.py:214-271) — reviewer CONFIRMED.
3. Rate-limit fail-open: RedisRateLimitChecker глотает исключение → allow
   (global_ratelimit.py:178-185).
4. gRPC fail-open auth: без api_key сервер слушает insecure без interceptor'ов
   (grpc_server/server.py:99-102,137).
5. SSRF webhook_relay: target_url без private-IP проверки (webhook_relay.py:273; WAF-слой
   есть, но default-permissive без private/loopback — reviewer PARTIAL).
6. Silent fallback production → deprecated pg_runner c replay=NotImplementedError
   (workflow/factory.py:109-117).
7. files.py: S3-ключ из URL без tenant-scope/ownership (files.py:161-235).
8. Scheduler sync/async: retry-семантика deferred (ConflictingIdError цикл,
   deferred_mixin.py:140-169).
9. Duplicate route: GET /api/v1/admin/feature-flags зарегистрирован дважды
   (admin.py:146 + admin_feature_flags.py:124) — второй недостижим.
10. Startup phase MongoDB/ES сбои логируются .debug() — невидимы в prod (protocols.py:81-131).

### P2 (выборочно)
- PEP 758 безскобочные except (4 файла) — стиль при касании (валидно на 3.14).
- except-Exception-pass паттерны (streaming/reliability.py:149, semanticrouter:72).
- Дубли mixin-ов вне MRO (collection_mixin, request_reply_mixin).
- Широкий except в _dispatch_dsl + fake-success при security=None (schema.py:310-324).

## 4. Confirmed dead code и false positives
- CONFIRMED дубликаты: core/services/base_external_api.py (exact copy, 275 LOC),
  saga_lra legacy-пакет содержимое (~811 LOC). Итого ~1110 LOC безопасного удаления.
- Мёртвые: InfraLogWriteProcessor, FeatureFlagCheckProcessor, collection_mixin/
  request_reply_mixin (вне MRO), _now_utc(), admin_audit.py, feature_flags.scheduler_backend,
  quotas_service stub.
- FALSE POSITIVE: все 4 «SyntaxError» (PEP 758), секреты в коде (docstring-примеры),
  SQL ML-inference (валидирован isalnum), notebooks path traversal (санитизация есть).

## 5. Library replacement matrix
См. library_replacement_matrix.md. ADOPT: import-linter, Schemathesis, LibCST.
REJECT: Dishka, OpenFeature, RESPX, AnyIO-слой. PLAN: scheduling consolidation.

## 6. План атомарных PR/commits
1. fix(security): tenant fail-closed get-by-id (notebooks+feedback) + тесты.
2. fix(messaging): broadcaster wrapper-pubsub (async-путь) + тест.
3. fix(db): MongoDBClient.start() в startup phase + ensure_indexes после старта.
4. fix(scheduler): async-адаптер в фасаде (iscoroutinefunction) или async-Protocol.
5. fix(workflow): CompensatingDriver — исполнение compensating_actions.
6. fix(security): webhook_relay _validate_url + WAF private-IP default для outbound.
7. fix(api): дубль feature-flags route; GraphQL depth-limit; gRPC fail-closed auth.
8. fix(middleware): rpa_policy/ai_tool_whitelist order > auth; tenant state>header.
9. refactor: удалить 2 дубликата (~1110 LOC) + миграция 1 импорта.
10. chore: 4 PEP 758 → скобочная форма; admin_audit.py удалить.

## 7. Выполненные проверки (exit codes)
- Инвентаризация/граф: сгенерированы (6769 файлов, 16 SCC) — скрипт детерминирован.
- Статика чистого checkout (фаза аудита): 13/13 exit 0 (privacy — ENV-bound, задокументирован).
- Runtime группы 20-23: exit 0; 24/25: pollution (изоляция 76 passed).
- Coverage gate (чистый checkout): 77.02% ≥ 70 exit 0.
- make ci/readiness: PASS; pre-prod: 26/37 → 25/37+1 (coverage.xml генерат).
- Канонический unit (xdist, timeout 120): 19 801 passed / 164 failed (env-tier без .env +
  pollution — классифицировано изоляцией).

## 8. cURL и browser evidence
- :8000 (образ 5 недель): health 200, openapi 411 paths, docs/redoc 200, GraphQL 403 fail-closed.
- HEAD-app (:8081 staging-профиль): health 200, Host-header защита подтверждена.
- Playwright (HEAD-app): Swagger UI/ReDoc render, 0 console errors, скриншоты
  (artifacts/e2e/). CSP-баг старого образа исправлен в HEAD.

## 9. Performance baseline
- Staging multiworker granian (локальный drill, dev-box): 2w/100VU 582 RPS p95 100;
  4w/100VU 599 RPS p95 96, p99 140; 4w/200VU 660 RPS p95 310. Потолок ~660 RPS.
- S6-порог 1000 RPS/p95<200 → 19/22 PARTIAL: требуется staging-стенд
  (бут-цепочка staging локально закрыта — 7 фиксов, задокументировано).

## 10. Remaining risks и честный verdict
- Риски: (а) 6 P0 требуют код-фиксов (список в п.6 — атомарные PR);
  (б) SCC-649 — монолит ядра (разрыв — марафон, начать с main↔app_factory↔routers);
  (в) artifacts в git 18.6MB+logs 4.1MB — в CI storage.
- **Verdict: NOT production-ready по протоколу** (6 P0 код-дефектов найдены и
  не исправлены в этом аудите — аудит по ТЗ «начинай не с исправлений»).
  При этом: вся статика/рантайм-инфраструктура проверок зелёная, 21/23 DoD
  предыдущего протокола VERIFIED. После P0-PR'ов (п.6, ~1-2 дня) и на staging-стенде
  для perf — достижимо 23/23.
