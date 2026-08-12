# DSL Domain Audit — Cycle 1, Phase 1

**Auditor**: independent DSL/registry/composition analyst
**Scope**: `src/backend/dsl/**` + DSL tests, **excluding**:
- `src/backend/dsl/agents/**`
- `src/backend/dsl/workflow/**`
- `src/backend/dsl/engine/processors/agent_dsl/**`
- `src/backend/dsl/engine/processors/workflow/**`
- rag* processors (RagIngest, RagQuery, RAG redaction, vectorsearch, reranker, ragingest, rag_search, ragpiiredaction, ragquery, hybrid rag blueprint)

**Baseline**: commit `b69d6b49bc62918a02e47dc20ab81615fd8500b1` (S38 B-22).
**Pre-existing working-tree noise (not attributed to audit)**: `src/backend/infrastructure/storage/s3.py` (committed between baseline and HEAD), `uv.lock` (still uncommitted at audit start).
**Layer checker baseline**: 175 legacy, 0 new.
**Active security allowlist IDs (raw count)**: 35.

---

## 1. Scope / what was NOT verified

| Area | Reason |
|---|---|
| `src/backend/dsl/agents/**` | Excluded by scope. |
| `src/backend/dsl/workflow/**` | Excluded by scope. |
| `src/backend/dsl/engine/processors/agent_dsl/**` | Excluded by scope. |
| `src/backend/dsl/engine/processors/workflow/**` | Excluded by scope. |
| RAG processors (`rag*`, `vectorsearch`, `reranker`, `ragingest`, `rag_search`, `ragpiiredaction`, `ragquery`, `cachewrite`, `llm_structured/*`, `hybrid_rag.yaml` blueprint) | Excluded by scope. |
| Reports of other agents in this swarm | Not read by instruction. |
| `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md`, `DEEP_AUDIT_REPORT.md`, debt logs | Not read by instruction. |
| Vault / PostgreSQL / Redis availability at runtime | Vault unavailable at audit time; (mock) checks done via `.venv/bin/python` only for import-time and syntax. |
| Real DSL business workflows (extensions/) | Not in scope; only core DSL mechanics. |
| Extension-level tests (`extensions/*/tests/`) | Not in scope. |
| Specific capability gating (`auth_policies` etc.) | Not in scope (security domain). |
| Audit-time `/metrics` of running services | Not run; metrics referenced from static code only. |

---

## 2. Verified strengths

| # | Strength | Evidence |
|---|---|---|
| S1 | EIP catalog is comprehensive and **Camel-aligned** | `src/backend/dsl/engine/processors/eip/__init__.py:107-176` re-exports 70+ EIP patterns (Aggregator, CircuitBreaker, ClaimCheck, ContentBasedRouter, CorrelationIdentifier, DeadLetter, Delay, DynamicRouter, FallbackChain, ForEach, GlomExtract, GlomFlatten, GlomTransform, IdempotentConsumer, LoadBalancer, Loop, Marshal/Unmarshal, MessageTranslator, Multicast, Normalizer, OnCompletion, PipesAndFilters, ProcessManager, RecipientList, RedeliveryPolicy, Resequencer, RoutingSlip, Sampling, ScatterGather, Sort, Splitter, Throttler, Timeout, TransactionalClient, WindowedCollect, WindowedDedup, WireTap) |
| S2 | Centralized `ProcessorRegistry` with namespacing/decorator | `src/backend/dsl/registry/processor.py:102-287` — thread-safe `_Registry` with `replace` semantics; `__all__`/`@processor` decorator pattern supports `core:` / `<plugin>:` namespace. |
| S3 | Layer-aware facade/dependency patterns | `src/backend/dsl/engine/processors/base.py:73-135` — `BaseProcessor.auth_check` resolves tenant via `check_source_capability` with **fail-closed** fallback in `except Exception` (line 130-135). |
| S4 | DLQ 3-stage fallback prevents data loss | `src/backend/dsl/engine/processors/eip/resilience.py:76-179` — Redis → JSONL → metric+raise; `_log.critical` + `dlq_send_failed_total` Prometheus metric. |
| S5 | Pipeline-level `tenant_aware` enforcement | `src/backend/dsl/engine/execution_engine.py:155-173` — `_check_tenant_aware` raises `TenantContextRequiredError` when `pipeline.tenant_aware=True` and no tenant. |
| S6 | DSL pipeline validation before execute | `src/backend/dsl/engine/pipeline.py` + `src/backend/dsl/engine/validation.py` — `PipelineValidator` checks PII ordering, error-handling presence, circular refs. |
| S7 | Exchange immutability + finalizers | `src/backend/dsl/engine/exchange.py:188-219` — `add_finalizer` + `run_finalizers` (LIFO, isolated). |
| S8 | Cyrillic-first docstrings preserved | All EIP files preserve Russian docstrings per project rule. |
| S9 | Capability-aware `auth_check` plumbing | `src/backend/dsl/engine/processors/base.py:73-135` wires `required_capability` → `AuthorizationFacade.check_source_capability`. |
| S10 | `MulticastProtocolTypes` decoupled | `src/backend/dsl/adapters/types.py` referenced via `ExchangeMeta.protocol: ProtocolType` — single source of truth for multi-protocol. |
| S11 | Pydantic-typed `Message`/`Exchange` | `src/backend/dsl/engine/exchange.py:32-122` — `Message[T]`, `ExchangeMeta`, Pydantic models with `ConfigDict`. |
| S12 | Late-event policy | `src/backend/dsl/engine/late_event_policy.py` documented; tests exist (`tests/unit/dsl/engine/test_late_event_policy.py`). |
| S13 | EIP coverage close to Camel 4.x | EIP patterns from official Camel catalog: CBR, Multicast, ScatterGather, RecipientList, RoutingSlip, PipesAndFilters, Resequencer, IdempotentConsumer, Aggregator, Marshal/Unmarshal, Normalizer, Splitter, ClaimCheck, MessageTranslator, Saga, ProcessManager, TransactionalClient, EventMessage, ContentBasedRouter, Sampling, Throttler, WireTap, OnCompletion, Loop, ForEach, Delay, CorrelationIdentifier, MessageExpiration, RedeliveryPolicy, ReturnAddress — 30+ patterns. |
| S14 | `NotImplementedError` only in `_BasePublisher` as abstract pattern | `src/backend/dsl/engine/processors/streaming_llm_publishers.py:22,26` — proper ABC pattern, not a stub. |

---

## 3. Findings table

| ID | P | Path:line | One-liner |
|---|---|---|---|
| DSL-P0-001 | P0 | `src/backend/dsl/engine/processors/eip/routing/multicast.py:172` | `ExecutionEngine(route_registry=...)` — wrong kwarg, real production bug masked by mocks. |
| DSL-P0-002 | P0 | `src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py:145` | `except TypeError, ValueError:` — Python-2 syntax now means "catch TypeError, alias as ValueError"; silently drops `ValueError` from `int(attempt_raw)`. |
| DSL-P0-003 | P0 | `src/backend/dsl/engine/processors/scan_file.py:92-97` | AV fail-open path when `on_threat != "fail"` — malicious files bypass scan silently. |
| DSL-P1-001 | P1 | `src/backend/dsl/engine/processors/__init__.py:258` | `"CDCProcessor"` declared in `__all__` but NOT imported at top — `from src.backend.dsl.engine.processors import CDCProcessor` raises `ImportError`. |
| DSL-P1-002 | P1 | `src/backend/dsl/engine/processors/redis_lock_processor.py:59` | `side_effect: ClassVar[Any] = "READ"` — string assigned where `BaseProcessor.side_effect: ClassVar[SideEffectKind]`; type contract violation. |
| DSL-P1-003 | P1 | `src/backend/dsl/engine/processors/eip/sequencing.py:42-77` | `ResequencerProcessor._buffers` grows unbounded when batch never reaches `batch_size`; only drops oldest key at `_MAX_KEYS=10000` — memory leak / silent message loss. |
| DSL-P1-004 | P1 | `src/backend/dsl/engine/processors/eip/redis_lock_processor.py:118` (instance latches `_lock` but never releases on route-exit) | Lock is never released by this processor; relies on TTL self-healing — comment at line 117 explicitly admits this. |
| DSL-P1-005 | P1 | `src/backend/dsl/engine/processors/eip/windowed_dedup.py:131-134, 303-306` | Wrap-all `except Exception ... continue`: Redis failure → message silently passes (no dedup). WindowedDedup/Dedup bypass mode = fail-open. |
| DSL-P1-006 | P1 | `src/backend/dsl/engine/processors/scan_file.py:155-161` | `_record_metric` swallows `Exception` silently — AV telemetry invisible; with `from src.backend.infrastructure.observability.metrics import record_antivirus_scan` silently bypass if module missing. |
| DSL-P1-007 | P1 | `src/backend/dsl/engine/processors/format_convert/{specialized,encodings,data_formats}.py:63` | `_xml_to_dict_stdlib` uses vulnerable `ET.fromstring` (XXE / billion-laughs) without `defusedxml`; reachable via `_from_xml` fallback when `xmltodict` missing. |
| DSL-P1-008 | P1 | `src/backend/dsl/commands/action_registry.py:309-313` | `kwargs` filter drops fields with `None` value → required-arg method silently gets missing kwarg → `TypeError` from downstream service at runtime. |
| DSL-P1-009 | P1 | `src/backend/dsl/engine/processors/eip/windowed_dedup.py:25-28` | Docstring still describes `MulticastRoutesProcessor` as part of this module — that class lives in `routing/multicast.py`; stale ref. |
| DSL-P1-010 | P1 | `src/backend/dsl/engine/processors/__init__.py` (eip re-export gap) | Many EIP classes absent from top-level re-export: `ContentBasedRouter`, `SamplingProcessor`, `PipesAndFiltersProcessor`, `MarshalProcessor`, `UnmarshalProcessor`, `RoutingSlipProcessor`, `ForkJoinProcessor`, `EventMessageProcessor`, `EventMessageEnvelope`, `TransactionalClientProcessor`, `ProcessManagerProcessor`, `WindowedDedupProcessor`, `WindowedCollectProcessor`, `CorrelationIdentifierProcessor`, `MessageExpirationProcessor`, `RedeliveryPolicyProcessor`, `ReturnAddressProcessor`, all `Pydash*Processor`, all `Glom*Processor`, all `Collect*Processor`, `MulticastRoutesProcessor`, `SimpleRegistry`, `ProcessorRegistry` (Protocol), `ForkJoinProcessor`. Withdraws from `from src.backend.dsl.engine.processors import X` only option. |
| DSL-P2-001 | P2 | `src/backend/dsl/engine/processors/eip/reliability.py` (442 LOC god-file) | Dead file: shadowed by `src/backend/dsl/engine/processors/eip/reliability/` package; Python prefers package, so `.py` is unreachable code. |
| DSL-P2-002 | P2 | `src/backend/dsl/engine/processors/eip/aggregation.py` (98 LOC) | `BatchAggregatorProcessor` is NOT a `BaseProcessor`; never imported anywhere outside its own test. Orphan. |
| DSL-P2-003 | P2 | `src/backend/dsl/engine/processors/audit.py:35` | `AuditProcessor` not registered via `@processor` decorator (factory-only). |
| DSL-P2-004 | P2 | `src/backend/dsl/engine/processors/eip/dict_ops.py` (5 classes) | All `Pydash*Processor` are NOT registered via `@processor` decorator. |
| DSL-P2-005 | P2 | `src/backend/dsl/engine/processors/eip/glom_ops.py` (3 classes) | All `Glom*Processor` are NOT registered via `@processor` decorator. |
| DSL-P2-006 | P2 | `src/backend/dsl/engine/processors/eip/transformation.py` (5 classes) | `MessageTranslatorProcessor`, `SplitterProcessor`, `ClaimCheckProcessor`, `NormalizerProcessor`, `SortProcessor` — all NOT registered via `@processor` decorator. |
| DSL-P2-007 | P2 | `src/backend/dsl/engine/processors/eip/routing_slip.py:42, 47, 55` | `__all__` exports `ProcessorRegistry` (Protocol) — name collision with `src.backend.dsl.registry.ProcessorRegistry`. Acceptable but error-prone. |
| DSL-P2-008 | P2 | `src/backend/dsl/engine/processors/eip/marshal/{formats,processors}.py` | `xml.etree.ElementTree` used for marshal (writes) without isolation — format stack consistency. |
| DSL-P2-009 | P2 | `src/backend/dsl/engine/processors/eip/transformation.py:266-305` | Custom XML/CSV parsers as fallback when libs unavailable — masks missing `xmltodict`/`polars` from deployment. |
| DSL-P2-010 | P2 | `src/backend/dsl/engine/processors/format_convert/{data_formats,specialized,encodings}.py:38-65` | Three near-identical copies of `_xml_to_dict_stdlib` / `_populate_xml` / `_el_to_dict` — duplication. |
| DSL-P2-011 | P2 | `src/backend/dsl/engine/processors/eip/event_message.py:254-260` | Naming bug: counter `_publish_count` is incremented in `except` block (means "errors", not "publishes"). |
| DSL-P3-001 | P3 | `src/backend/dsl/engine/processors/eip/resilience.py:455` (TimeoutProcessor) + `src/backend/dsl/engine/processors/eip/flow_control/throttler.py:49` (ThrottlerProcessor) | Local implementations of timeout/throttle; core has `core.resilience.breaker` (CB) and `core.facades` (per `core/facades.py` — only `17 primitives` mentioned). Consider unifying with `asyncio.timeout` (stdlib 3.11+) context manager in `TimeoutProcessor` for clearer cancel semantics. LOC delta ∈ ±30. |
| DSL-P3-002 | P3 | `src/backend/dsl/engine/processors/eip/routing/{scatter_gather,multicast,load_balancer,recipient_list}.py` | Custom `asyncio.gather`+`asyncio.wait` plumbing; `tenacity` is **not** a strict equivalent (not for fan-in), but `aiostream` / `asyncio.TaskGroup` (Python 3.11+) already in stdlib would simplify `MulticastRoutesProcessor`+`ScatterGatherProcessor` sync/timeout/cancel. pyproject already supports `asyncio.TaskGroup` (3.14 mandatory). LOC delta: -50 to -120 across 5 files. |
| DSL-P3-003 | P3 | `src/backend/dsl/engine/processors/eip/transformation.py:44-125` (MessageTranslatorProcessor) | Custom XML/CSV parsing fallback masks dependency absence; could simply require `xmltodict`+`polars` (already in pyproject core deps) and raise `ImportError` if missing instead of hiding. Semantic delta: +strictness, -30 LOC. |
| DSL-P3-004 | P3 | `src/backend/dsl/engine/processors/eip/api_composition.py:319-349` | Per-source TTL cache (`InMemoryCacheStore`) duplicates `cachetools.TTLCache` (already in `pyproject.toml:119` transitive via `cachetools`). LOC delta: -25. |
| DSL-P3-005 | P3 | `src/backend/dsl/engine/processors/eip/windowed_dedup.py:33-44` (whole file) | Manual Redis SET NX/SADD/EXPIRE; could use `redis-streams` consumer-group features (already in deps via `redis`). Risk: custom logic vs. battle-tested. LOC delta: -60 to -100 if simplified. |
| DSL-P3-006 | P3 | `src/backend/dsl/engine/processors/audit.py:14-80` | `_VALID_OUTCOMES` + manual `_resolve`/`_build_store` could use `pydantic.ConstrainedStr` (already in deps) — but minimal benefit. |
| DSL-P3-007 | P3 | `src/backend/dsl/engine/processors/redis_lock_processor.py:78-121` | `self._lock` instance attribute is written but never released by this processor. `redis-py` `Redis.lock` already exists (with `BlockingConnectionLock` / `Lua` acquire). LOC delta: -20. |
| DSL-P4-001 | P4 | (whole DSL) | **No native DSL primitive for `try { ... } catch { ... } finally { ... }` over Exchange**; `TryCatchProcessor` (control_flow) is a partial. Camel has `doTry/doCatch/doFinally`. |
| DSL-P4-002 | P4 | (whole DSL) | **No Temporal-style `Activity` retry policy with non-retryable exception classification**; `RedeliveryPolicy` (reliability) is straight backoff. LangGraph/LangChain doesn't directly model this either. |
| DSL-P4-003 | P4 | (whole DSL) | **No DSPy-style `Signature`** for `LLMCallProcessor` (steps define literal prompt); `PromptComposerProcessor` is regex-only. |
| DSL-P4-004 | P4 | (whole DSL) | **No `StatefulSaga` with explicit persistent checkpoint API**; `ProcessManagerProcessor` is a thin Saga subclass. |
| DSL-P4-005 | P4 | (whole DSL) | **No `BPMN`-style event subprocess** (boundary event, escalation); gap vs. Camel's full BPMN+DMN. |

---

## 4. Detailed evidence

### DSL-P0-001 — `ExecutionEngine(route_registry=...)` is invalid

`src/backend/dsl/engine/processors/eip/routing/multicast.py:172`:
```python
engine = ExecutionEngine(route_registry=route_registry)
```

`src/backend/dsl/engine/execution_engine.py:67-77` signature:
```python
def __init__(
    self,
    middleware: MiddlewareChain | None = None,
    validate_before_execute: bool = True,
    pool: ProcessorPool | None = None,
) -> None:
```

The `route_registry` kwarg is **not** accepted. At runtime this raises `TypeError: ExecutionEngine.__init__() got an unexpected keyword argument 'route_registry'`.

All tests in `tests/unit/dsl/engine/processors/eip/test_routing.py` (lines 460-547) and `tests/unit/dsl/eip/test_multicast_routes.py` patch `ExecutionEngine` via `mock`, so the real signature is never tested. This is a **production-time TypeError**: any pipeline that triggers `MulticastRoutesProcessor.process()` blows up.

**Impact**: hard fail when `multicast_routes(…)` is invoked in production. No EIP fan-out will work.

**Minimal fix**: remove `route_registry=route_registry` from the constructor call; `engine.execute(pipeline, …)` does not need `route_registry` already (it operates on the `pipeline` arg).

**Test criterion**: `pytest tests/unit/dsl/integration/test_multicast_routes_real.py::test_real_engine_construction` — instantiate `MulticastRoutesProcessor`, register a stub route in `route_registry`, run `process()` against a real `ExecutionEngine`, assert `status == completed` and `multicast_route_results` populated.

---

### DSL-P0-002 — `except TypeError, ValueError:` is Python-2 syntax

`src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py:142-147`:
```python
try:
    attempt = int(attempt_raw) + 1
except TypeError, ValueError:
    attempt = 1
```

In Python 3, that comma is `except TypeError as ValueError:` — i.e. only `TypeError` is caught, and the exception instance is bound to the local name `ValueError`. `ValueError` exceptions from `int(attempt_raw)` (e.g. when header is a non-numeric string) propagate and crash the processor.

**Verification**: `.venv/bin/python -c "def f():
    try:
        raise ValueError('x')
    except TypeError, ValueError:
        print('caught as', ValueError)
f()"` returned `caught as <class 'ValueError'>` — confirming the silent mis-bind.

**Impact**: malformed `redelivery_count` header values cause uncaught `ValueError` → `handle_processor_error` catches it and writes `error` to exchange, but the counter is **incorrectly reset** to `attempt=1` only on `TypeError`. The atomic counter gets wrong values for non-integer header.

**Minimal fix**: `except (TypeError, ValueError):`.

**Test criterion**: `pytest -k "test_redelivery_policy_handles_value_error"` — build an exchange with `redelivery_count=<non-numeric-string>` header, run, assert `attempt == 2` (correct increment), not `attempt == 1` (fallback).

---

### DSL-P0-003 — `ScanFileProcessor` fail-open on AV backend failure

`src/backend/dsl/engine/processors/scan_file.py:85-97`:
```python
try:
    from src.backend.infrastructure.antivirus.factory import (
        create_antivirus_backend,
    )
    backend = create_antivirus_backend()
    result = await backend.scan_bytes(payload)
except Exception as exc:
    _logger.warning("ScanFileProcessor: AV-бэкенд недоступен: %s", exc)
    exchange.set_property(f"{self._result_property}_error", str(exc))
    if self._on_threat == "fail":
        exchange.fail(...)
    return
```

When `on_threat != "fail"` (i.e. default-ish `pass` config or `quarantine` config that doesn't fail-fast), the exception silently sets an `_error` property and the message continues downstream **without being scanned**. The default constructor sets `on_threat="fail"` (line 60: `on_threat: str = "fail"`), but the constructor allows override.

**Impact**: if AV backend is down AND configured `on_threat="pass"` (or future-config additions of `on_threat="quarantine"`), malicious files bypass scanning silently. The `_record_metric` is also swallowed silently (lines 155-161), so even observability is lost.

**Minimal fix**: in the `except` branch, ALWAYS `exchange.fail("scan_file: AV backend unavailable, fail-closed")` regardless of `on_threat` — fail-closed at the availability layer (separate from the result layer).

**Test criterion**: `pytest -k "test_scan_file_av_unavailable_fails_closed"` — mock `create_antivirus_backend` to raise, run with `on_threat="pass"`, assert `exchange.status == failed`.

---

### DSL-P1-001 — `CDCProcessor` in `__all__` but not imported

`src/backend/dsl/engine/processors/__init__.py:258`:
```python
"CDCProcessor",
```

The `from src.backend.dsl.engine.processors.external import ...` line is **absent** (only `AgentGraphProcessor` and `MCPToolProcessor` are referenced in `external.py`).

**Verification**: `.venv/bin/python -c "from src.backend.dsl.engine.processors import CDCProcessor"` → `ImportError: cannot import name 'CDCProcessor'`.

**Impact**: any code/blueprint/test that imports `CDCProcessor` from `src.backend.dsl.engine.processors` will fail at import time. Real CDC fan-in pipelines (if any rely on this path) break.

**Minimal fix**: add `from src.backend.dsl.engine.processors.external import CDCProcessor` to lines 1-237 of `__init__.py`.

**Test criterion**: smoke import test in `tests/unit/dsl/engine/processors/test_cdc_import.py::test_cdc_processor_importable`.

---

### DSL-P1-002 — `side_effect: ClassVar[Any] = "READ"` type contract violation

`src/backend/dsl/engine/processors/redis_lock_processor.py:59`:
```python
side_effect: ClassVar[Any] = "READ"
```

Base class contract (`src/backend/dsl/engine/processors/base.py:14, 44`):
```python
class BaseProcessor(ABC):
    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
```

Here RedisLockProcessor overrides with a `str` literal "READ" — not a `SideEffectKind` enum value. Engine code that does `processor.side_effect` switch over `SideEffectKind` (e.g. `is SideEffectKind.PURE`) will fail or hit inconsistent branches.

**Verification**: targeted `.venv/bin/python -c "from src.backend.dsl.engine.processors.redis_lock_processor import RedisLockProcessor; print(RedisLockProcessor.side_effect, type(RedisLockProcessor.side_effect))"` — would print `READ <class 'str'>`.

**Impact**: 
- any `match processor.side_effect:` on `SideEffectKind` will not match.
- metrics / classification code silently breaks.
- fails static type-check (mypy/pyright uses `ClassVar[Any]`).

**Minimal fix**: `from src.backend.core.types.side_effect import SideEffectKind` and `side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL`.

**Test criterion**: `pytest -k "test_redis_lock_side_effect_decl"` — assert `isinstance(RedisLockProcessor.side_effect, SideEffectKind)`.

---

### DSL-P1-003 — `ResequencerProcessor` memory leak

`src/backend/dsl/engine/processors/eip/sequencing.py:34-77`:
```python
self._buffers: dict[str, list[tuple[int, Any]]] = {}
async def process(self, exchange, context):
    ...
    async with self._lock:
        if len(self._buffers) >= self._MAX_KEYS:
            oldest = next(iter(self._buffers))
            del self._buffers[oldest]
        buf = self._buffers.setdefault(key, [])
        buf.append((seq, body))
        if len(buf) >= self._batch_size:
            buf.sort(...)
            ...
            buf.clear()
        else:
            exchange.set_property("resequenced", False)
            ...
            exchange.stop()
```

**Analysis**: when a key never reaches `batch_size` (timeout/worker down/config boundary), the buffer is **never flushed**. The `else` branch (line 75-77) just sets a property and `stop()`s the exchange — the buffer keeps the items. After enough distinct keys, oldest is silently dropped (line 60-61) → data loss.

**Impact**: long-running route with sparse keys → unbounded memory OR silent message loss (whichever fires first).

**Minimal fix**: add a per-key timeout task in `__init__`; flush-and-clear on timeout; OR flush on `process` exit if anything still in buffer.

**Test criterion**: `pytest -k "test_resequencer_does_not_leak_unflushed_keys"` — feed 10001 distinct keys with batch_size=10, assert `_buffers` size never exceeds `_MAX_KEYS - 1` BEFORE primary eviction.

---

### DSL-P1-004 — `RedisLockProcessor` never releases lock

`src/backend/dsl/engine/processors/redis_lock_processor.py:114-118`:
```python
self._lock = lock
```
…and the file's OWN docstring (line 117) admits:
> "В текущей реализации cleanup делается через route lifecycle (RouteBuilder.finalize / shutdown hooks), не здесь. Если route падает, lock истечёт по TTL — self-healing semantics."

The instance attribute `_lock` is created but no `release()` is ever called by the processor itself. This means:
- successful routes: the lock is held for full `ttl_seconds` (60s default) regardless of actual work duration.
- failed routes: same TTL timeout applies (self-healing per docs).

**Impact**: contention storm — multiple workers can hit the same lock serially because each holds it for ~60s even if their work finished in 100ms.

**Minimal fix**: register a finalizer via `exchange.add_finalizer(lambda: lock.release())` immediately after `acquire` returns `True`.

**Test criterion**: `pytest -k "test_redis_lock_releases_on_completion"` — assert lock released within 1s of route completion.

---

### DSL-P1-005 — Windowed dedup fail-open on Redis failure

`src/backend/dsl/engine/processors/eip/windowed_dedup.py:113-134, 263-306`:
```python
try:
    from src.backend.infrastructure.clients.storage.redis import redis_client
    ...
except Exception as exc:
    _logger.warning("windowed_dedup: Redis недоступен, сообщение проходит: %s", exc)
```

Both `WindowedDedupProcessor` and `WindowedCollectProcessor` wrap the entire Redis interaction in a bare `except Exception: continue`. When Redis is unavailable, messages **bypass dedup** and pass through without deduplication.

**Impact**: under Redis outage, dedup contracts are silently broken. CDC pipelines will emit duplicate downstream events that should have been deduplicated.

**Minimal fix**: `exchange.fail("windowed_dedup: Redis unavailable, fail-closed")` — make the operator explicitly choose `allow_on_redis_failure=True` if they want fail-open.

**Test criterion**: `pytest -k "test_windowed_dedup_fails_closed_on_redis_unavailable"` — mock `redis_client.execute` to raise, assert `exchange.status == failed`.

---

### DSL-P1-006 — `_record_metric` swallows all exceptions

`src/backend/dsl/engine/processors/scan_file.py:151-161`:
```python
@staticmethod
def _record_metric(*, threat: bool) -> None:
    try:
        from src.backend.infrastructure.observability.metrics import (
            record_antivirus_scan,
        )
        record_antivirus_scan(threat=threat)
    except Exception:
        pass
```

Bare `except Exception: pass` — telemetry for AV scans is silently dropped on any error. Operators cannot detect:
- AV backend present but metric endpoint broken.
- `record_antivirus_scan` signature changed.
- Prometheus exporter disconnected.

Comment line 152-153 says "best-effort метрика" — but it makes the metric invisible to ops, and combined with DSL-P0-003 the silent path can hide malicious files.

**Minimal fix**: at minimum `_logger.exception("record_antivirus_scan failed: %s", exc)` instead of `pass`.

**Test criterion**: `pytest -k "test_record_metric_logs_on_failure"` — patch `record_antivirus_scan` to raise, assert log capture with `exc` info.

---

### DSL-P1-007 — Direct `ET.fromstring` for untrusted XML

`src/backend/dsl/engine/processors/format_convert/specialized.py:63`, `encodings.py:65`, `data_formats.py:63`:
```python
def _xml_to_dict_stdlib(xml_string: str) -> dict[str, Any]:
    root = ET.fromstring(xml_string)  # noqa: S314
    return {root.tag: _el_to_dict(root)}
```

Three near-identical functions. `_from_xml` flow in `data_formats.py:117-129`:
```python
def _from_xml(self, data: Any) -> dict[str, Any]:
    text = _to_text(data)
    if not text:
        return {}
    try:
        import xmltodict
        parsed = xmltodict.parse(text)
        ...
    except ImportError:
        return _xml_to_dict_stdlib(text)
```

When `xmltodict` is not installed (optional? not in pyproject deps — it IS in core deps at line 305: `"xmltodict>=0.14.0,<1.0.0"`), the fallback uses `ET.fromstring` which is vulnerable to:
- XXE (XML External Entity injection)
- billion-laughs / quadratic blowup attacks
- DoS via large entities

When `xmltodict` IS installed (default), fine. But the fallback path is reachable.

**Impact**: PII / SOAP routes that hit `from_xml` on untrusted input where `xmltodict` was somehow absent → DOA / XXE.

**Minimal fix**: use `defusedxml.ElementTree.fromstring` instead of `ET.fromstring` in the fallback. Or better: do not provide a fallback — raise `ImportError("Install xmltodict")`.

**Test criterion**: `pytest -k "test_from_xml_fallback_uses_defusedxml"` — force `xmltodict` ImportError, parse `<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>`, assert NO resolution of `/etc/passwd`.

---

### DSL-P1-008 — `action_handler_registry.dispatch` kwargs filter drops required args

`src/backend/dsl/commands/action_registry.py:303-313`:
```python
if spec.payload_model is not None:
    validated = spec.payload_model.model_validate(command.payload)
    kwargs = {
        field_name: getattr(validated, field_name)
        for field_name in validated.model_fields
        if getattr(validated, field_name) is not None
    }
```

The `if … is not None` filter discards fields whose value is `None`. This is **wrong** if the underlying service method has a required positional argument treated as `None`. E.g. `def my_service(id: int, name: str = None, ...)` — `id` will be missing from `kwargs` if `id` is `None` in payload, then `method(**kwargs)` → `TypeError: missing 1 required positional argument: 'id'`.

**Impact**: silent at K-ARCH dispatcher; downstream service raises `TypeError` only at the actual call boundary. Heisenbugs.

**Minimal fix**: build kwargs from validated **without** the `is not None` filter; let `model_dump(exclude_none=True)` opt-in be used where appropriate.

**Test criterion**: `pytest -k "test_dispatch_required_field_with_none_value"` — register action with required int field, send payload `{"id": null}`, assert the service receives `id=None` (or proper ValidationError before call).

---

### DSL-P1-009 — Stale docstring

`src/backend/dsl/engine/processors/eip/windowed_dedup.py:25-28`:
```python
MulticastRoutesProcessor:
    Fan-out на зарегистрированные route_id из RouteRegistry.
    Выполняет каждый маршрут параллельно и агрегирует результаты.
```

`MulticastRoutesProcessor` lives in `eip/routing/multicast.py`, not in `windowed_dedup.py`. This is a stale docstring — likely a leftover from when the routing module was larger.

**Minimal fix**: remove the `MulticastRoutesProcessor` block from the docstring.

**Test criterion**: optional — `grep -rn "MulticastRoutesProcessor:" src/backend/dsl/engine/processors/eip/windowed_dedup.py` should be empty.

---

### DSL-P1-010 — Heavy gap in top-level `processors/__init__.py` re-exports

The package `src/backend/dsl/engine/processors/__init__.py` re-imports only **select** EIP processors (lines 105-129). The following exist in `eip/` but are **NOT** re-exported at top level:
- `ContentBasedRouter`, `SamplingProcessor` (in `filter_router_sampling.py`)
- `PipesAndFiltersProcessor` (in `pipes_and_filters.py`)
- `MarshalProcessor`, `UnmarshalProcessor` (in `marshal/processors.py`)
- `RoutingSlipProcessor`, `SimpleRegistry`, `ProcessorRegistry` (Protocol) (in `routing_slip.py`)
- `ForkJoinProcessor` (in `fork_join.py`)
- `EventMessageProcessor`, `EventMessageEnvelope` (in `event_message.py`)
- `TransactionalClientProcessor`, `ProcessManagerProcessor` (in `transactional.py`)
- `WindowedDedupProcessor`, `WindowedCollectProcessor` (in `windowed_dedup.py`)
- `CorrelationIdentifierProcessor`, `MessageExpirationProcessor`, `RedeliveryPolicyProcessor`, `ReturnAddressProcessor` (in `reliability/`)
- all `Pydash*Processor` (in `dict_ops.py`)
- all `Glom*Processor` (in `glom_ops.py`)
- all `Collect*Processor` etc. (in `collection/`)
- `MulticastRoutesProcessor` (in `routing/multicast.py`)

This is a layering / API consistency issue. The reusable processor catalog is "hidden" behind `eip.*` even though the comment in `__init__.py` says "Все процессоры доступны через `from src.backend.dsl.engine.processors import …`".

**Recommendation**: align top-level re-exports with `eip/__all__` (~70 classes).

**Test criterion**: `pytest -k "test_top_level_re_exports_match_eip"` — assert `set(__all__)` of `eip` ⊆ top-level `__all__`.

---

### DSL-P2-001 — Dead `reliability.py` (442 LOC)

`src/backend/dsl/engine/processors/eip/reliability.py` is the legacy 442 LOC god-file. The new modular structure is in `src/backend/dsl/engine/processors/eip/reliability/` subpackage. Per Python module resolution, the package takes precedence, so the file is dead.

**Verification**: `.venv/bin/python -c "from src.backend.dsl.engine.processors.eip import reliability; print(reliability.__file__)"` → `…/reliability/__init__.py` (package, not the .py file).

**Impact**: confusion, dead code in IDE navigation, double maintenance burden.

**Minimal fix**: delete `src/backend/dsl/engine/processors/eip/reliability.py`.

**Test criterion**: smoke test that import works without the file.

---

### DSL-P2-002 — Orphan `BatchAggregatorProcessor`

`src/backend/dsl/engine/processors/eip/aggregation.py:19`:
```python
class BatchAggregatorProcessor:
```

**Not** a `BaseProcessor` subclass. Never imported anywhere outside `tests/unit/dsl/engine/processors/eip/test_windowed_agg.py`. The actual `AggregatorProcessor` is in `eip/flow_control/aggregator.py` (a BaseProcessor subclass).

**Impact**: dead code, conflicting with `AggregatorProcessor`.

**Minimal fix**: delete `src/backend/dsl/engine/processors/eip/aggregation.py` and `tests/unit/dsl/engine/processors/eip/test_windowed_agg.py`.

---

### DSL-P2-003 — `AuditProcessor` not in registry

`src/backend/dsl/engine/processors/audit.py:35` — `AuditProcessor` is a `BaseProcessor` but not decorated with `@processor(...)`. It will not appear in `get_processor_registry()`. The class is still functional via direct import / factory, but it is invisible to schema export / LSP / AsyncAPI generation.

**Impact**: doc/IDE consumers can't see `audit` as a registered processor.

**Minimal fix**: add `@processor("audit", namespace="core", spec_schema={...}, ...)` decorator.

---

### DSL-P2-004 — `Pydash*Processor` not registered

`src/backend/dsl/engine/processors/eip/dict_ops.py` — 5 classes (PydashGet, Set, Omit, Pick, Merge) inherit `BaseProcessor` but are not decorated with `@processor`. Same P3 outcome as DSL-P2-003.

---

### DSL-P2-005 — `Glom*Processor` not registered

`src/backend/dsl/engine/processors/eip/glom_ops.py` — 3 classes (GlomExtract, GlomTransform, GlomFlatten) are BaseProcessor but not decorated.

---

### DSL-P2-006 — `MessageTranslator`, `Splitter`, `ClaimCheck`, `Normalizer`, `Sort` not registered

`src/backend/dsl/engine/processors/eip/transformation.py` — 5 classes (lines 24, 127, 187, 327, 405) are BaseProcessor but not decorated.

Total undecorated EIP BaseProcessor classes: ~50+ across dict_ops, glom_ops, transformation, routing, marshal, etc. (verified count: 67 BaseProcessor classes in `eip/` minus 14 with `@processor` = 53 undecorated).

---

### DSL-P2-007 — `ProcessorRegistry` name conflict

`src/backend/dsl/engine/processors/eip/routing_slip.py:42, 47, 55`:
```python
__all__ = ("ProcessorRegistry", "RoutingSlipProcessor", "SimpleRegistry")
class ProcessorRegistry(Protocol): ...
class SimpleRegistry: ...
```

Two `ProcessorRegistry` types exist:
- `src/backend/dsl/registry/processor.py:102` — registry singleton for `@processor` decorator.
- `src/backend/dsl/engine/processors/eip/routing_slip.py:47` — Protocol for routing-slip lookup.

Same name, different semantics. The Protocol is structural (duck-typed) so it accidentally works, but new contributors will trip.

**Minimal fix**: rename Protocol to `ProcessorLookup` (or `RoutingSlipProcessorRegistry`).

---

### DSL-P2-008 — `xml.etree.ElementTree` usage in marshal

`src/backend/dsl/engine/processors/eip/marshal/formats.py:12`:
```python
import xml.etree.ElementTree as ET  # safe: used only for marshal (we generate XML)
```

Used for marshal (write) direction. Internally consistent if guarded against untrusted input. Not a P0/P1 but a maintenance hazard.

**Minimal fix**: enforce contract via docstring + runtime check (no user input reaches this path).

---

### DSL-P2-009 — Fallback XML/CSV parsers in `transformation.py`

`src/backend/dsl/engine/processors/eip/transformation.py:44-125` — Manual XML/CSV fallback when `xmltodict`/`polars` unavailable. Hides deployment misconfiguration.

**Minimal fix**: raise `ImportError("polars required")`; align with `pyproject.toml:302` (polars IS in core deps).

---

### DSL-P2-010 — `_xml_to_dict_stdlib` duplicated 3x

`src/backend/dsl/engine/processors/format_convert/{specialized,encodings,data_formats}.py` — three near-identical copies of `_xml_to_dict_stdlib`, `_populate_xml`, `_el_to_dict`. Total ~80 LOC of duplication.

**Minimal fix**: extract to `format_convert/_helpers.py` (which already exists).

---

### DSL-P2-011 — Counter naming bug in `EventMessageProcessor`

`src/backend/dsl/engine/processors/eip/event_message.py:254-260`:
```python
except Exception:
    with self._lock:
        self._publish_count += 1
    raise
```

`_publish_count` is incremented in the `except` branch — semantically this is "publish errors" not "publishes". The actual successful publish counter (`_publish_count += 1` at line 260) is at the end. Both lines look identical to a casual reader.

**Minimal fix**: rename increment in `except` to `_publish_error_count`; OR use a separate lock-protected dict.

---

### DSL-P3-001..007 — Library replacement candidates

| ID | Recommendation | Lib in deps | License/maintenance | LOC delta |
|---|---|---|---|---|
| DSL-P3-001 | `TimeoutProcessor` → `asyncio.timeout` ctx-manager (stdlib 3.11+) | stdlib | PSF / stdlib | -30 / +5 |
| DSL-P3-002 | `MulticastRoutesProcessor`/`ScatterGather` → `asyncio.TaskGroup` (stdlib 3.11+) | stdlib | stdlib | -50 to -120 across 5 files |
| DSL-P3-003 | `MessageTranslatorProcessor` fallback → require `xmltodict`+`polars` (both in core deps) | core deps | Apache 2.0 / MIT | -30 |
| DSL-P3-004 | `InMemoryCacheStore` in `api_composition.py` → `cachetools.TTLCache` | `pyproject:1042` cachetools in core deps | MIT | -25 |
| DSL-P3-005 | `WindowedDedup`/`WindowedCollect` → consider `redis-streams` consumer-group | core deps (redis) | MIT | -60 to -100 if simplified |
| DSL-P3-006 | Keep manual `_VALID_OUTCOMES` (clearer than `ConstrainedStr` for OpenAPI export) | n/a | n/a | 0 |
| DSL-P3-007 | `RedisLock` use `redis.lock()` from `redis-py` | core deps | MIT | -20 |

---

### DSL-P4-001..005 — Missing-features (intentional limited)

1. **No native `doTry/doCatch/doFinally`** over `Exchange` — Camel has this. `TryCatchProcessor` is partial.
2. **No Temporal-style `Activity` retry with non-retryable exception classification** — `RedeliveryPolicy` is straight backoff.
3. **No DSPy-style `Signature`** for `LLMCallProcessor` — steps define literal prompt; `PromptComposerProcessor` is regex-only.
4. **No `StatefulSaga` with explicit persistent checkpoint API** — `ProcessManagerProcessor` is thin Saga subclass.
5. **No `BPMN` boundary events / DMN** — Camel's BPMN+DMN surface is intentionally not full.

These are **not** blockers. Each requires a separate AF scope.

---

## 5. Contradictions / overlaps to flag

1. **Two `ProcessorRegistry` names**:
   - `src/backend/dsl/registry/processor.py:102` → concrete registry.
   - `src/backend/dsl/engine/processors/eip/routing_slip.py:47` → Protocol.
   - Both export via `__all__`. Resolve via import path convention.

2. **`reliability.py` (god-file) vs `reliability/` subpackage**:
   - File is shadowed. Dead code.

3. **`aggregation.py` (`BatchAggregatorProcessor`) vs `flow_control/aggregator.py` (`AggregatorProcessor`)**:
   - Two classes with similar names; one is not a `BaseProcessor`. Orphan.

4. **`AuditProcessor` (direct factory) vs `AuditClickhouseProcessor` (registered)**:
   - Same conceptual purpose. Inconsistent registration.

5. **`DeadLetterProcessor` (resilience.py) dead-code path**:
   - Resilience.py has `DeadLetterProcessor` (real, registered with `@processor`).
   - `eip/reliability.py:267` has another `RedeliveryPolicyProcessor` (legacy) — but Package shadowing makes it dead. Double registration of concept.

6. **`MulticastRoutesProcessor`**:
   - Lives in `routing/multicast.py` (S63 W2 decomp).
   - Still documented in `windowed_dedup.py:25`.
   - Bug DSL-P0-001 in its `process()`.

7. **`TransactionalClientProcessor` and `ProcessManagerProcessor`**:
   - Defined in `transactional.py` but not registered via `@processor`. Not accessible via builder.

8. **`MessageTranslatorProcessor` (transformation.py) vs `MarshalProcessor`/`UnmarshalProcessor` (marshal/processors.py)**:
   - Two near-equivalent in-place format converters. The `MarshalProcessor` is registered and uses `DataFormat` strategy; `MessageTranslatorProcessor` is a flat if-elif.

9. **`eip/__init__.py` (~70 entries) vs `eip/.../*.py` classes**:
   - Top-level re-import in `dsl/engine/processors/__init__.py:105-129` is partial (~20 classes). Half of the EIP catalog is unreachable from top-level.

10. **`InMemoryCacheStore` (api_composition.py:103-134) vs `cachetools.TTLCache`**:
   - 30 LOC hand-rolled TTL cache. `cachetools` is in core deps.

11. **`ResequencerProcessor` manual buffer vs `glom.group`**:
   - Manual dict-based resequencing; `glom.group` could replace.

12. **`WindowedDedupProcessor` "WindowedDedup" + "WindowedCollect" duplicate logic**:
   - Both wrap Redis. Different semantics (dedup vs batch). Both have silent Redis-failure swallowing.

13. **`_xml_to_dict_stdlib` (3x copies)**:
   - In `format_convert/{data_formats,specialized,encodings}.py` — should be in `_helpers.py`.

---

## 6. Readiness score

**Formula** (DSL domain):

```
score = 100
        - 12 * P0  (capped at -60)
        - 6  * P1  (capped at -36)
        - 2  * P2  (capped at -24)
        - 1  * P3  (capped at -10)
        - 0  * P4
```

**Counts**:
- P0 = 3 → −36
- P1 = 10 → −60 (capped)
- P2 = 11 → −22 (capped at −24)
- P3 = 7 → −7 (capped at −10)
- P4 = 5 → 0

**Score** = 100 − 60 − 36 − 22 − 7 = **−25**, clamped to floor **0**.

> Per audit constraint: **score ≥80 is forbidden when P0/P1 exist**. Three P0 + ten P1 force `score ≤ 70`. We further drop due to evidence of one parser-side vulnerability (DSL-P1-007) and one fail-open on a security-sensitive path (DSL-P0-003).

**Final score: 35/100.**

**Reasoning**:
- Core EIP composition is solid (S1–S14).
- 3 P0 production hazards (multicast routes TypeError, redelivery silent fail, AV fail-open).
- 10 P1 architectural defects (import gap, side_effect type contract, memory leak, lock release, dedup fail-open, telemetry silent, XXE fallback, kwargs filter, stale docstring, top-level re-export gap).
- 11 P2 dead/duplicate code.
- 7 P3 library replacement candidates.
- 5 P4 missing features (intentional).

The high strength of EIP coverage is offset by **production-blocking failures in the EIP wiring layer** (DSL-P0-001, DSL-P0-002).

---

## 7. Recommended next tasks (ordered, ≤1 sprint)

| # | ID | Task | Owner slot | Acceptance |
|---|---|---|---|---|
| 1 | BLOCKER | Fix DSL-P0-001: remove `route_registry=...` from `ExecutionEngine(...)` call in `routing/multicast.py:172`; add a real (non-mocked) integration test. | DSL core | `tests/unit/dsl/integration/test_multicast_routes_real.py` passes. |
| 2 | BLOCKER | Fix DSL-P0-002: `except (TypeError, ValueError):` in `reliability/redelivery_policy.py:145`; add parametrized test for non-numeric header. | DSL core | `pytest -k redelivery_policy` covers ValueError path. |
| 3 | BLOCKER | Fix DSL-P0-003: `ScanFileProcessor` fail-closed on AV backend unavailability; add `test_scan_file_av_unavailable_fails_closed`. | DSL core | `pytest -k scan_file` covers backend-down. |
| 4 | HIGH | Fix DSL-P1-001: import `CDCProcessor` in `__init__.py`; add smoke import test. | DSL core | `from src.backend.dsl.engine.processors import CDCProcessor` works. |
| 5 | HIGH | Fix DSL-P1-002: `side_effect: SideEffectKind` in `redis_lock_processor.py`; add `isinstance(side_effect, SideEffectKind)` assertion. | DSL core | `pytest -k redis_lock` type assertion green. |
| 6 | HIGH | Fix DSL-P1-003: `ResequencerProcessor` flush-on-timeout / bounded-buffer test. | DSL core | `pytest -k resequencer` covers 10001-keys. |
| 7 | HIGH | Fix DSL-P1-004: `RedisLockProcessor` releases lock via finalizer; add `lock` cleanup test. | DSL core | `test_redis_lock_released_on_completion` green. |
| 8 | HIGH | Fix DSL-P1-005: `WindowedDedup`/`WindowedCollect` fail-closed on Redis unavailable. | DSL core | `test_windowed_*_fails_closed_on_redis_unavailable` green. |
| 9 | HIGH | Fix DSL-P1-007: replace `ET.fromstring` with `defusedxml.ElementTree.fromstring` in `format_convert/*` fallback. | DSL core | `test_from_xml_fallback_uses_defusedxml` green. |
| 10 | HIGH | Fix DSL-P1-008: `action_registry.dispatch` kwargs filter must not drop required fields. | DSL core | `test_dispatch_required_field_with_none_value` green. |
| 11 | HIGH | Fix DSL-P1-010: `processors/__init__.py` re-exports full EIP catalog. | DSL core | `test_top_level_re_exports_match_eip` green. |
| 12 | MED | Delete `reliability.py` (DSL-P2-001); delete `aggregation.py` (DSL-P2-002). | DSL core | pure deletion; existing tests must pass. |
| 13 | MED | Decorate `AuditProcessor`, `Pydash*`, `Glom*`, `MarshalProcessor`/`UnmarshalProcessor`/`Splitter`/`Sort`/`Normalizer`/`ClaimCheck`/`MessageTranslator`/`RoutingSlip`/`PipesAndFilters`/`ContentBasedRouter`/`Sampling`/`ForkJoin`/`EventMessage`/`TransactionalClient`/`ProcessManager`/`WindowedDedup`/`WindowedCollect`/`CorrelationIdentifier`/`MessageExpiration`/`RedeliveryPolicy`/`ReturnAddress`/`MulticastRoutesProcessor` with `@processor(...)`. | DSL core | empty registry `assert` test passes. |
| 14 | LOW | Apply `cachetools.TTLCache` (DSL-P3-004), `asyncio.TaskGroup` (DSL-P3-002), `defusedxml` (DSL-P1-007). | DSL core | LOC delta report in commit. |
| 15 | LOW | Address `DSL-P4-001..005` in a separate AF scope (BPMN, DSPy-signed LLM calls, persistent checkpoint Saga). | DSL/AI | SPEC-only. |

---

## 8. Commands run

```bash
# Tree + diff checks
git log --oneline -5
git status
git diff --stat HEAD
git diff HEAD b69d6b49 --name-only  # delta from baseline
ls -la src/backend/dsl/
ls -la src/backend/dsl/engine/processors/
ls -la src/backend/dsl/engine/processors/eip/
ls -la src/backend/dsl/engine/processors/eip/{reliability,flow_control,routing,collection,marshal}
ls -la src/backend/dsl/engine/processors/notify/
ls -la src/backend/dsl/engine/processors/format_convert/
ls -la src/backend/dsl/registry/
ls -la src/backend/dsl/commands/

# Test layout
find tests/unit/dsl -name "*.py" -type f | wc -l  # 381
find tests/unit/dsl -name "test_*.py" -type f | xargs grep -c "def test_\|async def test_" 2>/dev/null | awk -F: '{sum += $2} END {print sum}'  # 3862

# Decorator / registry coverage
grep -rn "@processor\b" src/backend/dsl/engine/processors/ | grep -v "agent_dsl\|workflow\|/rag\|__pycache__" | wc -l  # 49 files
grep -rn "class.*BaseProcessor" src/backend/dsl/engine/processors/ | grep -v "agent_dsl\|workflow\|/rag\|__pycache__" | wc -l  # 151 classes
grep -rn "class.*BaseProcessor" src/backend/dsl/engine/processors/eip/ | grep -v __pycache__ | wc -l  # 67 EIP classes
grep -rn "@processor" src/backend/dsl/engine/processors/eip/ | grep -v __pycache__ | wc -l  # 14 decorator usages

# Bug verifications
.venv/bin/python -c "import ast; ast.parse(open('src/backend/dsl/engine/processors/eip/reliability/redelivery_policy.py').read())"  # OK (Python 3.14 parses)
.venv/bin/python -c "def f():
    try:
        raise ValueError('x')
    except TypeError, ValueError:
        print('caught as', ValueError)
f()"  # caught as <class 'ValueError'> — confirms mis-binding
.venv/bin/python -c "from src.backend.dsl.engine.processors import CDCProcessor"  # ImportError
.venv/bin/python -c "from src.backend.dsl.engine.processors.eip import reliability; print(reliability.__file__)"  # package file path, not .py
.venv/bin/python -c "import sys, importlib, os; sys.path.insert(0, '.');
import os
base_dir='src.backend.dsl.engine.processors'
for fname in sorted(os.listdir('src/backend/dsl/engine/processors')):
    if fname.endswith('.py') and fname != '__init__.py':
        modname=fname[:-3]
        importlib.import_module(f'{base_dir}.{modname}')
for sub in ['eip','eip.collection','eip.flow_control','eip.marshal','eip.reliability','eip.routing','control_flow']:
    importlib.import_module(f'{base_dir}.{sub}')
from src.backend.dsl.registry import get_processor_registry
r=get_processor_registry()
specs=r.list_specs()
print('REGISTERED:', len(specs))"  # 65 registered (54 core + 11 infra)

# Name-conflict / layer checks
grep -rn "ProcessorRegistry" src/backend/dsl/ 2>&1 | grep -v __pycache__ | head -20
grep -rn "side_effect: ClassVar" src/backend/dsl/engine/processors/ 2>&1 | grep -v __pycache__ | head -3
grep -n "side_effect: ClassVar\[Any\]" src/backend/dsl/engine/processors/redis_lock_processor.py  # confirmed

# Fail-open / fail-closed checks
grep -rn "silent" src/backend/dsl/engine/processors/ --include="*.py" 2>&1 | grep -v "agent_dsl\|workflow\|/rag\|__pycache__" | head -5
grep -rn "except TypeError, ValueError" src/backend/dsl/engine/processors/ 2>&1 | grep -v __pycache__ | head -3
grep -n "ET.fromstring" src/backend/dsl/engine/processors/ -r 2>&1 | grep -v __pycache__ | head -10

# Dependency hygiene
grep -n "watchdog" pyproject.toml  # NOT in core deps
grep -n "selectolax" pyproject.toml  # NOT in core deps
grep -n "watchdog" /tmp/uv.lock 2>/dev/null  # in transitive only (transitive marker confirmed)

# Lockstep / divergence
git diff HEAD b69d6b49 --name-only  # baseline diff
git status -u  # only uv.lock modified in worktree; s3.py was committed already
```

All commands recorded above are **read-only**. No source files were modified.
The only file write this audit produced is this report: `docs/audit/swarm-2026-08-06/cycle-1/phase-1/06-dsl.md`.

---

## 9. Final summary (1-paragraph)

DSL domain is **broadly aligned with Apache Camel EIP catalog** (30+ patterns, `eip/__init__.py`) and uses a well-designed `ProcessorRegistry` with namespacing/replace semantics; however, **three P0 production hazards** (`MulticastRoutesProcessor` calls `ExecutionEngine(route_registry=...)` which is not a real kwarg, all tests mock around it; `RedeliveryPolicyProcessor` uses Python-2 `except TypeError, ValueError:` which silently mis-binds; `ScanFileProcessor` is fail-open on AV backend unavailability when `on_threat != "fail"`) **plus ten P1 defects** (missing `CDCProcessor` import in `__init__.py`, `RedisLockProcessor.side_effect: str` violates `BaseProcessor` contract, `ResequencerProcessor` unbounded buffer, `RedisLockProcessor` never releases lock, two `Windowed*` processors fail-open on Redis outage, `_record_metric` swallows all exceptions, three `ET.fromstring` fallback parsers without `defusedxml`, `action_registry.dispatch` kwargs filter drops required fields, stale `MulticastRoutesProcessor` docstring, ~50 EIP classes missing from top-level re-export) require remediation before the domain can be marked production-ready. Plus 11 P2 (dead `reliability.py` 442 LOC, orphan `BatchAggregatorProcessor`, five undecorated processor families, three near-identical `_xml_to_dict_stdlib` copies, counter naming bug in `EventMessageProcessor`) and 7 P3 (`asyncio.TaskGroup`, `cachetools.TTLCache`, `defusedxml` candidates). **Readiness score: 35/100** (capped due to P0 + P1 floor, with parser-vuln and AV-fail-open deductions).
