# Infrastructure domain audit — Cycle 2 / Phase 1

- **HEAD:** `ca5bff93` (baseline supplied by cycle-2 instructions)
- **Output:** `docs/audit/swarm-2026-08-06/cycle-2/phase-1/01-infrastructure.md`
- **Audit posture:** bounded, read-only audit. No source/config/lockfile/allowlist/`s3.py` changes were made.

## Scope / не проверено

Проверены исходники `src/backend/infrastructure/**`, доступные unit-тесты `tests/unit/infrastructure/**`, `tools/check_layers.py` и числовая содержательная часть `tools/check_layers_allowlist.txt`; отдельно проверены CDC implementation/guard и история S3. `src/backend/infrastructure/storage/s3.py` был прочитан только для требуемой проверки D-AUDIT-#14 и не изменялся. Запрещённые отчёты, cycle-1 reports/BASELINE, `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md`, lockfiles и иные домены не читались.

Не проверено: полный runtime wiring composition root вне scope, внешние сервисы/Temporal cluster/S3/Qdrant/Kafka, production profile фактического запуска, лицензии и maintenance всех кандидатов библиотек, полный прогон тестов проекта. Из-за отсутствующего в окружении `prometheus_client` targeted pytest collection не завершила тесты CDC/storage (см. Commands run); это не интерпретируется как дефект audited code.

## Verified strengths

1. Layer checker завершился exit 0: **0 new violations**, 175 legacy, 2273 files scanned. Это соответствует cycle-2 baseline, а не заявлению о 180 violations.
2. CDC production default `dlq_required=True`; отсутствующий writer вызывает `RuntimeError` на `_send_to_dlq` (client.py:267–281), то есть misconfiguration не маскируется silent return.
3. CDC callback и action dispatch ошибки превращаются в `DLQEnvelope` с `DLQReason.UNEXPECTED`, stage/subscription/profile/table metadata и передаются через `await self._dlq_writer.write(envelope)` (client.py:210–249, 292–329).
4. `set_dlq_writer()` автоматически вызывает `mark_cdc_dlq_writer_wired()` (client.py:83–97); guard защищён lock и имеет явный `is_wired()` (guard.py:35–82).
5. Webhook ограничивает scheme и private/loopback/link-local IPs до запроса и применяет HMAC SHA-256 при наличии secret provider (webhook.py:46–83, 105–143).
6. S3 multipart fix подтверждён историей: commit `2f620910` (`fix(infra): S3 multipart abort on CancelledError + MemoryError (D-AUDIT-#14, S183 W2 #1)`), а код abort-ит перед повторным выбросом CancelledError/MemoryError (s3.py:337–367).

## Findings table (P0..P4)

| ID | Priority | Path:line | Evidence / impact | Minimal recommendation | Test criterion |
|---|---|---|---|---|---|
| DOMAIN-P0-001 | P0 | `src/backend/infrastructure/clients/external/cdc/client.py:323-334` | Если `DLQWriter.write()` сам падает, код логирует `EVENT WILL BE LOST` и возвращает без retry/secondary durable fallback. Это прямой подтверждённый data-loss path при одновременном отказе обработчика и DLQ. | Добавить bounded retry + durable fallback/операционный fail-stop; не считать log достаточным подтверждением доставки. | Тест writer failure: retry/fallback выполняются, исходное событие не теряется или consumer останавливается с явным alarm.
| DOMAIN-P1-001 | P1 | `src/backend/infrastructure/clients/messaging/event_bus.py:151-169` | Infrastructure импортирует `src.backend.services.schema_registry.registry` напрямую внутри `_validate_event`; это reverse layer boundary, хотя checker сообщает 0 new/175 legacy. | Убрать прямой services import через core protocol/facade/DI adapter; обновить checker после миграции. | Layer test не содержит соответствующего legacy edge; registry validation сохраняет поведение.
| DOMAIN-P1-002 | P1 | `src/backend/infrastructure/cache/rag/semantic.py:55-67` | Infrastructure lazy-imports `src.backend.services.ai.embedding_providers`; при init failure выставляет `False`, затем `_embed()` возвращает пустой vector и cache miss. Это fail-open деградация для cache path и reverse dependency. | Инжектировать embedder через core contract; distinguish unavailable from valid miss and expose health/metric; policy should be explicit. | Unit test asserts unavailable dependency is observable and no false-success cache result is returned.
| DOMAIN-P1-003 | P1 | `src/backend/infrastructure/scheduler/scheduled_tasks.py:55-61` | Infrastructure scheduler imports services AI memory implementation directly (confirmed by grep). Runtime coupling bypasses DI and layer boundary. | Move orchestration contract to core and inject service callable. | Static checker and import test reject infrastructure→services edge.
| DOMAIN-P2-001 | P2 | `src/backend/infrastructure/clients/messaging/memory_broker.py:58-62` | `QueueFull` is handled by `pass` after comment “Drop on full — для dev-сценария это приемлемо.” This is intentional dev-only drop, but dead/low-observability branch if used outside dev. | Keep only behind explicit dev backend guard and increment drop metric/log counter. | Test queue-full increments metric and production configuration rejects memory broker.
| DOMAIN-P2-002 | P2 | `src/backend/infrastructure/repositories/base/base.py:17-70` | Abstract methods contain `raise NotImplementedError`; this is abstract contract scaffolding, not a reachable concrete stub. No finding against production behavior; record for completeness. | No change unless abstract contract is instantiated; retain abstract methods. | Instantiation of abstract class fails; concrete repository tests pass.
| DOMAIN-P3-001 | P3 | `src/backend/infrastructure/clients/external/search_providers.py:327-343` | Optional Tavily/SearXNG registration catches ImportError/AttributeError and `pass`es. Feature absence is intentional optional integration; no library replacement finding established. | Replace silent pass with debug/structured capability status if operators need visibility. | Test optional dependency absent confirms provider omitted and diagnostic status emitted.

**Finding count:** P0=1, P1=3, P2=2, P3=1, P4=0. P2-001/P3-001 are lower-confidence operational cleanup, not security assertions.

## Detailed evidence

### Layer-violation growth: 173 → 180

The requested command was run directly:

```text
$ python tools/check_layers.py --root src
Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)
$ wc -l tools/check_layers_allowlist.txt
180
```

Therefore current checker baseline is **175 legacy / 0 new**, while allowlist file has **180 physical lines**. The numbers are different populations: checker reports legacy violations; `wc -l` includes header/comments plus entries. Direct grep evidence shows entries at `tools/check_layers_allowlist.txt:12-13,18-24,38-39,41-57` including infrastructure edges such as `core → infrastructure`/providers and compatibility exceptions. The supplied cycle-2 baseline says 175 legacy / 0 new and 35 active security IDs; the user’s “173→180” wording is not reproducible as a single metric. No new infrastructure violation was reported. Do not attribute pre-existing working-tree files or cycle-1 Phase-4 changes to this audit.

### CDC B-17 / B-02 conformance

The real code matches the essential B-17 reference formulation: production default is fail-loud, missing writer raises `RuntimeError`, and `set_dlq_writer` marks the guard wired. It also matches the B-02 DLQ pattern for callback/dispatch exceptions: envelope construction and writer handoff are explicit. It does **not** fully satisfy a strict “no-loss DLQ” interpretation because writer failure is caught and logged as `EVENT WILL BE LOST` (client.py:330–334), with no retry/fallback. Thus B-17 is RESOLVED for missing-wiring detection, but residual P0-001 remains for DLQ handoff failure.

### S3 D-AUDIT-#14

`git log --oneline -- src/backend/infrastructure/storage/s3.py` showed:

```text
2f620910 fix(infra): S3 multipart abort on CancelledError + MemoryError (D-AUDIT-#14, S183 W2 #1)
35082522 fix(storage): S3 multipart cancel при CancelledError/MemoryError (B-19, cycle 38, D-AUDIT-#14)
...
```

`git show` confirms commit `2f620910` added a dedicated `except (asyncio.CancelledError, MemoryError)` before the narrow ordinary exception branch and awaits `abort_multipart_upload` before re-raising. Abort-failure handling itself catches only `(OSError, RuntimeError, KeyError)`; a different abort exception would escape and could mask the original exception. This exact edge was not promoted to P0 without a failing test/evidence from the scoped suite; targeted suite collection was blocked by missing `prometheus_client`.

### Custom code / mature library assessment

No safe library replacement finding was asserted. Existing code already declares/uses `faststream`, `httpx`, `qdrant-client`, `temporalio`, `jsonschema`, and `orjson` in `pyproject.toml` (lines 67, 90, 97, 374, and corresponding optional usage). LOC delta, license, and maintenance risk were **не проверено**; no feature-for-feature copying recommendation is warranted. The repository abstract class and adapters are domain-specific seams, so replacing them wholesale would risk DI/layer contracts.

### Organic missing functionality

No P4 feature was raised. The bounded evidence supports hardening existing CDC DLQ durability and layer boundaries, not adding Camel/Airflow/Temporal/LangGraph/DSPy feature copies.

## Cycle-1 residuals (verified или mutated)

The requested cycle-1 identifiers `DOMAIN-P0-001..007`, `P1..P5`, and `P3-001` are not present in scoped source/tests/git history queried by literal grep. The cycle-1 reports were explicitly forbidden, so their original descriptions cannot be reconstructed safely. Status: **не проверено / не может быть сопоставлено по ID**; no claim of closure or mutation is made. The scoped current evidence does independently establish the findings listed above. B-17 and D-AUDIT-#14 were verified by current code/history, not by reading forbidden reports.

## Contradictions/overlaps to flag

- “173→180 layer violations” conflicts with reproducible current checker output **175 legacy / 0 new** and `wc -l` **180**. These must not be combined into one baseline.
- `tools/check_layers_allowlist.txt` is explicitly forbidden to modify; its physical line count cannot be treated as active violation count.
- CDC docstring says missing writer fallback is log-only at lines 216–218, but current `_send_to_dlq` is fail-loud when `dlq_required=True`; implementation is authoritative and the docstring is stale/contradictory.
- The CDC fail-loud guard prevents miswiring but does not guarantee delivery when the writer itself fails; DOMAIN-P0-001 is distinct from B-17.

## Readiness score 0–100

**Score: 45/100.** Formula: `100 - 35*P0 - 7*P1 - 3*P2 - 1*P3 = 100 - 35 - 21 - 6 - 1 = 37`, then +8 bounded-evidence credit for checker exit 0, S3 abort fix, and CDC missing-wiring guard = **45**. Score is below 80 as required because P0/P1 findings exist. The score is domain-bounded, not a release approval.

## Recommended next tasks

1. **P0 / DOMAIN-P0-001:** make CDC DLQ handoff durable: bounded retry, secondary durable store or explicit fail-stop/backpressure; add tests for writer failure and cancellation.
2. **P1 / DOMAIN-P1-001..003:** introduce core protocols/facades and DI wiring for schema registry, embeddings, and LangMem scheduler callback; remove direct infrastructure→services imports.
3. Add a test environment dependency check/fixture for `prometheus_client` so scoped CDC tests can collect and run.
4. Correct stale CDC `_dispatch_change` documentation to describe B-17 default and dev-only exception.
5. Keep layer metrics separate: publish checker legacy/new counts and allowlist active-entry count, not raw `wc -l`.

## Commands run

- `python tools/check_layers.py --root src` → exit 0; 0 new; 175 legacy; 2273 files.
- `wc -l tools/check_layers_allowlist.txt` → 180.
- `grep -nE 'infrastructure|storage|source|service|entrypoint|allow' tools/check_layers_allowlist.txt | head -80` → direct allowlist evidence.
- `git log --oneline -- src/backend/infrastructure/storage/s3.py | head -20` → `2f620910`, `35082522`, etc.
- `git show --stat --oneline 2f620910`; `git show ... 2f620910 -- .../s3.py` → fix details.
- `grep` scoped reverse-import search → confirmed event_bus.py:153, semantic.py:59, scheduled_tasks.py:57, presidio_sanitizer.py:32/45.
- `grep` scoped TODO/FIXME/NotImplemented/pass search → evidence listed above.
- `pytest -q tests/unit/infrastructure/clients/external/cdc tests/unit/infrastructure/storage --disable-warnings --maxfail=1` → collection failed before tests: `ModuleNotFoundError: prometheus_client`.
- Literal scoped search for requested cycle-1 IDs → no matches; original cycle-1 reports were not read by instruction.

## Final status

Bounded infrastructure audit complete. Source/config/allowlist/lockfile/S3 were not modified; only this report was created.
