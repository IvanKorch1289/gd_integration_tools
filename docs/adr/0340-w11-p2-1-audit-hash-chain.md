# ADR-0340 — Audit log integrity (hash chain ledger)

## Статус

**Accepted** (2026-09-23). Закрывает architectural gap "Audit log integrity"
из стратегического анализа 2026-09-22.

## Контекст

Стратегический анализ (timestamp 1790089356160) выявил gap:

> «Обычный audit log может быть изменён вместе с основной БД. Для
> критических действий нужны:
>   - Hash chaining.
>   - External immutable sink.
>   - Sequence-gap detection.
>   - Signed checkpoints.
>   - Separation of duties.
>   - Retention lock.
>   - Проверка восстановления цепочки после backup/restore.
> …
> Это особенно важно для plugin installation, route changes,
> impersonation, secret rotation, feature flags и DLQ replay.»

В репо уже есть:
- ``src/backend/infrastructure/audit/event_log.py`` — ClickHouse через
  AsyncBatcher (централизованный event log).
- ``src/backend/services/audit/clickhouse_audit_service/`` — query layer.
- ``src/backend/infrastructure/audit/jsonl_audit.py`` — JSONL fallback.
- ``src/backend/infrastructure/observability/audit_verify_lifecycle.py`` —
  lifecycle verification (отдельная concern).

Не хватает: **cryptographic hash chain** — append-only ledger где
каждая запись криптографически связана с предыдущей через SHA-256.

## Решение

Создать ``src/backend/infrastructure/audit/hash_chain.py`` —
``HashChainLedger`` класс с append-only API и verification.

### Components

| Класс/функция | Назначение |
|---|---|
| ``HashChainEntry`` | frozen dataclass с index/timestamp/payload/prev_hash/current_hash. |
| ``HashChainLedger.append(payload)`` | Добавляет entry, возвращает frozen объект. |
| ``HashChainLedger.from_entries(entries)`` | Reconstruct ledger из existing entries (для restore). |
| ``HashChainLedger.verify()`` | Проверяет hash chain integrity (SHA-256 пересчёт). |
| ``HashChainLedger.verify_with_gaps()`` | verify() + detection of missing indexes. |
| ``HashChainLedger.signed_checkpoint()`` | Snapshot для external signing (placeholder). |
| ``ChainVerificationResult`` | Dataclass с status/is_valid/tampered_index/gap_at. |
| ``IntegrityStatus`` | Enum: VALID/TAMPERED/GAP_DETECTED/INVALID_GENESIS. |
| ``_canonical_json(payload)`` | Детерминистичная JSON сериализация (sort_keys=True). |
| ``_compute_hash(...)`` | SHA-256 hex digest от canonical representation. |

### Hash computation

```
current_hash = SHA-256(
    f"{index}|{timestamp}|{canonical_json(payload)}|{prev_hash}"
)
```

Каноническая JSON сериализация использует ``sort_keys=True`` и
``separators=(",", ":")`` для детерминизма — порядок ключей не влияет на hash.

### Append-only invariant

- ``HashChainEntry`` frozen — после создания immutable.
- ``prev_hash`` каждой новой записи = ``current_hash`` предыдущей.
- ``index`` = ``len(self._entries)`` для append().
- Genesis hash = "0" * 64 (64 zeros).

### Verification semantics

**``verify()`` — обнаружение tamper**:
1. Проверяет ``prev_hash`` linkage каждой entry.
2. Пересчитывает ``current_hash`` (SHA-256) и сравнивает с stored.
3. Первая failure → ``TAMPERED`` status + ``first_tampered_index``.

**``verify_with_gaps()`` — extended verify**:
1. Сначала ``verify()`` — если failed, возвращает tamper result.
2. Если chain intact, проверяет contiguous indexes (0, 1, 2, 3, ...).
3. Пропущенный index → ``GAP_DETECTED`` status + ``first_gap_at``.

### Realistic scenarios (per tests)

| Scenario | verify() | verify_with_gaps() |
|---|---|---|
| Normal append chain | VALID | VALID |
| Modified payload (tamper) | TAMPERED @ index | TAMPERED @ index |
| Backup/restore с lost entry | TAMPERED @ next-after-gap | TAMPERED @ next-after-gap |
| Manual reconstruction с valid hashes + non-contiguous indexes | VALID | GAP_DETECTED @ first-missing |
| Modified genesis prev_hash | INVALID_GENESIS @ 0 | INVALID_GENESIS @ 0 |

**Important**: backup/restore с потерянным entry приводит к TAMPERED,
потому что prev_hash следующей entry указывает на хеш отсутствующей
(цепь разорвана). Это корректно: backup/restore с потерей данных — это
data integrity issue, который должен быть обнаружен.

### Public API surface

```python
# Append new entry.
entry = ledger.append({"event": "login", "user": "alice"})

# Verify integrity.
result = ledger.verify()
if not result.is_valid:
    if result.status == IntegrityStatus.TAMPERED:
        # Audit failure — security incident.
        alert_security_team(result)
    elif result.status == IntegrityStatus.GAP_DETECTED:
        # Backup/restore с потерей — replay from checkpoint.
        replay_from_checkpoint(last_signed_checkpoint)

# Restore from backup.
restored = HashChainLedger.from_entries(recovered_entries)
result = restored.verify_with_gaps()

# Create checkpoint for external signing (production: Vault Transit).
checkpoint = ledger.signed_checkpoint()
```

## Альтернативы (отклонённые)

- **Использовать существующий ``event_log.py`` как append-only** —
  отклонено: ClickHouse может быть изменён (admin), нет hash chain по
  умолчанию. Hash chain — это *cryptographic* invariant, требует
  отдельной структуры.
- **Использовать blockchain / DLT** — отклонено: overhead, latency,
  operational complexity неоправданы для internal audit log.
- **Merkle tree (binary hash tree)** — отклонено: linear chain проще
  для текущего use case (sequential events), Merkle tree оптимален
  для parallel verification (out of scope).
- **Signed log entries (Ed25519 per entry)** — отклонено: требует
  key management per entry (Vault/KMS), overhead высокий. Hash chain
  sufficient для tamper detection, signing добавляется на checkpoint
  уровне (через ``signed_checkpoint()`` placeholder).

## Последствия

### Плюсы

- **Cryptographic tamper detection** — любая модификация entry
  (включая payload, timestamp, prev_hash) → TAMPERED detected.
- **Restore verification** — backup/restore integrity check через
  ``verify_with_gaps()``.
- **Deterministic hash** — canonical JSON + SHA-256 → reproducible
  hashes для cross-system verification.
- **Immutable entries** — frozen dataclass, append-only ledger.
- **Production-ready integration path** — ``signed_checkpoint()``
  hook для external signing (Vault Transit, AWS KMS).

### Ограничения

- **In-memory storage** — default implementation для тестов. Production
  требует persistent storage (ClickHouse table + on-disk WAL).
- **Single-process assumption** — не thread-safe. Multi-writer нужен
  external coordination (asyncio.Lock или DB row lock).
- **No external immutable sink** — placeholder в ``signed_checkpoint()``.
  Production deployment требует Kafka append-only topic или S3 Object
  Lock для checkpoint snapshots.
- **No separation of duties** — single operator can append. Production
  требует dual-control (security_team + audit_team) для critical
  operations.

### Backward compat

- Не трогает существующий ``event_log.py`` (централизованный
  ClickHouse log остаётся canonical для query/analytics).
- Не заменяет ``audit_verify_lifecycle.py`` (другая concern — lifecycle
  verification, не cryptographic integrity).
- Standalone модуль — DI не требуется.

### Production deployment path

1. Persistent storage: ClickHouse table + on-disk WAL (для crash recovery).
2. External signing: ``signed_checkpoint()`` → Vault Transit → Kafka
   append-only topic.
3. Retention lock: 7 лет (GDPR / financial regulation).
4. Dual control: critical operations (plugin install, route change,
   DLQ replay per W11 P1-2) требуют двух operator approvals.
5. Monitoring: alert на TAMPERED / GAP_DETECTED status → PagerDuty.

### Cross-cutting integration

- **W11 P1-2 (DLQ replay governance)** — каждое replay должно писать
  audit entry через ``HashChainLedger.append()``.
- **W11 P1-1 (outbox crash matrix)** — critical operations (poison
  message handling) → hash chain audit trail.
- **V15 R-V15-1 (plugin contract)** — plugin install → hash chain entry.
- **V15 security constraints** — secret rotation, route change,
  feature flag toggle → hash chain entry.

## Verification

| Gate | Команда | Результат |
|---|---|---|
| compileall | `python -m compileall -q src/ extensions/ scripts/ tools/ tests/ testkit/` | EXIT 0 |
| check_python3_syntax | `python tools/checks/check_python3_syntax.py --root .` | EXIT 0 |
| ruff | `python -m ruff check src/backend/infrastructure/audit/hash_chain.py tests/...` | All checks passed |
| pytest (W11 P2-1) | `python -m pytest tests/unit/infrastructure/audit/test_w11_p2_1_audit_hash_chain.py` | 33/33 passed |
| pytest (full W11) | 6 test files | 247/247 passed |

### Test coverage (33 tests в 8 test classes)

- **TestAppend** (6): genesis hash, prev_hash linkage, contiguous indexes, frozen entry, custom timestamp/metadata.
- **TestCanonicalJson** (4): key order doesn't affect hash, nested dict, unicode, non-serializable raises.
- **TestVerify** (7): empty valid, single valid, multiple valid, payload tamper, prev_hash tamper, timestamp tamper, invalid genesis.
- **TestVerifyWithGaps** (5): contiguous valid, backup/restore → TAMPERED, multiple gaps → TAMPERED, manual reconstruction → GAP_DETECTED, restore scenario → TAMPERED.
- **TestReadOnlyAccess** (4): len, getitem, iter, get_entries returns copy.
- **TestSignedCheckpoint** (2): empty checkpoint, non-empty checkpoint.
- **TestEndToEndScenarios** (4): plugin install, route change, DLQ replay, secret rotation.
- **TestPerformance** (1): 1000 entries verify.

## Файлы

- `src/backend/infrastructure/audit/hash_chain.py` — новый модуль (~420 LOC)
- `tests/unit/infrastructure/audit/test_w11_p2_1_audit_hash_chain.py` — 33 tests (~490 LOC)
- `docs/adr/INDEX.md` — обновлён (132 → 133 ADRs)

## Ссылки

- ADR-0339 — DLQ replay governance (integration)
- ADR-0338 — outbox crash matrix (integration)
- ADR-0337 — DomainProblem (canonical error contract)
- Strategic analysis 2026-09-22: audit log integrity gap
- `src/backend/infrastructure/audit/event_log.py` — существующий ClickHouse log
- `src/backend/infrastructure/observability/audit_verify_lifecycle.py` — lifecycle verification
- PROGRESS_LEDGER: `docs/roadmap/PROGRESS_LEDGER.md`
