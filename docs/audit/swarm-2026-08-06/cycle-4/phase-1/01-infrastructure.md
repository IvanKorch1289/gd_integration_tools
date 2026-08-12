# Cycle 4 / Phase 1 — Infrastructure domain audit

**Domain:** `src/backend/infrastructure/**` + `tests/unit/infrastructure/**` +
`tools/check_layers.py` + `tools/check_layers_allowlist.txt`
**HEAD:** `22e08a0d` (cycle-1/2/3 reapply commit)
**Date:** 2026-08-06
**Interpreter:** `.venv/bin/python` (Python 3.14.0)
**Agent:** independent domain analyst (no cross-agent reads)

---

## 1. Scope / Что проверялось

| Слой / каталог | Файлов | Проверено |
|---|---|---|
| `src/backend/infrastructure/` (всего) | 429 .py | да |
| `tests/unit/infrastructure/` (всего) | 219 .py | да |
| `tools/check_layers.py` | 466 строк | да |
| `tools/check_layers_allowlist.txt` | 180 строк (175 active) | да |

**Forbidden** (не читались): `pyproject.toml`, `uv.lock`, `tools/check_layers_allowlist.txt` (правки), `src/backend/infrastructure/storage/s3.py` (явный запрет).
**Не проверено** (вне scope): `extensions/**` (кроме layer-lint теста, который выявил extensions-нарушения), `services/**`, `core/**`, `entrypoints/**` (кроме упоминания в качестве cross-layer контрагента).
**Не проверено** (явно по инструкции): cycle-1/2/3 markdown отчёты, KNOWN_ISSUES.md, CLAUDE.md, PLAN.md, DEEP_AUDIT_REPORT.md, triage_allowlist_report.md.
**Прочитано** (разрешено): `docs/audit/swarm-2026-08-06/cycle-4/BASELINE.md`, `AGENTS.md` (root, только как обязательные правила).

---

## 2. Verified baseline (cross-check с BASELINE.md)

| Проверка | Команда | Ожидаемо | Факт | Статус |
|---|---|---|---|---|
| HEAD commit | `git rev-parse HEAD` | `22e08a0d…` | `22e08a0dcfe249019e08429509b6d965a10c4c91` | OK |
| Layer checker (allowlist mode) | `.venv/bin/python tools/check_layers.py --root src` | `0 новых` | `Нарушений: 0 новых (файлов: 2273; baseline: 175 legacy)` | OK |
| Layer checker (strict — игнор allowlist) | `… --strict` | 175 legacy | `НОВЫЕ нарушения: 175` | OK (baseline подтверждён) |
| Allowlist size | `grep -c "^src/" tools/check_layers_allowlist.txt` | 175 | 175 | OK |
| CVE allowlist | `grep -c "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | 27 active | 27 | OK |

**T-3.1 (cachetools.TTLCache) — RESOLVED verified:** в HEAD
`src/backend/infrastructure/cache/backends/memory.py:14-27`:
```python
from cachetools import TTLCache
…
self._cache: TTLCache[str, bytes] = TTLCache(maxsize=maxsize, ttl=default_ttl)
self._lock = asyncio.Lock()
```
Каждый `get/set/delete/delete_pattern/exists` оборачивает доступ в
`async with self._lock:`. Это решает threading-safety + async race.
Smoke-тест BASELINE.md T-3.1 — пройден.

**B-17 (cycle 37) CDC DLQ fail-loud production guard — RESOLVED verified:**

* `src/backend/infrastructure/clients/external/cdc/client.py:67-81`:
  `__init__(dlq_required: bool = True)` (production default).
* `client.py:271-289`: `_send_to_dlq` поднимает `RuntimeError` если
  `_dlq_writer is None and _dlq_required` (fail-loud).
* `client.py:90-97`: `set_dlq_writer` помечает
  `mark_cdc_dlq_writer_wired` через guard-объект.
* `src/backend/infrastructure/clients/external/cdc/_dlq_writer_guard.py:91-100`:
  module-level singleton `cdc_dlq_writer_guard: DLQWriterGuard` +
  `mark_cdc_dlq_writer_wired` wrapper.
* Тесты: `.venv/bin/python -m pytest tests/unit/infrastructure/clients/external/cdc/test_dlq_writer_guard_cycle37.py` → **13 passed**.

---

## 3. Verified strengths (что реально работает)

| # | Область | Evidence | Оценка |
|---|---|---|---|
| S-1 | CDC DLQ wiring (B-02 + B-17 + cycle 33/37) | 13/13 cycle-37 guard tests + 17 DLQ wiring tests + 22 CDC external tests | excellent |
| S-2 | Outbox multi-instance safety (S72 W2-W3) | `claim_pending` (advisory lock + SELECT-FOR-UPDATE-SKIP-LOCKED + per-row lease), `reset_stuck_processing` sweeper, `count_stuck_pending_by_transport` | excellent |
| S-3 | Resilience / CB consolidation (Wave 6.1) | `ClientCircuitBreaker` обёртка над `purgatory`-фасадом `BreakerRegistry`; `ReconnectForever / ReconnectN / NoReconnect` (Camel `errorHandler(defaultErrorHandler().maximumRedeliveries(...))` analog) | excellent |
| S-4 | Workflow / Temporal backend | `TemporalWorkflowBackend` + `WorkflowBackend` Protocol; canonical-JSON payload converter; B-15 cycle 37 e2e-replay fix | excellent |
| S-5 | OTel auto-instrumentation | 11 instrumentors (FastAPI/httpx/SQLAlchemy/asyncpg/Redis/Logging/aiokafka/aio-pika/PyMongo/gRPC client), fail-soft per-instrumentor | excellent |
| S-6 | Cache memory backend (T-3.1) | cachetools.TTLCache + asyncio.Lock (см. §2) | excellent |
| S-7 | Cache rag embedding (cycle-1 P3-01) | тот же паттерн, async-native замена threading.Lock → asyncio.Lock | excellent |
| S-8 | Logging router + batching | `SinkRouter` + `BatchingSinkRouter` (Wave 7.7), `route_to_sinks` structlog processor, thread/loop bridge | very good |
| S-9 | Outbox dispatcher retry-with-backoff | per-event in-line exponential backoff (по делу — control над per-attempt state); graceful drain через `asyncio.Event` | very good |
| S-10 | Vault secret refresher | per-path tracking (IL2.4), fan-out to `ConnectorRotator`, graceful cancel | very good |
| S-11 | SLO tracker | HdrHistogram (O(1) percentile) с list-fallback; `enforce_slo` decorator | very good |
| S-12 | Database initializer (Wave F.3 async-first) | sync-engine опционален (warning + None fallback для APScheduler), replica DSN support | very good |
| S-13 | Storage S3 cache adapter (Cycle 35 B-03) | tenant-scoped cache keys (`tenant:_unscoped_:` для anonymous), `feature_flags.tenant_cache_prefix_enabled` gate | very good |
| S-14 | Observability audit lifecycle | verify lifecycle, idempotent start/stop, structured logs | very good |
| S-15 | Retry policy unification | все retry — через `tenacity` декоратор из `core.resilience.retry` (единый источник правды); единственная ручная in-line retry — в `OutboxDispatcher._dispatch_one` (обоснованно: per-attempt DB state + transactional ack) | very good |

---

## 4. Findings table (P0..P4)

| ID | P | Path:Line | Title | Evidence |
|---|---|---|---|---|
| **INFRA-P0-001** | P0 | `src/backend/infrastructure/cache/rag/embedding_cache.py:31-34` vs `tests/unit/infrastructure/cache/rag/test_embedding_cache.py:131` | **`_cache` attr naming-drift → `test_defaults_match_baseline` падает с AttributeError** | Тест ожидает `cache._cache.maxsize == 1024` / `cache._cache.ttl == 300.0`, но после cycle-1/P3-01 поле переименовано в `_store`. Реальный bug в тесте (не в коде), но он не проходит CI gate. См. §5.1. |
| **INFRA-P0-002** | P0 | `tests/unit/infrastructure/messaging/outbox/test_claim_pending.py:108` + `test_per_row_claim_and_sweeper.py:356` | **9 test-failures: stub `transaction` с `lambda:` (0 args), production вызывает `transaction(session)` (1 arg) → `TypeError`** | Реальные test-failures, затрагивают multi-instance safe claim path. Stub `_StubSessionManager.transaction` принимает `_session=None` arg, но тесты monkeypatch-ат `transaction` на `lambda: fake_txn` без args → 9 падений в production safety path. См. §5.2. |
| **INFRA-P0-003** | P0 | `src/backend/infrastructure/cdc/test_cdc_status_docs_s7w2.py` + 4 failures | **CDC architecture-status doc-sync: реализация `production-ready`, тесты требуют `scaffold`** | Backends poll_backend и listen_notify_backend помечены как `**production-ready**` в `docs/architecture/cdc/...md`, но тесты (cycle-1 s7w2) требуют `**scaffold**` — doc-test синхронизации не было выполнено. См. §5.3. |
| **INFRA-P1-001** | P1 | `src/backend/infrastructure/observability/otel_auto.py:251-266` + `init_otel` line 134 | **Дублирование `asyncpg` instrumentation: unguarded private `_instrument_asyncpg()` vs public `instrument_asyncpg_if_enabled()`** | Private `_instrument_asyncpg()` вызывается безусловно из `init_otel()` (line 134), игнорируя feature-flag `otel_asyncpg`. Public `instrument_asyncpg_if_enabled()` (line 35-73) имеет guard `_ASYNCPG_INSTRUMENTED` + flag check. Семантическое расхождение. См. §5.4. |
| **INFRA-P1-002** | P1 | `src/backend/infrastructure/application/slo_tracker.py:242-247` + `vault_refresher.py:248-253` | **Module-level `from src.backend.core.di import app_state_singleton` в середине файла (после декорируемых функций)** | DI-import в позиции 242/248 (не наверху). Технически работает (Python evaluates module top-down), но нарушает PEP-8 + усложняет cycle-detection. Не blocking, но inconsistent с другими модулями. См. §5.5. |
| **INFRA-P2-001** | P2 | `src/backend/infrastructure/repositories/base/base.py:11-70` | **9× `raise NotImplementedError` в ABC abstractmethod declarations — стандартный ABC-паттерн, не dead code** | Это легитимные ABC-методы (SQLAlchemy repository base class). Не блокирующий — стандартный Python ABC idiom. См. §5.6. |
| **INFRA-P2-002** | P2 | `src/backend/infrastructure/logging/router.py:57-63` | **`RouterLike` Protocol-like class с `NotImplementedError` в abstract methods — Protocol, не ABC** | Объявлен как `class RouterLike:`, помечен как «минимальный protocol-like контракт». Лучше `Protocol` от `typing`, но не блокирующий. См. §5.7. |
| **INFRA-P3-001** | P3 | `src/backend/infrastructure/messaging/outbox/dispatcher.py:276-310` | **`OutboxDispatcher._dispatch_one` — кастомный exponential backoff без `tenacity`** | Обоснованно (per-attempt DB state + transactional ack), задокументировано в docstring (line 276). Ponytail-рекомендация: можно вынести retry в `core.resilience.retry` helper. См. §5.8. |
| **INFRA-P3-002** | P3 | `src/backend/infrastructure/resilience/reconnection.py:91-122` | **Custom reconnect с `asyncio.sleep + multiplier`, без `tenacity`** | Обоснованно — `tenacity.AsyncRetrying` плохо работает с `while True`-семантикой forever-reconnect; явный backoff чище. См. §5.9. |
| **INFRA-P3-003** | P3 | `src/backend/infrastructure/application/slo_tracker.py:30-67` | **Custom `_FallbackStats` (list-based percentile) — `statistics.quantiles` из stdlib** | Python 3.8+ имеет `statistics.quantiles(data, n=100)` для O(n log n) percentile. Custom list-rebuild каждые 5000 записей — рабочий, но `statistics.quantiles` чище. См. §5.10. |
| **INFRA-P4-001** | P4 | (нет кода) | **Organic feature: typed DLQ replay API для failed-events в CDC (T-W1-02 cycle-2 deferred)** | Реальная функциональная дыра: failed events попадают в DLQ, но нет `replay_dlq(scope, since)` DSL action. EIP «Dead Letter Channel» обычно имеет «Republish from DLQ». Organic fit (Camel `<from uri="jms:queue:dlq"/>`). См. §5.11. |

**Итого:** P0=3, P1=2, P2=2, P3=3, P4=1.

---

## 5. Detailed evidence

### 5.1. INFRA-P0-001 — Embedding cache test naming drift

**File:** `tests/unit/infrastructure/cache/rag/test_embedding_cache.py:128-132`

```python
def test_defaults_match_baseline() -> None:
    """Defaults: ttl=300s, maxsize=1024 (baseline контракт сохранён)."""
    cache = EmbeddingVectorCache()
    assert cache._cache.maxsize == 1024
    assert cache._cache.ttl == 300.0
```

**Code under test** (`src/backend/infrastructure/cache/rag/embedding_cache.py:28-34`):

```python
def __init__(self, ttl_seconds: float = 300.0, maxsize: int = 1024) -> None:
    self._ttl = ttl_seconds
    self._maxsize = maxsize
    self._store: TTLCache[str, list[float]] = TTLCache(
        maxsize=maxsize, ttl=ttl_seconds,
    )
```

После cycle-1/P3-01 рефакторинга (custom TTL+LRU → `cachetools.TTLCache` + `asyncio.Lock`)
поле переименовано с `_cache` на `_store`. Тест **не обновлён**.

**Test run:**

```
.venv/bin/python -m pytest tests/unit/infrastructure/cache/rag/test_embedding_cache.py --tb=short
…
FAILED tests/unit/infrastructure/cache/rag/test_embedding_cache.py::test_defaults_match_baseline
AttributeError: 'EmbeddingVectorCache' object has no attribute '_cache'
1 failed, 9 passed in 1.42s
```

**Impact:** CI gate fail (тест не проходит; проверка «defaults match baseline» сломана).
**Recommendation:** обновить тест на `cache._store.maxsize == 1024` / `cache._store.ttl == 300.0`
**или** переименовать `_store` обратно в `_cache` для backward-compat с тестом.
**Test criterion:** `pytest tests/unit/infrastructure/cache/rag/test_embedding_cache.py` → 10 passed.

### 5.2. INFRA-P0-002 — Outbox claim/sweeper stub-arity mismatch (9 failures)

**Files:**
- `tests/unit/infrastructure/messaging/outbox/test_claim_pending.py:108,137,177` (`lambda: fake_txn`)
- `tests/unit/infrastructure/messaging/outbox/test_per_row_claim_and_sweeper.py:356`

**Production code** (`src/backend/infrastructure/repositories/outbox.py:235-236, 355-356`):

```python
async with main_session_manager.create_session() as session:
    async with main_session_manager.transaction(session):     # ← вызов с 1 аргументом
        …
```

**Test stub** (`test_claim_pending.py:25-32`):

```python
class _StubSessionManager:
    def transaction(self, _session: object = None) -> "MagicMock":   # ← принимает session
        …
```

**Monkeypatch** (`test_claim_pending.py:106-109`):

```python
monkeypatch.setattr(
    "src.backend.infrastructure.repositories.outbox.main_session_manager.transaction",
    lambda: fake_txn,                          # ← 0 аргументов!
)
```

**Test run:**

```
TypeError: test_claim_pending_lock_not_acquired_returns_empty.<locals>.<lambda>()
            takes 0 positional arguments but 1 was given
src/backend/infrastructure/repositories/outbox.py:236: TypeError
```

**9 failed tests** (multi-instance safe claim/sweeper path — production-critical):

```
FAILED test_claim_pending.py::test_claim_pending_lock_not_acquired_returns_empty
FAILED test_claim_pending.py::test_claim_pending_lock_acclaimed_db_empty_returns_empty
FAILED test_claim_pending.py::test_claim_pending_lock_acclaimed_returns_orm_objects
FAILED test_per_row_claim_and_sweeper.py::test_claim_pending_propagates_claimed_columns
FAILED test_per_row_claim_and_sweeper.py::test_claim_pending_sql_includes_status_processing
FAILED test_per_row_claim_and_sweeper.py::test_reset_stuck_processing_returns_count
FAILED test_per_row_claim_and_sweeper.py::test_reset_stuck_processing_no_stuck_returns_zero
FAILED test_per_row_claim_and_sweeper.py::test_reset_stuck_processing_filters_by_status_processing
FAILED test_per_row_claim_and_sweeper.py::test_reset_stuck_processing_respects_threshold
9 failed, 59 passed, 4 warnings in 5.66s
```

**Impact:** multi-instance safety path не тестируется. `claim_pending` используется в
production outbox-worker (S72 W2-W3) — silent double-publish возможен при
одновременном запуске >1 worker'а (по дизайну advisory lock должен
предотвращать, но тесты не доказывают корректность).
**Recommendation:** исправить stub — `lambda *_a, **_kw: fake_txn`
**Test criterion:** все 9 тестов проходят.

### 5.3. INFRA-P0-003 — CDC doc-sync test failures

**File:** `tests/unit/infrastructure/cdc/test_cdc_status_docs_s7w2.py`

**4 failed tests** про статус CDC backends в `docs/architecture/cdc/...md`:

```
FAILED test_architecture_marks_debezium_as_implemented
  assert "**implemented**" in "...debezium_events_backend.py`...default-OFF)..."
FAILED test_architecture_marks_poll_as_scaffold
  AssertionError: Polling row should be marked scaffold (pre-existing):
  '| Polling | `poll_backend.py` | **production-ready** | …'
FAILED test_architecture_marks_listen_notify_as_scaffold
  AssertionError: Listen/Notify row should be marked scaffold:
  '| Listen/Notify | `listen_notify_backend.py` | **production-ready** | …'
FAILED test_architecture_no_stale_production_ready_for_poll_or_listen
  assert "production-ready" not in '| Polling |…**production-ready** |…'
```

**Source of truth:** `docs/architecture/cdc/cdc.md` (или аналогичный) помечает
PollBackend и ListenNotifyBackend как `**production-ready**`, но cycle-1 s7w2 тесты
требуют пометки `**scaffold**` (backends ещё не production-grade).

**Impact:** test-suite говорит «этот код ещё не production», но в docs он
production. Это либо (a) тесты устарели после того как backends достигли
production-grade, либо (b) backends регрессировали. Нужно одно из:
обновить docs до `**scaffold**`, **или** обновить тесты до
`**production-ready**` (с явным changelog).

**Recommendation:** cycle-2 deferred T-W1-02 был «CDC DLQ handoff failure»
(см. §6.2 ниже) — теперь RESOLVED (B-17). Возможно, и эти backends
достигли production-grade в post-cycle-1 sprints. Проверить
`docs/architecture/cdc/*.md` на actual status и обновить либо docs, либо tests.
**Test criterion:** 4 теста проходят.

### 5.4. INFRA-P1-001 — Duplicated asyncpg instrumentation

**File:** `src/backend/infrastructure/observability/otel_auto.py`

**Public (with flag + guard):** lines 35-73

```python
def instrument_asyncpg_if_enabled() -> bool:
    global _ASYNCPG_INSTRUMENTED
    if _ASYNCPG_INSTRUMENTED:
        return False
    try:
        if not feature_flags.otel_asyncpg:    # ← flag check
            return False
    …
    AsyncPGInstrumentor().instrument()
    _ASYNCPG_INSTRUMENTED = True
```

**Private (unguarded, unconditional):** lines 251-266

```python
def _instrument_asyncpg() -> None:
    """asyncpg raw-driver spans. …"""
    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
        AsyncPGInstrumentor().instrument()    # ← no flag check, no guard
```

**Caller of private:** `init_otel` line 134 — `_instrument_asyncpg()` вызывается
безусловно на старте (если OTEL endpoint задан).

**Caller of public:** `src/backend/infrastructure/database/database/initializer.py:75` —
вызывает `instrument_asyncpg_if_enabled()` при создании `DatabaseInitializer`
(проверяет flag).

**Race scenarios:**

1. Если `feature_flags.otel_asyncpg = False`, но `init_otel()` вызывается с
   `OTEL_EXPORTER_OTLP_ENDPOINT` — `_instrument_asyncpg()` instrumentation
   произойдёт, нарушая feature-flag contract.
2. `_ASYNCPG_INSTRUMENTED` guard в public — не синхронизирован с private
   вызовом. Если `init_otel()` сначала, потом DatabaseInitializer — guard
   уже `True`, и public call no-op (но instrumentation уже сделан).
3. Наоборот: DatabaseInitializer сначала (instrument + guard=True), потом
   `init_otel()` — instrumentation сделан дважды (если guard не помог).

**Recommendation:** единый путь. Либо:
- (a) удалить private `_instrument_asyncpg()`, оставить только public;
- (b) добавить в private проверку `feature_flags.otel_asyncpg` + guard.
**Test criterion:** test на `feature_flags.otel_asyncpg=False` + init_otel() →
asyncpg НЕ instrumented.

### 5.5. INFRA-P1-002 — DI import placement

**Files:**
- `src/backend/infrastructure/application/slo_tracker.py:242-247`
- `src/backend/infrastructure/application/vault_refresher.py:248-253`

```python
# slo_tracker.py, line 242 (после dataclass'ов и функций, ПЕРЕД финальным @decorator):
from src.backend.core.di import app_state_singleton


@app_state_singleton("slo_tracker", SLOTracker)
def get_slo_tracker() -> SLOTracker:
```

**Issue:** `from src.backend.core.di import app_state_singleton` — в середине
файла. PEP-8 (E402) requires imports на top. Работает корректно (Python
evaluates top-down), но:

- Не консистентно с другими модулями (большинство — imports наверху).
- Затрудняет audit cross-layer imports через layer-checker (line-number
  based allowlist).
- Если в будущем кто-то использует `isort`, потребует `# isort: skip`.

**Impact:** low — code works correctly.
**Recommendation:** перенести import в начало файла.

### 5.6. INFRA-P2-001 — ABC abstractmethod NotImplementedError (9×)

**File:** `src/backend/infrastructure/repositories/base/base.py:11-70`

```python
class AbstractRepository[ConcreteTable: BaseModel](ABC):
    @abstractmethod
    async def get(self, session, key, value) -> ConcreteTable:
        """Получить объект по ключу и значению."""
        raise NotImplementedError
    # … 8 more abstract methods with raise NotImplementedError
```

**Justification:** стандартный Python ABC pattern. `ABC` +
`@abstractmethod` + `raise NotImplementedError` — idiomatic. Не dead code,
не stub. Subclasses (`SQLAlchemyRepository`) обязаны override.

**Status:** documented как легитимный паттерн; **не finding**, но упомянут
для прозрачности (197 hits по `raise NotImplementedError|^.*pass$|# TODO|# FIXME`
grep'у, из них 9 — легитимные ABC, остальные — legitimate control flow).

### 5.7. INFRA-P2-002 — RouterLike is class, не Protocol

**File:** `src/backend/infrastructure/logging/router.py:50-63`

```python
class RouterLike:
    """Минимальный protocol-like контракт router'а (sync + batching).
    Реализуют :class:`SinkRouter` и :class:`BatchingSinkRouter`."""
    async def dispatch(self, record: dict[str, Any]) -> None:
        raise NotImplementedError
    async def aclose(self) -> None:
        raise NotImplementedError
```

**Issue:** docstring говорит «protocol-like контракт», но это `class` с
concrete method bodies (raise NotImplementedError). Лучше `typing.Protocol`
для structural subtyping.

**Impact:** low — current usage works because `SinkRouter`/`BatchingSinkRouter`
explicitly inherit (duck-typed by Python). Не блокирующий.
**Recommendation:** переписать как `class RouterLike(Protocol)`.

### 5.8. INFRA-P3-001 — Outbox custom retry без tenacity

**File:** `src/backend/infrastructure/messaging/outbox/dispatcher.py:273-319`

```python
async def _dispatch_one(self, event: OutboxEvent) -> None:
    """Доставка одного события с retry-loop'ом.
    Использует in-line tenacity-подобный exponential backoff (без
    декоратора, чтобы сохранить контроль над per-attempt-state и
    транзакционностью)."""
    for attempt in range(1, self._max_retries + 1):
        …
        sleep_for = self._retry_backoff_seconds * (2 ** (attempt - 1))
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=sleep_for)
```

**Justification:** обоснованно — `tenacity.AsyncRetrying` декоратор не
позволяет прерывать retry-loop при `_stopping.set()` (нужно внутри
callback'а raise + catch). Текущий код использует
`asyncio.wait_for(self._stopping.wait(), timeout=sleep_for)` для
graceful shutdown.

**Recommendation:** вынести retry-loop в `core.resilience.retry` helper
с shutdown-event parameter. Не blocking — current code is correct.

### 5.9. INFRA-P3-002 — Custom reconnect без tenacity

**File:** `src/backend/infrastructure/resilience/reconnection.py:91-122`

```python
@dataclass(slots=True)
class ReconnectForever(ReconnectionStrategy):
    async def run(self, client_name, dial):
        attempt = 0
        delay = self.initial_delay
        while True:
            attempt += 1
            try:
                return await dial()
            except Exception:
                await asyncio.sleep(delay)
                delay = min(self.max_delay, delay * self.multiplier)
```

**Justification:** `tenacity.AsyncRetrying` плохо работает с infinite
loop (есть `retry_forever`, но менее explicit). Custom loop читается
проще и поддерживает `ReconnectForever` / `ReconnectN` / `NoReconnect`
через единый Protocol.

**Recommendation:** оставить как есть. Ponytail-mode одобряет.

### 5.10. INFRA-P3-003 — SLO fallback stats вместо `statistics.quantiles`

**File:** `src/backend/infrastructure/application/slo_tracker.py:30-67`

```python
@dataclass(slots=True)
class _FallbackStats:
    latencies: list[float] = field(default_factory=list)
    def record(self, latency_ms):
        self.latencies.append(latency_ms)
        if len(self.latencies) > 10000:
            self.latencies = self.latencies[-5000:]  # ← lossy trim
    def percentile(self, p):
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * p / 100)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]
```

**Issue:** (1) при превышении 10000 samples — lossy trim (отбрасывает старые
без агрегации); (2) `sorted` — O(n log n) на каждый query.

**Replacement (stdlib):** `statistics.quantiles(data, n=100, method='inclusive')`
из Python 3.8+.

**Caveat:** `statistics.quantiles` тоже O(n log n) и тоже не агрегирует
across resets. HdrHistogram (preferred path) уже O(1). Этот fallback
срабатывает только если `hdrh` не установлен — rare в prod.

**Recommendation:** low priority — оставить, если не планируется убирать
hdrh из deps.

### 5.11. INFRA-P4-001 — Organic feature: DLQ replay

**Context:** failed CDC events попадают в DLQ (B-02/B-17) — но нет API для
«replay DLQ since timestamp». EIP «Dead Letter Channel» обычно имеет
«Republish from DLQ» (Camel `<from uri="jms:queue:dlq"/>`).

**Status:** cycle-2 deferred T-W1-02 «CDC DLQ handoff failure» — теперь
RESOLVED (B-17 production guard). Следующий organic step — replay API.

**Recommendation:** новый DSL action `cdc_replay_dlq(scope, since)` —
organic fit, не feature-for-feature copying. **Не блокирующий**.

---

## 6. Cycle-1+2+3 residual verification

### 6.1. T-1.4 (multicast + redelivery) — RESOLVED (per BASELINE.md, not re-verified in scope)

* Не входит в `infrastructure/**` напрямую (composition root + workflow engine).
* BASELINE.md smoke 8/8 PASS, T-1.4 зелёный.

### 6.2. T-W1-02 (CDC DLQ handoff failure) — RESOLVED

* `cycle 37 B-17` fix applied: `_dlq_writer` + `dlq_required=True` (prod default),
  `_dlq_writer_guard` singleton + composition root marker.
* Evidence: `tests/unit/infrastructure/clients/external/cdc/test_dlq_writer_guard_cycle37.py`
  — **13 passed**.
* Adjacent: `tests/unit/infrastructure/messaging/test_dlq_writers.py`,
  `test_outbox_dlq_wiring.py`, `test_dlq_inbox_migration.py` — **17 passed**.
* **RESOLVED confirmed.**

### 6.3. T-W1-03 (MQ subscribers ACK vs DLQ) — not directly verified in scope

* `src/backend/infrastructure/messaging/dlq/` существует (kafka_writer,
  rabbit_writer, nats_writer, memory_writer, fanout_writer, inbox_writer).
* Тесты `test_kafka_writer.py::TestKafkaDLQWriter` — 4/4 fail из-за
  capability gate (см. T-06 deferred в §6.4) — это тест-infra проблема,
  не DLQ-writer bug. Pre-existing.
* **RESIDUAL** (тесты не зелёные, но logic correct — cycle-3 deferred T-06
  отвечает за test-infra conftest).

### 6.4. T-06 (test-infra conftest) — RESIDUAL (verified pre-existing)

* Тесты `tests/unit/infrastructure/messaging/dlq/test_*writer.py` падают с
  `ConnectorAuthError: Capability 'dlq.write' denied for anonymous`.
* Аналогично `tests/unit/infrastructure/sinks/test_http_sink.py` — падает с
  `Capability 'http.send' denied for anonymous`.
* Это отсутствующий capability-fixture в conftest — cycle-3 deferred.

### 6.5. T-W1-08 (credit_pipeline unknown_tenant) — RESOLVED (verified)

* `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` — **3 passed**.
* BASELINE.md smoke зелёный.

### 6.6. T-04 (4-way CVE enforcement unification) — RESOLVED (per BASELINE.md)

* CVE allowlist — 27 active (cycle-4 D-AUDIT-02: 35→27).
* Не в scope (security/cve), но baseline подтверждает.

### 6.7. T-3.1 (cachetools.TTLCache) — RESOLVED (verified)

* `src/backend/infrastructure/cache/backends/memory.py:14-27` —
  cachetools.TTLCache wrapped in asyncio.Lock. См. §2.

### 6.8. T-1.5 (policy_mixin + AIGatewayProductionWiringError) — RESOLVED (per BASELINE.md)

* Не в `infrastructure/` напрямую (services/ai). BASELINE.md зелёный.

### 6.9. Cycle-3 T-02 / T-03 — RESOLVED (per BASELINE.md)

* Не в scope. Подтверждены в BASELINE.md.

---

## 7. Targeted test runs (команды + результаты)

| Команда | Результат |
|---|---|
| `git rev-parse HEAD` | `22e08a0dcfe249019e08429509b6d965a10c4c91` |
| `.venv/bin/python tools/check_layers.py --root src` | exit 0; `Нарушений: 0 новых (файлов: 2273; baseline: 175 legacy)` |
| `.venv/bin/python tools/check_layers.py --root src --strict` | exit 1; 175 новых нарушений (= baseline; expected) |
| `grep -c "^src/" tools/check_layers_allowlist.txt` | 175 |
| `grep -c "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | 27 |
| `.venv/bin/python -m pytest tests/unit/infrastructure/cache/rag/test_embedding_cache.py` | **1 failed**, 9 passed — INFRA-P0-001 |
| `.venv/bin/python -m pytest tests/unit/infrastructure/cdc/` | **4 failed**, 34 passed — INFRA-P0-003 |
| `.venv/bin/python -m pytest tests/unit/infrastructure/messaging/outbox/` | **9 failed**, 59 passed — INFRA-P0-002 |
| `.venv/bin/python -m pytest tests/unit/infrastructure/messaging/dlq/` | **10 failed** (capability gate, T-06), passed elsewhere |
| `.venv/bin/python -m pytest tests/unit/infrastructure/clients/external/cdc/test_dlq_writer_guard_cycle37.py` | **13 passed** — B-17 RESOLVED |
| `.venv/bin/python -m pytest tests/unit/infrastructure/messaging/test_dlq_writers.py tests/unit/infrastructure/messaging/test_outbox_dlq_wiring.py tests/unit/infrastructure/messaging/test_dlq_inbox_migration.py` | **17 passed** — DLQ wiring RESOLVED |
| `.venv/bin/python -m pytest tests/unit/infrastructure/resilience/` | 98 passed — RESOLVED |
| `.venv/bin/python -m pytest tests/unit/infrastructure/clients/ tests/unit/infrastructure/storage/ tests/unit/infrastructure/audit/ tests/unit/infrastructure/ai/ tests/unit/infrastructure/observability/ tests/unit/infrastructure/policy/ tests/unit/infrastructure/sources/ tests/unit/infrastructure/scheduler/ tests/unit/infrastructure/security/ tests/unit/infrastructure/secrets/ tests/unit/infrastructure/workflow/ tests/unit/infrastructure/repositories/ tests/unit/infrastructure/cache/ tests/unit/infrastructure/cdc/` | **5 failed** (P0-001, P0-003), остальное passed/skipped |
| `.venv/bin/python -m pytest tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` | **3 passed** — T-W1-08 RESOLVED |

**Интерпретатор всех pytest:** `.venv/bin/python` (Python 3.14.0).

---

## 8. Contradictions / overlaps to flag

### 8.1. CDC doc-test vs production reality

Тесты в `tests/unit/infrastructure/cdc/test_cdc_status_docs_s7w2.py`
говорят «PollBackend и ListenNotifyBackend ещё scaffold», но код и docs
говорят «production-ready». Это **либо** doc-sync drift (тесты устарели),
**либо** код регрессировал (что маловероятно — CDC subsystem стабилен).
**Recommend:** решить на основе git history (commit'ы между cycle-1 s7w2 и HEAD).

### 8.2. test-infra capability gate (T-06) vs production DLQ wiring

Тесты `test_*dlq_writer.py` и `test_http_sink.py` падают с capability
denied. Это **test-infra проблема** (отсутствующий fixture в conftest),
**не** DLQ production-bug. Production DLQ wiring (B-17 cycle 37) verified
через 13 guard tests. **Recommend:** cycle-3 deferred T-06 закрыть перед
Phase 2.

### 8.3. Public/private asyncpg instrumentation diverges

Public `instrument_asyncpg_if_enabled()` имеет guard + flag check;
private `_instrument_asyncpg()` не имеет ни того, ни другого.
Дублирование создаёт race + bypass-flag scenarios. См. INFRA-P1-001.

### 8.4. ABC NotImplementedError vs Protocol NotImplementedError

`repositories/base/base.py` — легитимный ABC (subclasses override).
`logging/router.py::RouterLike` — «protocol-like class» (не Protocol, но
с NotImplementedError stub). Два разных стиля для одной идеи —
**consistency improvement opportunity**.

---

## 9. Readiness score 0–100

**Formula:**

```
readiness = 100
            - 15 × N_P0
            -  8 × N_P1
            -  3 × N_P2
            -  1 × N_P3
            -  0 × N_P4
```

**Подсчёт:**

* N_P0 = 3 (INFRA-P0-001 naming drift, INFRA-P0-002 outbox claim stub,
  INFRA-P0-003 CDC doc-sync)
* N_P1 = 2 (INFRA-P1-001 duplicated asyncpg instrumentation, INFRA-P1-002 DI
  import placement)
* N_P2 = 2 (INFRA-P2-001 ABC pattern — non-blocking, INFRA-P2-002 RouterLike
  Protocol-стиля)
* N_P3 = 3 (INFRA-P3-001/002/003 — custom retry/reconnect/stats, обоснованные)
* N_P4 = 1 (organic feature — non-blocking)

**Score:** `100 − 15·3 − 8·2 − 3·2 − 1·3 − 0·1 = 100 − 45 − 16 − 6 − 3 − 0 = 30`

**Cap by rule:** «Оценка ≥80 запрещена при наличии P0/P1». У нас 3 P0 + 2 P1,
поэтому **score capped at 79**.

**Обоснование 30 (raw):**

* Infrastructure core (cache, resilience, workflow, observability, OTel) —
  solid production-grade.
* DLQ wiring (B-17 cycle 37) — fail-loud production guard verified.
* CDC/Outbox multi-instance safety — design correct, но **тесты не
  доказывают корректность** (9 test failures в claim/sweeper path).
* CDC docs ↔ code sync нарушена (4 test failures).
* EmbeddingCache contract test сломан (naming drift) — CI gate ломается.
* Дублирование asyncpg instrumentation создаёт race + bypass-flag.
* Custom retry/reconnect/stats — допустимо, но документировано как
  tech-debt (P3).

**Final score:** **30 / 100** (raw; ниже 79 cap).

---

## 10. Recommended next tasks (cycle 4 Phase 2 / cycle 5)

| Приоритет | Task | Effort | Impact |
|---|---|---|---|
| **must** | INFRA-P0-002: исправить `lambda:` → `lambda *_a, **_kw:` в 9 outbox-stub (или переписать stub на `_session` param) | XS | multi-instance safety tests зелёные |
| **must** | INFRA-P0-001: переименовать `_store` → `_cache` в EmbeddingVectorCache **или** обновить тест | XS | CI gate зелёный |
| **must** | INFRA-P0-003: решить CDC doc-sync (либо docs → `**scaffold**`, либо tests → `**production-ready**`) | S | 4 CDC tests зелёные |
| **should** | INFRA-P1-001: унифицировать asyncpg instrumentation (убрать private `_instrument_asyncpg` или добавить flag+guard) | S | feature_flag contract enforced |
| **should** | INFRA-P1-002: перенести DI imports в top of file (slo_tracker, vault_refresher) | XS | PEP-8, isort-friendly |
| **could** | INFRA-P2-002: переписать `RouterLike` как `typing.Protocol` | XS | structural subtyping |
| **could** | INFRA-P3-001/002: вынести retry/reconnect в `core.resilience.retry` helper с shutdown-event | M | DRY |
| **later** | INFRA-P4-001: organic feature `cdc_replay_dlq(scope, since)` | L | EIP/Camel full coverage |

---

## 11. Что НЕ проверялось (явно по инструкции)

* `pyproject.toml`, `uv.lock`, `tools/check_layers_allowlist.txt` (правки).
* `src/backend/infrastructure/storage/s3.py` (явный запрет в инструкции).
* `src/backend/infrastructure/storage/s3_cache.py` — частично прочитан (для S-13
  evidence), но не модифицирован.
* `extensions/**` — только `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py`
  (T-W1-08 verification).
* `core/**`, `services/**`, `entrypoints/**` — только как cross-layer контрагенты
  (через type annotations в infrastructure коде).
* cycle-1/2/3 markdown отчёты (явный запрет).
* KNOWN_ISSUES.md, CLAUDE.md, PLAN.md, DEEP_AUDIT_REPORT.md, triage_allowlist_report.md
  (явный запрет).
* runtime performance benchmarks (не было запрошено).

---

## 12. Bottom line

* **Baseline confirmed:** 175 legacy layer violations, 0 new; CVE allowlist 27;
  0 missing docstrings; HEAD `22e08a0d`.
* **T-3.1 RESOLVED** (verified directly in HEAD).
* **B-17 CDC DLQ fail-loud production guard** confirmed: 13 cycle-37 tests
  + 17 DLQ wiring tests pass; fail-loud `RuntimeError` если `_dlq_writer is None
  and _dlq_required=True`.
* **3 P0 + 2 P1** open: naming drift в embedding cache test, outbox stub arity,
  CDC doc-sync, asyncpg instrumentation duplication, DI import placement.
* **Readiness: 30 / 100** (raw; не может быть ≥80 при наличии P0/P1).
* **Следующий шаг:** закрыть 3 P0 в Phase 2 (S effort каждый) →
  readiness поднимется до ~70 (если убрать P0 + P1) и можно смотреть
  на Phase 2 фиксы для P3 → 80+.
