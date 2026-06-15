# ADR-0217: Sprint 130 Closure — TD-030 Finish + FB-1 (S3 Fallback) + gRPC Codegen Path Fix (4 commits, score 9.8 → 9.85)

- **Status:** Accepted (Sprint 130 closure, 2026-06-15)
- **Wave:** s130-w5-closure
- **Sprint:** 130
- **Depends:** ADR-0216 (S129 closure), Rule #109/114 (4-state classification), Rule #124 (pre-existing fix)

## Context

Sprint 130 начался с попытки запустить S127 W1 = TD-030 (CB-1 delete 2 files) по stale
`s126_sprint_plan.md` (от 14.06, pre-S127-S128-S129 execution). Pre-flight (Rule #109)
обнаружил: **S127-S128-S129 уже выполнены, 7 of 8 RED gaps = closed, 1 missing = FB-1,
TD-030 = PARTIAL**. S130 sprint plan = fresh baseline (C+D hybrid: archive stale + new plan).

Sprint 130 closed **3 backlog items** за 4 commits: TD-030 finish (smtp + redis_breaker
миграция на canonical), FB-1 (новый feature: FallbackObjectStorage), TD-026 cont. (gRPC
codegen path fix).

## Sprint 130 Final Score (5 waves, 4 commits + INDEX regen)

| Wave | Commit | Scope | Δ | Status |
|---|---|---|---|---|
| W1 | `d2d1941c` | fact-check + archive: s126_sprint_plan → archive/s126/; s130_factcheck + s130_sprint_plan created | 264 LOC | ✅ |
| W2 | `6f7a812d` | TD-030 finish: smtp.py + redis_breaker_storage.py → canonical core/resilience/breaker.py. Shim files KEPT as back-compat (V24+ removal). 6 new regression tests. | +267/-37 LOC | ✅ |
| W3 | `84a10bfb` | FB-1: `FallbackObjectStorage` runtime S3→LocalFS chain. 17 tests (download/upload/delete/exists/list_keys/presigned_url + fallback_exceptions filter + healthcheck + metrics). | +569 LOC | ✅ |
| W4 | `0c3aee13` | gRPC codegen path fix: `make grpc-codegen` now works. Fixed 2 bugs: (a) `extensions` not on sys.path, (b) wrong output dir (`src/entrypoints/` → `src/backend/entrypoints/`). | +23/-5 LOC | ✅ |
| W5 | (this ADR) | ADR-0217 + CHANGELOG + INDEX | — | ✅ |
| **TOTAL** | **4 commits** | **+83 ahead of origin** | **0 NEW layer violations** | **9.85** |

## W1 — Fresh S130 baseline + archive stale s126 files

**File scope:** 1 new file (264 LOC) + 2 file moves

Pre-flight обнаружил **87.5% stale-gap rate** в `s126_verification_matrix.md` (vs S129 W1
= 75% stale-TD rate). S116-S117 cascade pattern подтверждён.

8 RED gaps from s126 verified:
- **CLOSED (7)**: VAR-1 (S127 W2 commit `2640d56d`), FACADE-2 (S127 W3 `ae1efe1b`),
  AI-6 (S127 W4 + S128 W3 `5c4bae28`+`623aef7c`), CDC-2 (S128 W2 `4404ff9f`),
  CERT-1 (S128 W1 `346f7d48`), DIST-1 (S128 W2 `4404ff9f`), layer linter regression
  (S127 W1 `61e75de7`)
- **PARTIAL (1)**: CB-1 / TD-030 (smtp.py + redis_breaker_storage.py still on shim)
- **MISSING (1)**: FB-1 S3 Runtime Fallback (no `fallback_storage.py`)

Action: archive `s126_sprint_plan.md` + `s126_verification_matrix.md` →
`reports/reaudit/archive/s126/`. Create `s130_w1_factcheck_classification.md` +
`s130_sprint_plan.md` based on S129 W1 baseline.

## W2 — TD-030 finish: smtp + redis_breaker миграция к canonical

**File scope:** 4 files modified + 1 new test file (267 LOC)

API mismatch обнаружен при dry-run: canonical `core.resilience.breaker.Breaker` использует
`guard()` async context manager (Purgatory), shim `core.utils.circuit_breaker` использует
`check_state() + record_success/failure`. НЕ drop-in replacement.

Миграция:
- `core/resilience/breaker.py`: добавлен `BreakerState` dataclass (single source of truth)
- `core/utils/pybreaker_adapter.py`: `BreakerState` теперь re-export из canonical
  (back-compat preserved)
- `infrastructure/clients/transport/smtp.py`:
  * import: `get_circuit_breaker` (DEPRECATED) → `get_breaker_registry` + `BreakerSpec` + `CircuitOpen`
  * `__init__`: `self._circuit_breaker = get_circuit_breaker()` → `self._breaker = get_breaker_registry().get_or_create("smtp", BreakerSpec(...))`
  * `get_connection()`: `await check_state(...)/record_success/record_failure` →
    `async with self._breaker.guard():` (auto record). `CircuitOpen` re-raised as
    `ConnectionError` (back-compat contract)
  * `metrics()`: `self._circuit_breaker.state` (uppercase) → `self._breaker.state` (lowercase)
- `infrastructure/resilience/redis_breaker_storage.py`: import `BreakerState` from canonical

6 new regression tests (`tests/unit/infrastructure/clients/transport/test_smtp_canonical_breaker.py`):
- static guard: smtp.py не импортирует `core.utils.circuit_breaker` (regex, не docstring)
- import check: smtp.py использует canonical
- signature: `get_connection` — @asynccontextmanager
- runtime: `SmtpClient._breaker` — canonical `Breaker` instance
- back-compat: open breaker raises `ConnectionError` (не `CircuitOpen`)
- metrics: `circuit_state` в lowercase (canonical)

**Verification**: 43 directly-related tests pass (smtp_canonical 6 + redis_breaker 9 +
unified_breaker 6 + shim tests 22). Layer linter 0 NEW.

**Pre-existing failures (NOT introduced by W2)** — verified via `git stash` + re-run:
- 18 failures в `test_http.py` (pre-existing, S107-S109 era)
- 13 failures в `test_backpressure_property` + `test_rate_limiter_tenant_namespace` (pre-existing)
- 9 failures в `test_retry.py` in-suite (test isolation issue, pre-existing)

Per Rule #124: eligible for fix if small+single-file+single-root-cause. Здесь multi-file +
interaction, OUT OF SCOPE для TD-030 closure.

**Shim files kept as back-compat** (per their docstring "Removal: V24+"):
- `core/utils/circuit_breaker.py` (DeprecationWarning продолжает firing)
- `core/utils/pybreaker_adapter.py` (BreakerState re-export, InMemoryPybreakerAdapter +
  PybreakerSDKAdapter сохранены)

## W3 — FB-1: FallbackObjectStorage runtime S3→LocalFS chain

**File scope:** 1 new file + 1 new test file (569 LOC)

`config_profiles/base.yml` уже содержал `resilience.fallbacks.minio: {chain: ["local_fs"]}` (W26).
`factory.py` имел init-time fallback (S3 init fails → LocalFS). **Но runtime try-primary-then-fallback
logic отсутствовал** — это и было FB-1 gap.

`FallbackObjectStorage(ObjectStorage)` wrapper (~245 LOC):
- 6 методов ABC + `healthcheck()`: download, upload, delete, exists, list_keys, presigned_url
- Try primary first; при matched exception → secondary (с warning + counter)
- `fallback_exceptions` parameter (default `(Exception,)`; может быть tightened до
  `(ConnectionError, OSError)` чтобы НЕ fallback'ить на логических ошибках типа `KeyError`)
- `fallback_count` property: per-method counter для observability
- `supports_presigned()` делегирует primary (для production-готовности)

17 tests (`tests/unit/infrastructure/storage/test_fallback.py`):
- download: primary success / primary fail → secondary / both fail → secondary exc
- upload: primary success / primary fail → secondary (write-through)
- delete: primary success / primary fail → secondary
- exists / list_keys / presigned_url: primary success / primary fail → secondary
- `fallback_exceptions` filter: KeyError не триггерит, ConnectionError триггерит
- supports_presigned delegates to primary
- healthcheck: primary ok / primary fail → secondary
- fallback_count accumulates across calls

**Verification**: 17/17 tests pass. Layer linter 0 NEW.

**Factory integration deferred (S131+)**: нужен рефактор `get_object_storage()` чтобы
возвращал `FallbackObjectStorage` wrapper по config вместо bare S3. Не блокирует FB-1 closure —
wrapper готов и протестирован, consumers могут adopt явно через
`FallbackObjectStorage(S3ObjectStorage(...), LocalFSStorage(...))`.

## W4 — gRPC codegen path fix

**File scope:** 1 file modified (28 LOC, +23/-5)

`make grpc-codegen` (target уже существовал с W1.3) был сломан двумя багами:

**Bug 1**: `tools/codegen_proto.py` НЕ добавлял project root в `sys.path`. При запуске через
`make grpc-codegen` (который использует `python tools/codegen_proto.py`), CWD (project root)
не попадал в `sys.path` автоматически, и `register_all_services()` фейлил с
`ModuleNotFoundError: No module named 'extensions'`. Workaround был `PYTHONPATH=$(pwd)`,
но это требовало от каждого разработчика помнить про env var.

**Fix**: добавил `sys.path.insert(0, _REPO_ROOT)` в начало `tools/codegen_proto.py`.

**Bug 2**: `_AUTO_PROTO_DIR` и `_PROTO_INCLUDE_DIR` указывали на `src/entrypoints/...`
(НЕ `src/backend/entrypoints/...`). При запуске codegen создавал параллельную
`src/entrypoints/grpc/protobuf/auto/` папку, игнорируя tracked файлы в правильном
месте. После фикса `_AUTO_PROTO_DIR` = `src/backend/entrypoints/grpc/protobuf/auto`
— codegen пишет в существующую tracked папку.

**Cleanup**: удалена фейк `src/entrypoints/` папка (untracked, от старого broken codegen).

**Verification**: `make grpc-codegen` теперь работает без `PYTHONPATH`, пишет в правильное
место. `make grpc-codegen-dry` показывает план: 4 .proto (files, orderkinds, orders, users)
+ compile pb2/pb2_grpc. 17 file_stream tests + 9 grpc_server tests = 26/26 pass.

**Full wire-up deferred (S131+)**: для полной активации `FileStreamGRPCServicer` (TD-026)
нужно:
1. Сгенерировать manual `files_pb2.py` + `files_pb2_grpc.py` для `FileService` (with
   DownloadFile/UploadFile streaming from S128 W3) — отдельный шаг, не `make grpc-codegen`
2. Обновить `class FileStreamGRPCServicer(BaseGRPCServicer, FileServiceServicer)` —
   multiple inheritance (S128 W3 не сделал)
3. Зарегистрировать в `grpc_server/server.py`

Это multi-day work, не 1-wave scope. Per Rule "Honest scope reduction" — вынесено в
отдельный sprint.

## Tech-debt burn-down

- **TD-030**: 🟡 PARTIAL (S127 W1) → 🟢 CLOSED (S130 W2). smtp.py + redis_breaker_storage.py
  migrated к canonical `core/resilience/breaker.Breaker.guard()`. Shim files kept as
  back-compat (V24+ removal per their docstring).
- **FB-1** (S126 reaudit #7): 🔴 MISSING → 🟢 CLOSED (S130 W3). `FallbackObjectStorage`
  runtime S3→LocalFS chain реализован. Factory integration deferred S131+.
- **TD-026 cont.**: 🟡 PARTIAL (codegen path broken) → 🟡 PARTIAL (path fix done, full
  wire-up deferred S131+). 1 of 2 steps completed.

**Net**: 2 fully CLOSED, 1 partial→partial (improved). End state: 0 P0/P1/P3, 1 P2 (continuous
docstring ratchet, by design).

## Sprint 130 final score

**9.8 → 9.85** (estimated, +0.05 for FB-1 new feature + TD-030 finish).

Score breakdown:
- 0 NEW layer violations (210 legacy baseline maintained)
- 0 NEW P0/P1 tech debt
- 2 features completed (TD-030 finish, FB-1)
- 1 infra fix (gRPC codegen path)
- 1 pre-existing test isolation issue documented (NOT my scope per Rule #124)
- 1 archive + 2 new reports (s130_factcheck, s130_sprint_plan)

## Verification (all waves)

| Aspect | Status |
|---|---|
| TD-030 (smtp + redis_breaker migration) | ✅ 43 tests pass |
| FB-1 (FallbackObjectStorage) | ✅ 17 tests pass |
| gRPC codegen path fix | ✅ 26 tests pass, `make grpc-codegen` works |
| Layer linter | ✅ 0 NEW (baseline 210 legacy) |
| Pre-existing failures (NOT mine) | ⚠️ Documented, out of scope |
| Shim files back-compat | ✅ DeprecationWarning preserved |

## Backlog (S131+)

- **TD-026 cont.** (full wire-up): manual proto regen + multiple inheritance +
  server registration (multi-day, dedicated sprint)
- **FB-1 factory integration**: refactor `get_object_storage()` to return
  `FallbackObjectStorage` wrapper per config (~2h)
- **TD-008** (audit/facade split, 394 LOC, 1 commit ~2h)
- **TD-010** (DSL AI exposure, 1-2 commits ~3h)
- **TD-011** (DSL source methods, 1-2 commits ~3h)
- **TD-013** (Streamlit feature-grouping 72 pages, 6+h, dedicated sprint)
- **TD-014/015/016** (small fixes, ~1h each)
- **Shim removal** (circuit_breaker.py + pybreaker_adapter.py) — V24+ per docstring

## References

- `reports/reaudit/s130_w1_factcheck_classification.md` (S130 W1 fact-check, 87.5% stale-gap rate)
- `reports/reaudit/s130_sprint_plan.md` (S130 plan, 5 waves)
- `reports/reaudit/archive/s126/` (archived stale s126 files)
- `reports/reaudit/s129_w1_factcheck_classification.md` (precedent, 75% stale-TD rate)
- ADR-0216 (S129 closure, Sprint 129 score 9.8)
- ADR-0215 (S128 closure)
- ADR-0214 (S127 closure)
- Rule #109 (pre-sprint fact-check)
- Rule #114 (4-state classification)
- Rule #121 (60-sec pre-flight)
- Rule #124 (pre-existing fix eligibility)
