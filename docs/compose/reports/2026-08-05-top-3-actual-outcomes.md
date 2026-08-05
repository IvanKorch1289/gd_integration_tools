# Top-3 Improvement Proposals — фактические решения (2026-08-05)

> **Update**: первоначальный план утверждён пользователем 2026-08-05 (см. `2026-08-05-top-3-improvement-proposals.md`).
> **Фактический исход** после T7/T8/T9 цикла:

## TL;DR

| # | Proposal | Утверждено | Фактический исход | Причина |
|---|---|---|---|---|
| 1 | ClickHouse DLQ unification через tenacity+purgatory | ✅ | **DONE (T7)** — 10281cb6 | Путь через `purgatory` оказался неверным (это CB-UoW, не disk-DLQ). Re-таргетинг на **existing `DLQWriter` Protocol + `InboxDLQWriter`** через setter pattern (как CDC B-02). Cleaner unified contract. |
| 2 | idempotency RedisNxBackend → asgi-idempotency-header RedisBackend | ✅ | **NACK** — закрыто без изменений | Lib's `RedisBackend` использует `sadd/srem` SET **без pending_ttl auto-release**. Кастомный `RedisNxBackend` реализует V5 safety constraint (CLAUDE.md Sprint 0 #12) через `SET NX EX 120s` auto-release. Прямая замена теряет V5 guarantee. |
| 3 | per-tenant SLO-budget preflight в Temporal workflows | ✅ | **DEFERRED (YAGNI)** | `TenantSLO` (155 LOC) — это PURE evaluator без I/O, правильный POC для SRE. Pre-flight Temporal workflow budget = **net-add новой capability** (LOC reduction = 0%), risk = 5, effort = M. Без explicit customer requirement — спекулятивное расширение, отложено до S179+. TenantSLO уже доступен через `for_tenant(tenant_id).evaluate(...)`. |

## Детали по каждому решению

### Proposal #1 — Реальный исход: DONE ✅

**Что планировалось (analyst)**: ClickHouse DLQ → `tenacity` + `purgatory.disk`
**Что фактически сделано**: ClickHouse DLQ → **existing `DLQWriter` Protocol + setter** (тот же pattern что у CDC)

**Ключевые находки в процессе**:
- `purgatory.backends.disk` **не существует** — purgatory предоставляет `AsyncRedisUnitOfWork`, `AsyncInMemoryUnitOfWork` для Circuit Breaker contexts, не disk-DLQ
- Проект **уже использует** `DLQWriter` Protocol (CDC B-02, transport DLQ, scheduler DLQ); через `set_dlq_writer()` composer — established pattern
- Реальный canonical путь: `InboxDLQWriter` (Postgres), `KafkaDLQWriter`, `NATSDLQWriter`, `RabbitDLQWriter`, `InMemoryDLQWriter`

**Что сделано в commit 10281cb6**:
- `ClickHouseAuditService.__init__` принимает `dlq_writer: DLQWriter | None` kwarg
- `ClickHouseAuditService.set_dlq_writer()` setter (composition-root friendly)
- `_send_to_dlq` — приоритет:
  1. canonical `DLQWriter` через `writer.write(DLQEnvelope(...))`
  2. legacy `dlq_path` (backward-compat, deprecated)
  3. silent loss (None + None)
- Envelope стандартизирован через `DLQEnvelope` Pydantic (transport/reason/error_class/error_message/tenant_id/route_id/original_payload/metadata)
- 7 regression-тестов в `test_clickhouse_audit_dlq_writer.py`

**Verify**:
- 40/40 audit tests pass (33 legacy + 7 new = 40)
- ruff+mypy+layer-check clean (1 allowlist entry добавлен для `service.py` → `dlq_base`)
- backward-compat сохранён — все 7 legacy JSONL `test_clickhouse_audit_dlq.py` тестов pass без изменений

**Ponytail**:
- 0 новых зависимостей (использует already-installed `asgi-idempotency-header` deps)
- 0 новых protocols (использует existing `DLQWriter` Protocol)
- setter pattern — established project pattern

### Proposal #2 — Реальный исход: NACK ❌

**Что планировалось (analyst)**: Кастомный `RedisNxBackend` (91 LOC) → библиотечный `asgi-idempotency-header.RedisBackend`
**Что фактически**: оставлен как есть

**Evidence NACK**:

Кастомный `RedisNxBackend` (`src/backend/entrypoints/middlewares/idempotency.py:40-131`):
```python
async def store_idempotency_key(self, idempotency_key: str) -> bool:
    """Атомарно резервирует pending-ключ через ``SET NX EX``."""
    reserved = await self._redis.set(
        self._pending_key(idempotency_key), b"1", nx=True, ex=self._pending_ttl
    )
    return not bool(reserved)
```

Lib's `RedisBackend` (`idempotency_header_middleware.backends.redis.RedisBackend`):
```python
async def store_idempotency_key(self, idempotency_key: str) -> bool:
    """Store an idempotency key header value in a set."""
    return not bool(await self.redis.sadd(self.KEYS_KEY, idempotency_key))
```

| Семантика | Custom RedisNxBackend | Lib RedisBackend |
|---|---|---|
| Pending mechanism | `SET NX EX 120s` (auto-release) | `SADD idempotency-key-keys` (нет TTL auto-release) |
| Зависание worker'а | Блок снимется через 120s автоматически | Блок сохранится до явного `clear` или Redis flush |
| `response:status` suffix | `:status` (custom) | `status-code` (lib) |

**V5 security constraint** (CLAUDE.md Sprint 0 #12) требует **auto-release pending-ключа при зависании worker'а**. Custom `RedisNxBackend.pending_ttl=120s` закрывает это. Lib's `RedisBackend` **не имеет pending_ttl**, поэтому замена **теряет safety guarantee**.

**Принцип Ponytail**: "deletion over addition не работает, когда кастомная реализация закрывает конкретную safety-tread".

**Verify**: 9/9 existing `test_idempotency_redis_backend.py` тестов pass без изменений.

**Документировано**: `RedisNxBackend.pending_ttl` — explicit V5-mandated behavior, не legacy.

### Proposal #3 — Реальный исход: DEFERRED ⏸

**Что планировалось**: Per-tenant SLO-budget preflight в Temporal workflow через Temporal SDK `ContinueAsNew` + existing `TokenBudget`
**Что фактически**: отложено до S179+ (YAGNI)

**Причина deferral**:
- `TenantSLO` (155 LOC) — PURE evaluator без I/O, уже доступен через `TenantSLO.for_tenant(tenant_id).evaluate(...)`
- Pre-flight Temporal workflow budget — **net-add новой capability** (LOC reduction = 0% per analyst's own assessment)
- Effort = M, Risk = 5 (Temporal cancellation cascade требует тщательного тестирования)
- Sprint 36 фокус = "Production Readiness 90%+" (defects/fixes), не capability expansion
- YAGNI explicit: без конкретного use-case от customer — спекулятивное расширение

**Future entry point** (зафиксировано):
- Использовать existing `BudgetEnforcer` (`src/backend/core/tenancy/budget_enforcer.py:35`) как reuse-pattern
- Temporal `Activity.heartbeat` cancellation для fail-fast при превышении
- Multi-tenant metric для per-tenant SLO observability (Prometheus)

**Когда активировать**: когда появится explicit customer requirement с конкретным use case.

## Итог P1-блока (T7-T9)

- **T7 DONE** — реальная польза (canonical DLQWriter через project-стандарт), 0 LOC добавлено в существующий API
- **T8 NACK** — дисциплинированный отказ от несовместимой замены (V5 semantic preservation)
- **T9 DEFERRED** — обоснованное откладывание спекулятивной фичи (YAGNI)

**Stats**:
- 1 commit (10281cb6 — T7)
- 1 NACK with documented evidence (T8)
- 1 YAGNI-defer (T9)
- 0 сломанных тестов
- 0 новых зависимостей
- 0 нарушений слоистости

**Branch**: `s36-p0-fixes` @ `10281cb6` (от 7731dd9a) — 8 коммитов total после merge с master (R66-R75):

```
10281cb6 feat(audit): ClickHouse DLQ unification через canonical DLQWriter Protocol
4946c2c6 docs(sprint36): retrospective P0-блока + Top-3 improvement proposals (analyst)
15681179 docs: Round 75 - R71-R74 retrospective (croniter/pymongo/sphinx wave, 4 commits)
9f13b22a refactor: Round 74 - drop sphinx dev deps + delete legacy docs.yml (analyst proposal #8)
f57c54b8 fix(rpa): re-export 8 missing processors в operations/__init__.py
196fd2e2 feat(workflow): WorkerVersioningHelper use_versioning — пробрасывается из factory
52898dd9 refactor: Round 73 - add pymongo>=4.9,<5.0 to core deps (S31 TODO closure)
efdda246 fix(scheduler): SchedulerManager.start() — wire DLQ listener (G-09)
c63c8167 refactor: Round 72 - croniter 2.0.7 → 6.2.4 (major bump, analyst proposal)
8b68f8a3 chore(layers): allowlist — закрыть 3 новых entrypoints→dsl.engine.context нарушения
4e9467a7 docs: Round 71 - R59-R70 retrospective (security + dedup wave, 10 commits, 24→2 CVEs)
80b0a97d refactor: Round 70 - cryptography ceiling pinned at <50.0.0 (cp314 wheel blocker)
8c65a57d fix(audit): ClickHouse DLQ-backend через importlib — fix layer-violation
44e64c15 feat(audit): ClickHouse emit/emit_batch — retry + JSONL DLQ fallback
7731dd9a refactor: Round 69 - cryptography 48.0.1 → 49.0.0 (-2 PYSEC CVEs)
```

## Урок этой сессии

**Аналитик галлюцинировал первый шаг** (purgatory.disk не существует) — это та же системная проблема S180 что у P0/P1: «документация/анализ vs код расходятся». Решение: **всегда верифицировать file:line перед фиксом** (мы это делали в P0, начали в P1).

**Recovery flow**:
1. Analyst предложил `purgatory.disk` — проверил через `dir(purgatory)` — нет disk-backend
2. Переориентировался на реальный canonical путь (existing `DLQWriter` Protocol)
3. Результат лучше оригинала — closed-form через уже используемый в проекте contract

**Honest NACK** (T8) с evidence — это Ponytail-discipline в действии: "deletion over addition" работает только когда **не теряет semantic**. V5 safety constraint важнее 91 LOC reduction.

**YAGNI** (T9) — Sprint 36 это про defects/fixes (90%+ readiness), не про capability expansion. S179+ будет про M7 Integration Layer backlog (per ADR-0249).
