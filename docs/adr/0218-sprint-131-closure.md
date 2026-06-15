# ADR-0218: Sprint 131 Closure — FB-1 Factory + TD-026 Full Wire-Up + TD-016 + TD-015 Partial (4 commits, score 9.85 → 9.9)

- **Status:** Accepted (Sprint 131 closure, 2026-06-15)
- **Wave:** s131-w5-closure
- **Sprint:** 131
- **Depends:** ADR-0217 (S130 closure), Rule #109/114 (4-state classification), Rule #124 (pre-existing fix)

## Context

Sprint 131 picked up the S130 backlog: FB-1 factory integration (deferred from S130 W3),
TD-026 cont. full wire-up (deferred from S130 W4), TD-016 pre-existing test failure
(`DatabaseBundle` missing `@dataclass`), TD-015 partial (`IDPResult` / `_FieldPattern`
missing `@dataclass`).

Sprint 131 closed **3 backlog items** за 4 code commits + 1 closure:
- **FB-1 factory integration** — `get_object_storage()` теперь возвращает
  `FallbackObjectStorage` wrapper per `resilience.fallbacks.minio` config (W26 chain).
- **TD-026 cont. full wire-up** — `FileStreamGRPCServicer` registered in gRPC server.
  Multi-step: manual `files_pb2.py` regen + multiple inheritance + server.py registration.
  Bonus: исправлены pre-existing broken imports в `invoker_pb2_grpc.py` /
  `orders_pb2_grpc.py` (v1.71+ relative import → absolute).
- **TD-016** — pre-existing test `test_bundle_carries_replica_session_maker` failing
  with `TypeError: DatabaseBundle() takes no arguments`. Root cause: missing
  `@dataclass` decorator. 1-line fix.

## Sprint 131 Final Score (5 waves, 4 code commits + 1 closure)

| Wave | Commit | Scope | Δ | Status |
|---|---|---|---|---|
| W1 | `5151bf12` | FB-1 factory: `get_object_storage()` returns `FallbackObjectStorage(S3, LocalFS)` per config. 2 new tests (wrapper success + init failure). | +128/-9 LOC | ✅ |
| W2 | `75e63b95` | TD-026 full wire-up: `files_pb2.py` + `files_pb2_grpc.py` regen (with absolute import post-process); `FileStreamGRPCServicer(BaseGRPCServicer, FileServiceServicer)`; `server.py` registration; bonus invoker+orders import fix + orders_pb2.py regen (DeleteResponse missing). | +617/-100 LOC, 2 new files | ✅ |
| W3 | `0498f682` | TD-016 fix: add `@dataclass` to `DatabaseBundle`. 1 test closed (`test_bundle_carries_replica_session_maker` now passes). | +2 LOC | ✅ |
| W4 | `72e8bb2b` | TD-015 partial: add `@dataclass` to `IDPResult` + `_FieldPattern` (with `field(init=False)` + `__post_init__` для `regex` alias). +12 tests pass. Remaining 23 failures have different root cause (BaseProcessor `__init__` chain), deferred. | +6/-6 LOC | ✅ |
| W5 | (this ADR) | ADR-0218 + CHANGELOG + INDEX regen | — | ✅ |
| **TOTAL** | **4 commits** | **+91 ahead of origin** | **0 NEW layer violations** | **9.9** |

## W1 — FB-1 factory integration

`get_object_storage()` теперь оборачивает S3 в `FallbackObjectStorage` per
`config_profiles/base.yml::resilience.fallbacks.minio: {chain: ["local_fs"], mode: auto}`
(W26) — runtime try-S3-then-fallback теперь согласован с config. Singleton
(`lru_cache(maxsize=1)`) сохранён — wrapper переиспользуется между вызовами.

При S3 init failure (ImportError на aioboto3 или generic Exception) — bare LocalFS
с warning (pre-existing behaviour сохранён). Bare LocalFS не оборачивается в
wrapper (нет смысла fallback'ить на самого себя).

2 новых test'а:
- `test_get_object_storage_s3_returns_fallback_wrapper` — provider='s3' +
  aioboto3 available → wrapper; primary=S3 mock, secondary=LocalFS,
  chain name contains "s3"; singleton (`lru_cache`) verified.
- `test_get_object_storage_s3_init_failure_returns_bare_local` —
  provider='s3' + S3 init raises RuntimeError → bare LocalFS, NOT wrapper.

Mock pattern: `sys.modules` injection (не `monkeypatch.setattr` на
`storage.s3.S3ObjectStorage`) — `storage.s3` import фейлит без `botocore`
(не установлен в test env), и monkeypatch не может patch'ить unimportable
module.

**Verification**: 7/7 factory tests pass, 55/55 storage tests pass.
Layer linter 0 NEW.

## W2 — TD-026 full wire-up (FileStreamGRPCServicer в gRPC server)

Multi-step (4 sub-tasks):

1. **Manual proto regen**: `uv run python -m grpc_tools.protoc
   -Isrc/backend/entrypoints/grpc/protobuf --python_out=... --grpc_python_out=...
   files.proto` — генерит `files_pb2.py` (3.4K) + `files_pb2_grpc.py` (8.6K)
   c `FileServiceServicer` + `add_FileServiceServicer_to_server`.

2. **Absolute import post-process**: protoc v1.71+ генерит
   `import files_pb2 as files__pb2` (relative), что требует
   `src/backend/entrypoints/grpc/protobuf/` в sys.path. Existing
   `orders_pb2_grpc.py` (v1.70.0 era) использует absolute import — следуем
   тому же стилю для consistency + lazy import-безопасности.
   Patch: `import src.backend.entrypoints.grpc.protobuf.files_pb2 as files__pb2`.

3. **Multiple inheritance**: `class FileStreamGRPCServicer(BaseGRPCServicer, FileServiceServicer)`.
   MRO verified: `['FileStreamGRPCServicer', 'BaseGRPCServicer', 'FileServiceServicer', 'object']`.

4. **Server registration**: `grpc_server/server.py::serve()`:
   ```python
   add_FileServiceServicer_to_server(FileStreamGRPCServicer(), grpc_server)
   ```
   Под `add_OrderServiceServicer_to_server` + `add_InvokerServiceServicer_to_server`.

**Bonus fixes (блокирующие W2 wire-up)**:
- `invoker_pb2_grpc.py` имел ТОТ ЖЕ pre-existing relative import bug —
  regen переписывал на relative, требовался post-process patch. Применён
  same fix pattern с комментарием.
- `orders_pb2.py` имел pre-existing DESCRIPTOR drift — `DeleteResponse`
  message declared in `orders.proto` (текущая версия) but missing в
  закоммиченном generated file. Regen по ТОМУ ЖЕ pattern
  (`-Isrc/backend/entrypoints/grpc/protobuf orders.proto`) обновил файл
  (2.0K → 3.2K) + перегенерил `_pb2_grpc.py` (тот же absolute import fix).
- Cleanup: `rm -rf src/backend/entrypoints/grpc/protobuf/{backend,src}/`
  (untracked dirs от broken earlier regen attempt с full path).

**Verification**: MRO verified, all 3 imports verified, 26/26 gRPC tests pass
(`test_file_stream.py` + `test_grpc_server.py`). Layer linter 0 NEW.

## W3 — TD-016 fix: DatabaseBundle @dataclass

Pre-existing test failure (`TypeError: DatabaseBundle() takes no arguments`):
`DatabaseBundle` class в `infrastructure/database/database/bundle.py` имеет
type annotations (`name: str`, `settings: DatabaseSettings`, ...) и fields
с default values (`replica_engine: AsyncEngine | None = None`), но
НЕ имеет `@dataclass` decorator. `initializer.py:120` вызывает
`DatabaseBundle(name=..., settings=..., async_engine=..., ...)` — kw-only
args, что работает только для dataclass.

**Fix**: добавлен `@dataclass` decorator. Все 8 fields (name, settings,
async_engine, async_session_maker, sync_engine, sync_session_maker,
replica_engine, replica_session_maker) уже в правильном порядке с
default values — dataclass auto-генерирует корректный `__init__`.

**Verification**: `test_bundle_carries_replica_session_maker` PASSES. Net
+1 test в database test suite (75 pass, up from 74). Layer linter 0 NEW.

**Out of scope (Rule #124)**: `test_smart_session_manager_singleton_uses_bundle`
тоже fails с `NameError: name 'DatabaseBundle' is not defined` at
`initializer.py:120` — но это SEPARATE pre-existing bug (initializer.py
missing import of `DatabaseBundle`). Verified via `git stash` — fails
BEFORE и AFTER моего fix. Не блокирует TD-016 closure.

## W4 — TD-015 partial: IDPResult + _FieldPattern @dataclass

Pre-existing test failure pattern (TD-015, 35 tests в
`test_idp_pipeline_processor.py`): `TypeError: object.__init__() takes
exactly one argument`. Identified как 2 of 3 root causes:

1. **`IDPResult`** class — type annotations + `field(default_factory=...)`
   (уже импорт из dataclasses), но НЕ `@dataclass` decorator.
   **Fix**: добавлен `@dataclass`.

2. **`_FieldPattern`** class — type annotations + explicit `__init__`
   метод (был dataclass-like вручную). Test instantiates как
   `_FieldPattern("invoice_number", r"...")` (2 positional args).
   **Fix**: добавлен `@dataclass` + `field(init=False)` для
   `regex` alias + `__post_init__` для auto-set
   `self.regex = self.pattern`.

3. **Unfixed (deferred)**: `IDPPipelineProcessor` class — explicit
   `__init__` (line 96-125) вызывает `super().__init__(name=...)` which
   resolves to `object.__init__` (BaseProcessor НЕ имеет `__init__`
   accepting `name` kwarg). 23 tests still fail. Different root cause,
   needs `BaseProcessor.__init__(self, name: str)` + `IDPPipelineProcessor`
   inheriting properly. Multi-step refactor, deferred S132+.

**Verification**: Net +12 tests pass (35 → 23 failed). `_FieldPattern`
`__post_init__` invariant verified (`fp.regex == fp.pattern`).
`IDPResult(doc_type="invoice", fields={"x": "1"})` works.
Layer linter 0 NEW.

## Tech-debt burn-down

- **FB-1 factory integration**: 🟡 PARTIAL (S130 W3 wrapper, no factory) →
  🟢 **CLOSED (S131 W1)**. `get_object_storage()` returns wrapper per config.
- **TD-026 cont. full wire-up**: 🟡 PARTIAL (S130 W4 codegen path only) →
  🟢 **CLOSED (S131 W2)**. All 3 steps completed: regen + multiple inheritance
  + server registration. 2 bonus pre-existing import fixes.
- **TD-016**: 🔴 OPEN (pre-existing) → 🟢 **CLOSED (S131 W3)**.
  `@dataclass` decorator added to `DatabaseBundle`.
- **TD-015**: 🔴 OPEN (pre-existing, 35 fails) → 🟡 **PARTIAL (S131 W4)**.
  2 of 3 root causes fixed (+12 tests). 1 root cause deferred (BaseProcessor
  __init__ chain, multi-step refactor).

**Net**: 3 fully CLOSED (FB-1 factory, TD-026, TD-016), 1 partial→partial
(TD-015: 35→23 fails). End state: 0 P0/P1 tech debt improvements, 1 P2
continuous docstring ratchet (by design), TD-008 verified closed (S107 W3).

## Sprint 131 final score

**9.85 → 9.9** (estimated, +0.05 for FB-1 factory integration + TD-026 closure).

Score breakdown:
- 0 NEW layer violations (210 legacy baseline maintained)
- 0 NEW P0/P1 tech debt
- 2 features completed (FB-1 factory, TD-026 wire-up)
- 1 trivial fix (TD-016 @dataclass)
- 1 partial fix (TD-015, +12 tests, 23 still deferred)
- 2 bonus pre-existing import fixes (invoker + orders)

## Verification (all waves)

| Aspect | Status |
|---|---|
| FB-1 factory integration | ✅ 7/7 factory tests, 55/55 storage tests |
| TD-026 wire-up | ✅ 26/26 gRPC tests (file_stream + grpc_server) |
| TD-016 (DatabaseBundle) | ✅ `test_bundle_carries_replica_session_maker` passes |
| TD-015 partial (IDPResult + _FieldPattern) | ✅ +12 tests pass (35 → 23 fails) |
| Layer linter | ✅ 0 NEW (baseline 210 legacy) |
| Pre-existing failures (NOT mine, OUT OF SCOPE per Rule #124) | ⚠️ 23 idp tests (BaseProcessor __init__ chain) + 1 db singleton (NameError) + 2 airflow (NameError) + 9 test_retry (test isolation) + 18 test_http (S107-S109 era) + 13 backpressure/rate_limiter |

## Backlog (S132+)

- **TD-015 cont.**: `IDPPipelineProcessor` + `BaseProcessor` `__init__` chain
  refactor (~2h, multi-step)
- **TD-010** (DSL AI exposure: ai_invoke, ai_tool_dispatch — partial, see `dsl/builders/agent_dsl/`)
- **TD-011** (DSL source methods: from_nats, from_mongo, from_grpc_stream — from_nats_js exists, others partial)
- **TD-013** (Streamlit feature-grouping 72 pages, 6+h, dedicated sprint)
- **TD-014** (control_flow.py 416 LOC review, ~1h)
- **TD-027** (S3 fallback deprecation/migration) — merged into FB-1 closure
- **TD-028** (CodecFacade) — pending
- **TD-029** (DB streaming cursor) — pending
- **TD-005** (DSN driver check) — pending
- **Shim removal** (circuit_breaker.py + pybreaker_adapter.py) — V24+ per docstring
- **master_prompt_for_agent.md update** до S131 baseline (optional)

## Commits

```
72e8bb2b fix(s131-w4-td015-partial): add @dataclass to IDPResult + _FieldPattern
0498f682 fix(s131-w3-td016): add @dataclass decorator to DatabaseBundle
75e63b95 feat(s131-w2-td026): FileStreamGRPCServicer wire-up + manual proto regen
5151bf12 feat(s131-w1-fb1-factory): wrap S3 in FallbackObjectStorage per config
```

Pre-S131 HEAD: bc3c4539 (S130 closure, ADR-0217). 91 commits ahead of origin
(NOT pushed — `I'll push` workflow maintained).

## References

- ADR-0217 (S130 closure, 9.8 → 9.85)
- ADR-0187 (S103 closure, audit facade origin)
- `docs/migration/audit-emit-deprecation.md` (Path A/B/C/D guide)
- `tools/check_audit_deprecation.py` (S105 W2 regression guard)
- `tools/check_layers.py` (layer linter)
- `tools/build_adr_index.py` (auto-regen INDEX.md)
- `tools/codegen_proto.py` (gRPC codegen, fixed S130 W4)
- `config_profiles/base.yml` (`resilience.fallbacks.minio` chain config)
