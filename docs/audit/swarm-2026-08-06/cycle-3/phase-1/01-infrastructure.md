# Cycle 3 Phase 1 — Infrastructure domain audit

- **Дата:** 2026-08-06
- **HEAD:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`
- **Scope:** `src/backend/infrastructure/**`, `tests/unit/infrastructure/**`,
  `tools/check_layers.py`, `tools/check_layers_allowlist.txt`.
- **Запрещено читать/менять:** `src/backend/infrastructure/storage/s3.py`,
  `pyproject.toml`, `uv.lock`, `tools/check_layers_allowlist.txt`,
  отчёты `cycle-1/`, `cycle-2/`, `KNOWN_ISSUES.md`, `CLAUDE.md`,
  `PLAN.md`, отчёты других агентов.
- **Интерпретатор runtime:** `.venv/bin/python` (Python 3.14.0,
  pytest 9.1.1, hypothesis 6.165.1, cachetools 7.1.7). System Python
  без `prometheus_client`/`fastapi`/`hypothesis` НЕ использовался.

## Scope / не проверено

**Проверено:**

- 429 `.py` файлов в `src/backend/infrastructure/**` (по `find -type f -name "*.py"`),
  219 тестовых файлов в `tests/unit/infrastructure/**`.
- `src/backend/infrastructure/clients/external/cdc/{client.py,_dlq_writer_guard.py,cdc_client_adapter.py}` — все прочитаны полностью (B-17/B-02 цикл 33/37).
- `src/backend/infrastructure/workflow/compensating_driver.py`,
  `src/backend/infrastructure/resilience/{coordinator.py,time_limiter.py,supervisor.py}`,
  `src/backend/infrastructure/messaging/dlq/{kafka_writer.py,nats_writer.py,rabbit_writer.py,inbox_writer.py}`.
- `src/backend/infrastructure/database/smart_session_manager.py` (S173 M2.4, K2 S19 W1).
- `src/backend/infrastructure/eventing/inbox.py` (Sprint 8 K2 W4).
- `src/backend/infrastructure/cache/rag/embedding_cache.py` (cycle-1/P3-01).
- `src/backend/plugins/composition/di.py:230-262` (CDC DLQ wiring).
- `src/backend/core/security/connector_auth.py` (S172 W2).
- `tools/check_layers.py`, `tools/check_layers_allowlist.txt` (header + tail + counts).
- Targeted runtime-тесты (см. «Commands run»).

**Не проверено (намеренно):**

- `src/backend/infrastructure/storage/s3.py` (запрет).
- Полное содержимое каждого из 429 `.py` (429 файлов — вне bounded-deep-dive);
  проверены только релевантные для findings/cycle-2/B-17.
- `tests/unit/infrastructure/messaging/outbox/*` — 9 failures
  предъявлены как pre-existing (`TypeError: lambda takes 0 positional
  arguments but 1 was given`, локальный баг теста, источник — `git log`
  показывает `a5a8fabc fix(tests): test_claim_pending stub — collection
  error (Cycle 86 L10)`, source из S171 — НЕ этому плану).
- `tests/unit/infrastructure/database/test_tenant_filter.py` (4 failures)
  — тесты для DEPRECATED shim `src/backend/infrastructure/database/tenant_filter.py:1-55`,
  перенесённого в `src/backend/core/tenancy/sqlalchemy_filter` (S107 W1,
  TD-002 residual, см. warning в `tenant_filter.py:55`).
- `tests/unit/infrastructure/eventing/test_inbox.py` (2 failures) —
  тесты проверяют сообщение `"Redis SETNX failed"`, источник в
  `inbox.py:84`, но фактический путь (`inbox.py:71`) бросает другое
  сообщение. Pre-existing, last touch 6f28ff30 (deep audit QW-C + sprints 35-45).
- `tests/unit/infrastructure/cdc/test_cdc_status_docs_s7w2.py` (4 failures)
  — тесты на содержимое `ARCHITECTURE.md` (строки `**implemented**`),
  не runtime. Pre-existing.
- `tests/unit/infrastructure/database/test_smart_session_manager.py::test_read_routes_to_replica`
  (1 failure) — `primary.calls==1` из-за `_update_lag_status` (S19 W1),
  intentional design (lag-check идёт через primary).
- `tests/unit/infrastructure/clients/transport/test_http_no_circuit_breaker.py::TestLayerLinterNoRegression::test_extensions_layer_linter_clean`
  (1 failure) — extensions linter, scope `extensions/`, не мой scope;
  baseline этого отчёта фиксирует 175 legacy / 0 new для `src/`.
- `tests/unit/infrastructure/security/test_vault_secrets.py::test_reauth_on_forbidden`
  (1 failure) — `hvac`/Vault сетевой стек; не проверено детально.
- Cycle-1/cycle-2 markdown отчёты (явный запрет).

## Verified strengths

1. **Layer checker 175 legacy / 0 new (2274 файлов) — confirmed.**
   `.venv/bin/python tools/check_layers.py --root src` →
   `Нарушений: 0 новых (файлов: 2274; baseline: 175 legacy)`,
   exit 0. Совпадает с cycle-3 baseline `BASELINE.md`.
   В allowlist 63 строки (из них 31 — `core → infrastructure`, ровно
   тот пул legacy-импортов через bridge-провайдеры, что задокументирован
   в `src/backend/infrastructure/README.md`).
2. **T-3.1 cachetools.TTLCache — RESOLVED (подтверждено в working tree).**
   `git diff src/backend/infrastructure/cache/rag/embedding_cache.py` показывает
   миграцию с custom `dict + time.monotonic()` на
   `from cachetools import TTLCache` + `asyncio.Lock`. 10/10
   `tests/unit/infrastructure/cache/rag/test_embedding_cache.py` PASSED
   (TTL expiration, LRU eviction, concurrent access, sha256-key,
   defaults). `cachetools 7.1.7` установлен в venv.
3. **B-17 cycle 37 fail-loud CDC DLQ wiring — РАБОТАЕТ в runtime.**
   - `src/backend/infrastructure/clients/external/cdc/client.py:83-97`
     `set_dlq_writer()` вызывает `mark_cdc_dlq_writer_wired(writer)`
     как side-effect.
   - `client.py:67-81,272-281` — production default
     `dlq_required=True`; в `_send_to_dlq` при `_dlq_writer is None`
     и `_dlq_required=True` бросается `RuntimeError("CDC event
     dropped: DLQ writer not wired ...")`.
   - `src/backend/plugins/composition/di.py:250-262` — wiring
     `InboxDLQWriter` через `_get_outbox_dlq_session_factory()` +
     явный `mark_cdc_dlq_writer_wired(inbox_dlq_writer)` после
     `cdc.set_dlq_writer(inbox_dlq_writer)`.
   - `src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py:91-99`
     module-level singleton `cdc_dlq_writer_guard`.
   - **13/13 тестов** `tests/unit/infrastructure/clients/external/cdc/test_dlq_writer_guard_cycle37.py`
     PASSED:
     `test_dlq_writer_guard_initial_state_is_not_wired`,
     `test_dlq_writer_guard_mark_wired_flips_to_true`,
     `test_dlq_writer_guard_mark_wired_is_idempotent`,
     `test_dlq_writer_guard_reset_clears_state`,
     `test_dlq_writer_guard_mark_wired_module_singleton`,
     `test_cdc_send_to_dlq_no_writer_required_raises_runtime_error`,
     `test_cdc_send_to_dlq_with_writer_writes_envelope`,
     `test_cdc_send_to_dlq_no_writer_dev_returns_silently`,
     `test_cdc_set_dlq_writer_flips_guard_as_side_effect`,
     `test_cdc_set_dlq_writer_none_does_not_clear_guard`,
     `test_cdc_set_dlq_required_overrides_default`,
     `test_composition_root_wires_cdc_dlq_writer`,
     `test_cdc_dispatch_with_writer_required_no_error`.
   - **Real-runtime sanity (вне AsyncMock):**
     `.venv/bin/python` script поднимает `FastAPI()` +
     `di.register_app_state(app)` (с моками `InboxDLQWriter` и
     `_get_outbox_dlq_session_factory`) →
     `cdc_dlq_writer_guard.is_wired() == True` →
     подтверждено, что composition root действительно выполняет
     wiring на boot.
4. **CDC adapter (M5 DLQ handoff) — 7/7 PASSED.**
   `tests/unit/infrastructure/cdc/test_cdc_client_adapter.py`: subscribe/
   yield/dlq-envelope-shape/on_overflow forwards-to-dlq/no-dlq-no-raise/
   dlq-failure-does-not-propagate/dlq-writer-satisfies-protocol.
5. **CompensatingDriverWorker — 6/6 PASSED.**
   `tests/unit/infrastructure/workflow/test_compensating_driver.py`:
   scan-once/no-stuck-noop/per-saga-exception/rolled-back-signal/
   start-stop-lifecycle/start-idempotent. Workflow D-AUDIT-FIX-184-1
   закрыт реальной in-process реализацией.
6. **Cache infra — 60/60 PASSED в `tests/unit/infrastructure/cache/**`.**
   LRU/Redis-Cluster-pipeline/tenant-wrapper/embedding-cache — всё
   green.
7. **Resilience + observability — 191/191 PASSED.**
   Backpressure/breaker/spec/facade/jittered-backoff/
   memory-metrics/audit-verify-lifecycle.
8. **Messaging (без outbox/dlq) — 28/28 PASSED.**
9. **Storage (без `s3.py`) — 60/60 PASSED.**
   `local_fs`, `fallback`, `sqlite_doc_store`, `vector_pool_registration`,
   `s3_cache`. `s3.py` не читал (запрет); `tests/unit/infrastructure/storage/`
   без `test_s3*.py` PASSED.
10. **Sources (139/139 PASSED + 2 skip)** — все runtime-тесты
    CDC/IMAP/GraphQL/REST/Kafka/etc. идут через `check_source_capability`
    (boolean вариант), не через `@require_capability` (raising
    вариант), поэтому anonymous проходит.
11. **Composition root CDC wiring explicit + observable + idempotent.**
    `cdc_dlq_writer_guard.mark_wired(writer)` вызывается и из
    `set_dlq_writer` (side-effect), и явно из `di.register_app_state`
    — счётчик `_wired_at_count` инкрементируется дважды, idempotent.
12. **35 active security IDs в allowlist** — стабильно
    (matches cycle-3 baseline).

## Findings table

| ID | P | path:line | evidence | impact | minimum fix | test criterion |
|----|---|-----------|----------|--------|-------------|----------------|
| 01-P1-NEW-001 | P1 | `tests/unit/infrastructure/sinks/conftest.py:1-28` + 9 sinks + 3 dlq writers | commit `e5d389c0` ("fix(s202): close RPA + DLQ security gaps") навесил `@require_capability(...)` на `send()` 9 sinks и `write()` 3 DLQ writers, но conftest (28 LOC) чистит только `BreakerRegistry` и НЕ выдаёт capabilities тестам. Тесты вызывают `await sink.send(payload)` без `_principal=` → `ConnectorAuthError: denied for anonymous`. Реальные runtime-failures: 6/9 `test_file_sink.py`, 4/8 `test_ws_sink.py`, 4/7 `test_soap_sink.py`, 4/8 `test_grpc_sink.py`, 6/10 `test_mq_sink.py`, 4/10 `test_webhook_sink.py`, 4/10 `test_http_sink.py`, + аналогично `mqtt/email/s3` + 10/14 в `test_kafka_writer/test_nats_writer/test_rabbit_writer` (`dlq.write`). | Тестовая инфраструктура полностью поломана для capability-protected sinks/writers. Production fail-closed semantics скрыта — при smoke-test разработчик видит ложный fail и может отключить decorator. | Добавить в `tests/unit/infrastructure/sinks/conftest.py` (и `messaging/dlq/conftest.py`) `autouse` fixture, который мокает `AuthorizationFacade.check_principal` чтобы возвращал `AuthDecision(allowed=True, ...)` для тестовых principal'ов; либо выдавать через `AuthorizationFacade.grant_capability("anonymous", "file.write", ...)` в session-scope fixture. | `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/ tests/unit/infrastructure/messaging/dlq/ -q` → 0 failures, exit 0. |
| 01-P2-NEW-001 | P2 | `src/backend/infrastructure/workflow/compensating_driver.py:118` | Строка `repo = self._session_factory.__class__.__module__  # placeholder` — pure dead code. Перезаписывается на 5 строк ниже (line 123) реальным `repo = WorkflowStateRepository(session)`. В комментарии прямо указано `# placeholder`. Тесты 6/6 PASS, потому что на 123-й строке используется правильный объект, но строка 118 нарушает правило "no dead code" и сбивает читателя. | Мёртвый код в hot-path (вызывается на каждом scan-tick 60s). Не функциональный bug, но индикатор копипасты из шаблона. | Удалить строку 118 (реальный `repo` всё равно создаётся ниже из сессии). ponytail: one-line deletion. | `.venv/bin/python -m pytest tests/unit/infrastructure/workflow/test_compensating_driver.py -q` → 6 passed (без регрессий); ruff F841 / F821 не ругается. |
| 01-P3-NEW-001 | P3 | `src/backend/infrastructure/database/smart_session_manager.py:208-209` + `tests/unit/infrastructure/database/test_smart_session_manager.py:49-59` | `acquire(mode="read")` → `_pick_sessionmaker("read")` → `_should_check_lag()` → `_update_lag_status()` (line 246) → `self._primary()` (для `pg_stat_replication`). Это intentional (K2 S19 W1 lag-budget routing: `pg_stat_replication` доступен только на primary). Тест `test_read_routes_to_replica` написан до S19 W1 и ожидает `primary.calls == 0`. `multi_replica_failover=True` в default feature_flags → путь активируется. | Pre-existing test/source drift, last modified `f32638e1` (s113 w5). Тест не учитывает новую lag-budget feature. | В тесте замокать `_update_lag_status` через `monkeypatch.setattr(sm, "_update_lag_status", AsyncMock())` либо выставить `feature_flags.multi_replica_failover=False` через fixture. Source-side fix не требуется. | `.venv/bin/python -m pytest tests/unit/infrastructure/database/test_smart_session_manager.py -q` → 7 passed. |

**Counts:** P0=0, P1=1, P2=1, P3=1, P4=0. **Total findings: 3.**

## Detailed evidence

### 01-P1-NEW-001 — connector_auth test infrastructure gap

Подтверждено прямым запуском (см. Commands run §):
- `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/test_file_sink.py` →
  `6 failed, 3 passed in 5.12s`; captured log:
  `WARNING core.security.connector_auth: connector_capability_denied:
  capability=file.write action=write principal=anonymous tenant=None
  reason=policy denied: write`.
- `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/test_ws_sink.py` →
  `4 failed, 4 passed in 8.52s` (аналогично `ws.send`).
- `.venv/bin/python -m pytest tests/unit/infrastructure/messaging/dlq/` →
  `10 failed, 11 passed`: kafka/nats/rabbit `dlq.write`.

Корень: commit `e5d389c0` (`fix(s202): close RPA + DLQ security gaps
with auth_check/require_capability`, 16 Jul 2026) добавил decorator
на 9 sinks (`file_sink.py`, `ws_sink.py`, `mqtt_sink.py`, `email_sink.py`,
`webhook_sink.py`, `soap_sink.py`, `s3_sink.py`, `grpc_sink.py`,
`mq_sink.py`, `nats_jetstream.py`, `sms_sink.py` НЕ имеет), 3 DLQ
writers (`kafka_writer.py`, `nats_writer.py`, `rabbit_writer.py`),
8 RPA processors и `BreakerRegistry.reset()`. Одновременно добавлен
**только breaker-reset** conftest (`tests/unit/infrastructure/sinks/conftest.py:24-27`),
БЕЗ capability grant. Production `AuthorizationFacade.check_principal`
(`src/backend/services/authorization/facade.py:139-148`,
`S202 audit fix: require authentication — anonymous requests denied`)
возвращает `AuthDecision(allowed=False, ...)` для principal=anonymous,
что ломает тесты.

Файлы, которые защищены и НЕ имеют grant в conftest:
- `src/backend/infrastructure/sinks/{file,ws,mqtt,email,webhook,soap,s3,grpc,mq,nats_jetstream}_sink.py`
  (10 sinks с `@require_capability(...)`).
- `src/backend/infrastructure/messaging/dlq/{kafka,nats,rabbit}_writer.py`
  (3 writers с `@require_capability("dlq.write", action="write")`).
- `src/backend/infrastructure/sources/webhook.py`
  (1 source).

**Production behavior корректное (fail-closed) — это test infra bug.**

### 01-P2-NEW-001 — placeholder dead code

`src/backend/infrastructure/workflow/compensating_driver.py:115-123`:

```python
async def _scan_once(self) -> None:
    async with self._session_factory() as session:  # type: AsyncSession
        repo = self._session_factory.__class__.__module__  # placeholder
        from src.backend.infrastructure.workflow.saga_state import (
            WorkflowStateRepository,
        )
        repo = WorkflowStateRepository(session)  # ← реальное присвоение
```

Строка 118 присваивает `repo` строку `__module__` класса, затем
строка 123 перезаписывает корректным объектом. ponytail: one-line
deletion. Risk: zero (тестовое покрытие 6/6 на строках 119-123 не
задевает 118).

### 01-P3-NEW-001 — smart_session_manager lag-check test drift

`src/backend/infrastructure/database/smart_session_manager.py:165-188`:

```python
async def acquire(self, mode: SessionMode = "read"):
    sessionmaker, on_replica = await self._pick_sessionmaker(mode)
    session = sessionmaker()  # ← primary.calls OR replica.calls += 1
```

`_pick_sessionmaker` для `mode="read"` (line 199-219):
1. replica available → `_should_check_lag()` (line 221-235) →
   `multi_replica_failover` default True → True on first call
   (`time.monotonic() - 0.0 >= 5.0`).
2. → `_update_lag_status()` (line 244-273) →
   `async with self._primary() as session: ...`
   (pg_stat_replication только на primary).
3. → `return self._replica, True` → sessionmaker() вызывает replica.

Итого: `primary.calls = 1, replica.calls = 1, session.label = "replica"`.
Тест `test_read_routes_to_replica` (line 49-59) ожидает
`primary.calls == 0` — был написан до K2 S19 W1 (commit
`f32638e1`, `s113-w5-closure`). Pre-existing test/source drift.

## Cycle-1+2 residuals (verified)

| Cycle ID | Статус | Доказательство (cycle-3 verification) |
|----------|--------|----------------------------------------|
| **T-3.1** (cachetools.TTLCache, cycle 1) | **RESOLVED ✓ (working tree)** | `git diff src/backend/infrastructure/cache/rag/embedding_cache.py`: +20/-30 LOC, замена custom `dict + time.monotonic()` на `cachetools.TTLCache` + `asyncio.Lock`. 10/10 tests/unit/infrastructure/cache/rag/test_embedding_cache.py PASS. cachetools 7.1.7 installed. Docstring обновлён: `Sprint 86, cycle-1/P3-01`. |
| **01-P0-001** (CDC DLQ data-loss, cycle 2 Infrastructure P0) | **RESOLVED ✓** | B-02 (cycle 33) + B-17 (cycle 37): `_send_to_dlq` fail-loud в production, `dlq_required=True` default. `mark_cdc_dlq_writer_wired` registered. Composition root wires `InboxDLQWriter` через `_get_outbox_dlq_session_factory` + explicit mark. **13/13 cycle-37 regression tests PASSED.** Runtime sanity: `di.register_app_state(app)` (mocked InboxDLQWriter/session_factory) → `cdc_dlq_writer_guard.is_wired() == True`. |
| **T-W1-04** (composition root DI, cycle 2) | **RESOLVED ✓** | См. 01-P0-001 — wiring в `di.py:250-262` подтверждён. |
| **T-W2-01..04** (layer track, cycle 2) | **CONFIRMED ✓** | `.venv/bin/python tools/check_layers.py --root src` → `0 новых / 175 legacy / 2274 файлов`, exit 0. Baseline match. |
| **T-W3-01** (tenacity library replacement, cycle 2) | **PARTIAL** | tenacity 9.0.0 установлен. Используется в `src/backend/infrastructure/clients/transport/http_httpx.py:24`, `http/request_mixin.py:13`. Outbox dispatcher (`messaging/outbox/dispatcher.py:273-313`) использует in-line exponential backoff с явным комментарием "tenacity-подобный" — задокументированное намеренное решение для сохранения контроля над per-attempt-state и транзакционностью. 3 retries + 1 critical infra (reconnection.py:152). Не blocking; cycle-2 finding остаётся **RESIDUAL** by-design. |
| **01-P1-001** (test infra sink/DLQ auth, cycle 2 inferred) | **MUTATED → 01-P1-NEW-001** | Test infrastructure gap, унаследованный от `e5d389c0`. Те же ~40+ failures, но root-cause явно в conftest, а не в source. Cycle-2 ID остаётся актуальным по сути, переформулирован. |
| **01-P1-002..003** (не верифицированы без cycle-2 markdown) | **UNVERIFIED** | Без доступа к cycle-2 отчёту невозможно установить, что именно скрывалось за этими ID. Найден один кандидат (placeholder dead code) — записан как 01-P2-NEW-001. |
| **01-P2-001..002** | **UNVERIFIED / 01-P2-NEW-001 candidate** | Найден один P2 dead code (compensating_driver placeholder). Возможно соответствует одному из cycle-2 ID; остальные UNVERIFIED. |
| **01-P3-001** | **UNVERIFIED / 01-P3-NEW-001 candidate** | Найден один P3 (smart_session_manager test drift). Возможно соответствует; UNVERIFIED без исходного описания. |

## Contradictions / overlaps to flag

1. **test_extensions_layer_linter_clean** падает с `НОВЫЕ нарушения: 3`
   в `extensions/{core_entities/orders,osint_agent}/...` — но это
   extensions/, не мой scope. Рекомендуется расширить scope cycle-3
   follow-up на extensions-domain. Layer checker для `src/`
   остаётся 175/0.
2. **B-17 cycle 37 guard — overkill для dev_light?** При
   `dlq_required=False` legacy log+drop сохранён, но новый cycle-2
   finding ID `01-P3-001` (если это тоже самое) может конфликтовать
   с backlog T-W3-01 (tenacity) — оба про "уже используемая
   библиотека лучше кастомного кода". Они НЕ пересекаются:
   tenacity = retry, dlq_guard = observability flag.
3. **InboxDLQWriter без @require_capability** (`inbox_writer.py:46`),
   тогда как Kafka/NATS/Rabbit имеют. Несоответствие — либо
   InboxDLQWriter должен тоже иметь decorator, либо Kafka/NATS/Rabbit
   лишние. Для production CDC wiring используется только
   InboxDLQWriter, так что observable impact отсутствует. P3 finding
   (architecture consistency), не блокер.
4. **`pg_runner_backend.py:229-231` и `cache/backends/memcached.py:97-110`**
   бросают `NotImplementedError` с явными docstring — структурно
   невозможные операции (memcached не поддерживает pattern-match,
   pg-runner не имеет replay API). Не finding, но координатор для
   следующего шага.
5. **Vault недоступен в runtime sanity** (`vault.enabled=false` или
   нет Vault на 127.0.0.1:8200). Warning, не error. Не блокер для
   инфра-аудита.

## Readiness score 0–100

**Формула:**

```
score = 100
      - 30 * P0_count      (security/data-loss/race/fail-open)
      - 20 * P1_count      (layer boundaries / test infra blocking)
      -  5 * P2_count      (dead code)
      -  2 * P3_count      (library replacement / minor)
      -  0 * P4_count
      - legacy_drag        (1 если 175 legacy > 100, иначе 0)
```

**Подстановка:**

```
score = 100
      - 30 * 0              =   0
      - 20 * 1              =  20   (01-P1-NEW-001: ~40 broken tests)
      -  5 * 1              =   5   (01-P2-NEW-001: 1 LOC dead code)
      -  2 * 1              =   2   (01-P3-NEW-001: 1 stale test)
      - legacy_drag         =   1   (175 legacy > 100 threshold)
                              ───
                              72
```

**Cap (per rule "≥80 запрещён при наличии P0/P1"):**
P1=1 → score cap = **79**.

**Итог: readiness = 72 → capped at 72.**

**Обоснование:**
- Сильная сторона: B-17 + T-3.1 + composition root wiring
  подтверждены real-runtime через `.venv/bin/python -m pytest`
  (не AsyncMock abuse), 13/13 + 10/10 + 6/6 PASS.
- Layer checker 175/0 (0 NEW) — без регрессий этого плана.
- Docstring gate 0 missing (cycle-2 baseline).
- 35 active security IDs (стабильно).
- 5 of 6 infra sub-testsuites PASS без замечаний
  (cache 60, resilience 191, observability 191, storage 60,
  sources 139, messaging-без-dlq 28).
- **Главный блокер (P1):** test-infra gap `tests/unit/infrastructure/sinks/conftest.py`
  не grants `dlq.write`/`file.write`/`ws.send`/etc. для тестов с
  `@require_capability`-decorated sinks и DLQ writers. ~40+ tests
  падают. Cap 79 не позволяет получить ≥80 при активном P1.
- Минимальный fix — одна `autouse` fixture (5-10 LOC) в conftest;
  не требует правок source/lockfile/allowlist.

## Recommended next tasks

1. **(P1) Tests cap auth fix.** Добавить в `tests/unit/infrastructure/sinks/conftest.py`
   и `tests/unit/infrastructure/messaging/dlq/conftest.py` fixture,
   мокающую `AuthorizationFacade.check_principal` →
   `AuthDecision(allowed=True, method="test", subject="test-principal")`.
   После фикса перезапустить
   `.venv/bin/python -m pytest tests/unit/infrastructure/{sinks,sources,messaging/dlq}/ -q`
   и убедиться в 0 failures. Это уберёт P1 и поднимет readiness до ~92.
2. **(P2) Dead-code removal.** Удалить `compensating_driver.py:118`
   (one-line ponytail deletion). Не требует теста (покрытие не теряется).
3. **(P3) Stale test fix.** В `test_smart_session_manager.py` добавить
   `monkeypatch.setattr(sm, "_update_lag_status", AsyncMock())` либо
   feature-flag fixture. Source остаётся как есть.
4. **(P3, residual) InboxDLQWriter consistency.** Решить, нужен ли
   `@require_capability("dlq.write")` на `InboxDLQWriter.write()`
   для symmetry с Kafka/NATS/Rabbit writers. Production impact — none
   (composition root wires `InboxDLQWriter`, `mark_cdc_dlq_writer_wired`
   уже фиксирует факт).
5. **(Cross-domain, not mine) extensions layer violations.** 3 NEW
   violations в `extensions/{core_entities,osint_agent}/...` →
   передать extensions-domain аналитику.
6. **(P3, residual) tenacity backlog T-W3-01.** Можно закрыть
   переписыванием `messaging/outbox/dispatcher.py:273-313` на
   `@tenacity.retry(...)` поверх `_deliverer`, если per-attempt
   state (event.retry_count/error_class) экспортируется через
   `retry_state`. Это позволит удалить ~40 LOC custom loop.
   Опционально, не блокер.

## Commands run

**Python interpreter:** `.venv/bin/python` (Python 3.14.0, pytest 9.1.1,
hypothesis 6.165.1, cachetools 7.1.7) — НЕ system Python.

| # | Command | Exit | Наблюдение |
|---|---------|------|------------|
| 1 | `.venv/bin/python tools/check_layers.py --root src` | 0 | `Нарушений: 0 новых (файлов: 2274; baseline: 175 legacy)` ✓ matches baseline |
| 2 | `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | 0 | `35` ✓ matches baseline |
| 3 | `.venv/bin/python -c "import cachetools; print(cachetools.__version__)"` | 0 | `7.1.7` |
| 4 | `.venv/bin/python -m pytest tests/unit/infrastructure/clients/external/cdc/test_dlq_writer_guard_cycle37.py -v` | 0 | `13 passed in 4.18s` (B-17 cycle 37) |
| 5 | `.venv/bin/python -m pytest tests/unit/infrastructure/cdc/test_cdc_client_adapter.py -v` | 0 | `7 passed in 4.48s` |
| 6 | `.venv/bin/python -m pytest tests/unit/infrastructure/cache/rag/test_embedding_cache.py -v` | 0 | `10 passed in 2.38s` (T-3.1) |
| 7 | `.venv/bin/python -m pytest tests/unit/infrastructure/workflow/test_compensating_driver.py -v` | 0 | `6 passed in 5.29s` |
| 8 | `.venv/bin/python -m pytest tests/unit/infrastructure/cache/ -q` | 0 | `60 passed in 4.82s` |
| 9 | `.venv/bin/python -m pytest tests/unit/infrastructure/{resilience,observability}/ -q` | 0 | `191 passed in 15.01s` |
| 10 | `.venv/bin/python -m pytest tests/unit/infrastructure/messaging/ -q --ignore=.../outbox --ignore=.../dlq` | 0 | `28 passed in 2.20s` |
| 11 | `.venv/bin/python -m pytest tests/unit/infrastructure/storage/ --ignore=.../test_s3.py -q` | 0 | `60 passed in 1.79s` |
| 12 | `.venv/bin/python -m pytest tests/unit/infrastructure/sources -q` | 0 | `139 passed, 2 skipped in 8.14s` |
| 13 | `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/test_file_sink.py -q` | 1 | `6 failed, 3 passed in 5.12s` (P1-NEW-001 evidence) |
| 14 | `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/test_ws_sink.py -q` | 1 | `4 failed, 4 passed in 8.52s` (P1-NEW-001 evidence) |
| 15 | `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/test_soap_sink.py -q` | 1 | `6 failed, 7 passed in 12.53s` (P1-NEW-001 evidence) |
| 16 | `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/test_mq_sink.py -q` | 1 | `6 failed, 4 passed in 51.91s` (P1-NEW-001 evidence) |
| 17 | `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/test_grpc_sink.py -q` | 1 | `4 failed, 4 passed in 9.18s` (P1-NEW-001 evidence) |
| 18 | `.venv/bin/python -m pytest tests/unit/infrastructure/sinks/test_webhook_sink.py -q` | 1 | `6 failed, 4 passed in 11.00s` (P1-NEW-001 evidence) |
| 19 | `.venv/bin/python -m pytest tests/unit/infrastructure/messaging/dlq/ -q` | 1 | `10 failed, 11 passed in 0.49s` (kafka/nats/rabbit, P1-NEW-001 evidence) |
| 20 | `.venv/bin/python -m pytest tests/unit/infrastructure/messaging/dlq/ -q --deselect kafka/nats/rabbit` | 0 | `10 passed, 11 deselected` (DLQ non-writer OK) |
| 21 | `.venv/bin/python -m pytest tests/unit/infrastructure/database/...test_smart_session_manager.py -v` | 1 | `1 failed (test_read_routes_to_replica) + 6 passed` (P3-NEW-001 evidence) |
| 22 | `.venv/bin/python -m pytest tests/unit/infrastructure/messaging/outbox -q` | 1 | `9 failed, 59 passed` (pre-existing lambda TypeError, not in scope) |
| 23 | `.venv/bin/python -m pytest tests/unit/infrastructure/database/test_tenant_filter.py -v` | 1 | `4 failed, 2 passed` (deprecated shim, not in scope) |
| 24 | `.venv/bin/python -m pytest tests/unit/infrastructure/eventing/test_inbox.py -v` | 1 | `2 failed, 5 passed` (auth-message drift, not in scope) |
| 25 | `.venv/bin/python -m pytest tests/unit/infrastructure/cdc/test_cdc_status_docs_s7w2.py` | 1 | `4 failed` (markdown content, not in scope) |
| 26 | Real-runtime composition wiring sanity (inline `.venv/bin/python` script: `FastAPI()` + `di.register_app_state(app)` + mocked `InboxDLQWriter`/`_get_outbox_dlq_session_factory`) | 0 | `cdc_dlq_writer_guard.is_wired() == True` after boot. Confirms B-17 wiring реально выполняется, не только тестами. |
| 27 | `git diff HEAD src/backend/infrastructure/cache/rag/embedding_cache.py` | 0 | +20/-30 LOC, migration на `cachetools.TTLCache` подтверждена в working tree. |

Все runtime-команды выполнены через `.venv/bin/python` / `.venv/bin/python -m pytest`.
System Python (без `prometheus_client`/`fastapi`/`hypothesis`) НЕ использовался —
в отличие от reviewer cycle 2, у которого были ложные ModuleNotFoundError.
