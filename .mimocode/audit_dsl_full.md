# DSL Layer Full Audit — `src/backend/dsl/` (520 .py files)

## Grand Totals

| Metric | Count |
|---|---|
| Files read | 520 |
| Layer violations | 87 |
| Security issues | 32 |
| Dead code instances | 48 |
| Missing docstrings | 63 |
| Code smells | 55 |

---

## 1. LAYER VIOLATIONS (87 instances, ~65 files)

Architecture rule: DSL may only import from `src.backend.core.*` and `src.backend.dsl.*`.
Imports from `infrastructure/*`, `services/*`, `entrypoints/*` are forbidden.

### engine/processors/ root (30 violations, 20 files)

- `batch.py:34` → `infrastructure.database.database.get_external_db_registry`
- `dask_compute.py:26` → `infrastructure.execution.dask_backend`
- `dq_check.py:37` → `services.ops.data_quality`
- `export.py:39` → `services.io.export_service`
- `external.py:53` → `services.ai.ai_graph`; `:103` → `infrastructure.clients.external.cdc`
- `feedback.py:154` → `services.ai.feedback`
- `graphql_query.py:100` → `infrastructure.clients.transport.http_httpx`
- `ingest_file.py:107` → `services.ai.document_parsers`; `:179` → `infrastructure.clients.storage.s3_pool`
- `integration.py:34` → `infrastructure.clients.messaging.event_bus`; `:62` → `services.ai.agent_memory`
- `invoke.py:127` → `services.execution.invoker`
- `invoke_workflow.py:125` → `infrastructure.workflow.factory`
- `ml_inference.py:149` → `services.ai.ai_agent`; `:185` → `infrastructure.clients.storage.redis`; `:332` → `infrastructure.database.database`
- `ml_predict.py:80` → `services.ai.ml.model_loader`; `:94` → `services.ai.model_registry`
- `notebook_dsl.py:15`, `notebook_execute.py:12`, `notebook_export.py:12` → `services.jupyter.execution_service`
- `saga_lra.py:32` → `infrastructure.database.database`; `:243` → `infrastructure.workflow.saga_state`
- `scan_file.py:86` → `infrastructure.antivirus.factory`; `:128` → `infrastructure.clients.storage.s3_pool`
- `security.py:34,39` → `entrypoints.api.dependencies.auth_selector`
- `vault_secret.py:81` → `infrastructure.secrets.vault_backend`
- `redis_lock_processor.py:83` → `infrastructure.clients.storage.redis_lock`

### engine/processors/ai/ (13 violations, 13 files)

- `cache_processor.py:43`, `cachewrite_processor.py:51` → `infrastructure.clients.storage.redis`
- `getfeedbackexamples_processor.py:126` → `services.ai.rag_service`
- `guardrails_processor.py:77,98,118,148` → `services.ai.guardrails.*` (4 imports)
- `llmcall_processor.py:12,173,176` → `services.ai.gateway.*`, `infrastructure.resilience.retry`, `services.ai.ai_agent`
- `llmfallback_processor.py:45` → `services.ai.ai_agent`
- `ragingest_processor.py:54` → `services.ai.rag_service`
- `ragpiiredaction_processor.py:51` → `services.ai.pii.retrieval_masker`
- `ragquery_processor.py:82,91` → `services.ai.rag_service`, `services.ai.rag.strategy_selector`
- `sanitizepii_processor.py:22` → `infrastructure.security.ai_sanitizer`
- `semanticrouter_processor.py:56` → `services.ai.rag_service`
- `vectorsearch_processor.py:35` → `services.ai.rag_service`
- `banking_processors/base.py:107` → `infrastructure.resilience.retry`

### engine/processors/agent_dsl+ai_banking (9 violations)

- `agent_graph.py`, `agent_run.py`, `plan_execute.py`, `reflection_loop.py` → `services.ai.*`
- `ai_banking/_base.py` → `infrastructure.*`
- `mcp_tool.py` → unvalidated URI to `Client()` (SSRF risk)
- `ai_tool_dispatch.py` → `services.ai.*`

### engine/processors/eip/ (7 violations, 5 files)

- `api_composition.py:90`, `idempotency.py:36`, `resilience.py:44` → `infrastructure.*`
- `transformation.py:211,225,254,265` → `infrastructure.clients.storage.*`
- `windowed_dedup.py:116,202,266,356` → `infrastructure.clients.storage.redis`

### engine/processors/components/ (4 violations)

- `databasequeryprocessor.py:52` → `infrastructure.database.database`
- `httpcallprocessor.py:47` → `infrastructure.clients.transport.http`
- `s3readprocessor.py:35`, `s3writeprocessor.py:35` → `infrastructure.clients.storage.s3_pool`

### rpa+sink+storage+streaming+telegram (12 violations)

- `sink_publish/generic.py:62` → `infrastructure.sinks.factory`
- `sink_publish/messaging.py:55,107` → `infrastructure.sinks.mq_sink`, `infrastructure.sinks.ws_sink`
- `sink_publish/protocols.py:50,105` → `infrastructure.sinks.grpc_sink`, `infrastructure.sinks.soap_sink`
- `storage_ext.py:148,239` → `infrastructure.database.database`, `infrastructure.clients.storage.redis`
- `storage/s3.py:61` → `services.storage.StorageFacade`
- `telegram/_common.py:36`, `edit.py:62`, `mention.py:65`, `reply.py:60`, `send.py:71`, `send_file.py:139` → `infrastructure.clients.external.telegram_bot`

### builders/ (4 violations)

- `policy_mixin.py:270` → `infrastructure.resilience.coordinator`
- `notify.py:122` → `services.notifications.apprise_service`
- `content_mixin.py:82` → `urllib.request.urlopen` (bypasses infra HTTP client)
- `agent_dsl/infra.py:199` → `services.ai.agent_sandbox`

### engine/ root (2 violations)

- `execution_engine.py:199` → `infrastructure.application.slo_tracker`
- `versioning.py:21` → `infrastructure.database.session_manager`

### processors/ subdir (2 violations)

- `batch_processor.py:32` → `infrastructure.database.database`
- `data_lineage.py:142` → `services.lineage`

### orchestration (borderline, allowed)

- `registers_integrations.py:234` → `infrastructure.clients.external.search_providers` (lazy import in setup func)

---

## 2. SECURITY ISSUES (32 instances)

### CRITICAL (P0)

| File:Line | Issue |
|---|---|
| `eip/marshal/formats.py:269` | `pickle.loads(data)` — arbitrary code execution. No runtime guard beyond "trusted only" comment |
| `eip/collection/collect.py:105` | `simpleeval.SimpleEval` on DSL-supplied `condition` — code execution vector |
| `components/httpcallprocessor.py:60` | `url.format(**exchange.in_message.body)` — user body keys injected into URL template |
| `components/databasequeryprocessor.py:40-47` | SQL blocklist incomplete — `WITH`, `SET`, `EXEC`, `/**/` comment obfuscation bypass it |
| `storage_ext.py:154` | SQL injection via unquoted table names in f-string |
| `storage/s3.py:154` | Same SQL injection pattern via table name |
| `sink_publish/messaging.py:220-223` | `MqttPublishProcessor.to_spec()` leaks `username` and `password` |

### HIGH (P1)

| File:Line | Issue |
|---|---|
| `content_mixin.py:82` | `urllib.request.urlopen()` — no cert verification, no SSRF protection, URL from exchange body |
| `content_mixin.py:81,93` | `assert` used for runtime validation — stripped by `-O` flag |
| `eip/transformation.py:69` | `f"<{k}>{v}</{k}>"` — XSS/XML injection in fallback XML generation |
| `ldap_query.py:184` | `to_spec()` leaks password into YAML output |
| `webhook_signature.py:195` | `to_spec()` returns raw `secret` in spec dict |
| `llmcall_processor.py:18-22` | Hardcoded stale LLM pricing (gpt-4-0613, gpt-3.5-turbo) |
| `script_runner.py:113` | `os.environ.copy()` passed to subprocess — inherits all secrets |
| `guardrails_processor.py` | `_resolve_config()` returns None on ImportError — silently disables all security guardrails |
| `notify.py:169` | `from_imap()` accepts plaintext `password: str` parameter |
| `converters_mixin.py:275-295` | `to_jwt()` accepts `secret: str` as DSL argument — plaintext in YAML config |
| `security.py:116-132` | `jwt_sign()`/`jwt_verify()` accept `secret_key: str` directly |
| `ai_banking/credit.py,document.py,identity.py` | Raw user-supplied JSON embedded directly into LLM prompts without sanitization |
| `rpa/operations/regexprocessor.py:63` | No regex complexity limit — catastrophic backtracking can hang event loop |

### MEDIUM (P2)

| File:Line | Issue |
|---|---|
| `versioning.py:114-115` | Snapshot save failure caught by bare `except Exception`, silently swallowed |
| `components/s3readprocessor.py:47` | `_validate_sql` blocklist is naive |
| `storage_ext.py:67-69` | Neo4j credentials from `os.environ` instead of Vault |
| `streaming/windows.py` | Unbounded buffer in tumbling/sliding windows — memory growth without limit |
| `reranker.py:160` | Mutates input candidate dicts by adding `rerank_score` — side effect on shared objects |

### LOW (P3)

| File:Line | Issue |
|---|---|
| Multiple processors | Silent `except Exception: pass` — failures invisible to monitoring (~15 instances) |
| `codec/__init__.py:100` | `cbor2.loads()` on untrusted input could trigger deserialization gadgets |
| `eip/windowed_dedup.py:171` | SHA256 truncated to 16 chars — collision risk for dedup |
| `streaming/operations.py:66-70` | Direct `out_message.body` assignment instead of `set_out()` |

---

## 3. DEAD CODE (48 instances)

### Entirely dead files (5 files, ~450 lines)

- `builders/camel_eip.py` — `CamelEIPMixin` has `__slots__ = ()` and zero methods
- `builders/integration_group_a.py` — skeleton with empty class
- `builders/integration_group_b.py` — skeleton with empty class
- `builders/collection_mixin.py` — duplicate of `collection.py` (not in MRO)
- `builders/request_reply.py` — duplicate of `request_reply_mixin.py` (not in MRO)

### Unused imports/functions

- `engine/processors/base.py` — `collect_route_results()` and `SubPipelineExecutor` in `__all__` but not re-exported
- `engine/dry_run.py:162` — `_now_ms()` defined but never called
- `codec/__init__.py:64-66` — `_BANKING_FORMATS` declares `fix`, `mx`, `edifact` with no implementation
- `registry/processor.py:194` — `list_all()` trivial alias for backward-compat
- `_python_blueprints.py:204` — `_ = max_retries` param silently discarded
- `ragquery_processor.py` and `vectorsearch_processor.py` — `_RAG_STRATEGIES` tuple duplicated across both files
- 10 rpa/operations files — `_rpa_logger` imported but unused
- 7 banking processor files — `_logger` imported but unused
- `cron_schedule.py` — dataclass-only, no `process()` method, not a real processor
- `data_query.py` — `JsonPathProcessor` duplicates `jsonpath_query.py`
- `business.py:230` — `HumanApprovalProcessor` duplicated by `hitl_approval.py`
- `ml_inference.py:290` — `OutboxProcessor` name collision with `business.py`
- `patterns.py:289-292` — dead branch where both `if` and `else` do identical work

### Empty TYPE_CHECKING blocks (10+ files)

- `reranker.py`, `credit.py`, `fraud.py`, `loan.py`, `risk.py`, `segmentation.py`, `results.py`, `integration_core/__init__.py`, `sources_mixin/__init__.py`, `eip/_base.py`

---

## 4. MISSING DOCSTRINGS (63 instances)

### Private methods with complex logic but no docstrings

- `validation.py` — `_check_ordering()`, `_check_error_handling()`, `_check_route_refs()`
- `middleware.py` — 11 auto-generated placeholder docstrings (`"Выполнить операцию init ."` pattern)
- `batch_processor.py` — `_set_result`, `_run_batches`, `_bulk`, `_do_delete`
- `patterns.py` — `SwitchProcessor.process()`, `MergeProcessor.process()`, `DeduplicateProcessor.process()`, `DebounceProcessor.process()`

### Widespread boilerplate `process()` docstrings

~80 processors have the identical auto-generated `process()` docstring: `"Обработать exchange согласно логике процессора..."`. These add zero value.

### Specific gaps

- `helpers/banking.py` — `validate_inn`, `validate_kpp`, `validate_bic`, `validate_swift` lack docstrings
- `helpers/datetime_utils.py` — `now`, `add_days`, `to_iso8601` lack docstrings
- `data_query.py`, `dq_check.py`, `external.py`, `invoke_async.py`, `mask_pii.py`, `regex_extractor.py`, `file_watch.py`, `ml_inference.py`, `ml_predict.py` — `process()` or key helper methods undocumented
- `storage_ext.py` — `Neo4jQueryProcessor.process()`, `TimeSeriesWriteProcessor.process()`

---

## 5. CODE SMELLS (55 instances)

### Structural

- `engine/processors/__init__.py` — 423-line god-file importing every processor
- `base/__init__.py` — MRO with 30+ mixins, any method name collision silently resolves via C3
- `service/registry.py:55-62` — module-level mutable `_registry` singleton with `global`, not thread-safe
- `orchestration/triggers.py:408-416` — `get_trigger_registry()` global singleton has no lock
- `saga_lra.py:26-37` — module-level mutable global with `global` keyword, thread-unsafe

### Duplicated patterns

- `_apply_target()` helper copied across 9 processor files — should be in `BaseProcessor`
- `_resolve()` / `_resolve_source()` dot-path traversal duplicated in 4+ processor files
- Feature-flag guard pattern (`try: from features import... if not feature_flags.X: return except: pass`) copy-pasted in 10+ files
- `_normalize_btn()` identical in `telegram/edit.py` and `telegram/send.py`
- 7 base mixin files share identical 26-line module docstring (182 lines total)
- `_isawaitable()` helper duplicated in `event_message.py` and `pipes_and_filters.py`
- `_check_capability()` copied across 3 ai_banking files instead of being in `_base.py`
- `script_python/node/ruby/shell` methods differ only by `language=` parameter — should be one method

### Silent exception swallowing

- `eventbus_mixin.py:52`, `policy_mixin.py:223`, `linter.py:103`, `middleware.py:210` — `except Exception as _: pass`
- `transformation.py:315,321,330` — three silent swallows in NormalizerProcessor
- `aggregators.py:73,103,141` — fallback to original body on any exception
- `idempotency.py:47` — fails open on Redis errors (dedup bypass)

### Deprecated / unsafe patterns

- `processor_pool.py:142` — `asyncio.get_event_loop()` deprecated since 3.10
- `orchestration/triggers.py:58` — `except (CancelledError, Exception)` — `CancelledError` is `BaseException` since 3.9
- `codec/format_converters/toml.py:135` — `_toml_key` allows bare keys starting with digits (violates TOML spec)
- `codec/converters.py:26` — `except Exception as _: return value` swallows all errors in numpy conversion

### Type safety

- `registry/lazy_processor.py:85` — `base: Any` instead of `ProcessorRegistry`
- `registry/processor.py:300` — `processor()` return type is `Any`
- `llm_structured/_protocol.py` — 3 signature mismatches with actual implementations
- `data_store_mixin.py:135`, `deferred_execution_mixin.py:282`, `request_reply_mixin.py:214` — `object.__setattr__` bypasses `__slots__`

### Naming / conventions

- `commands/setup/__init__.py` — re-exports private `_register_*` functions in `__all__`
- `codec/format_converters/toml.py:101` — extra parens around generator expression
- `llmfallback_processor` uses `llm_provider_used` while `llmcall_processor` uses `llm.provider`
- `ai_rpa/ai_llm.py:36-50` — `mcp_tool` and `agent_graph` methods conflict with `agent_dsl/infra.py` via MRO

---

## 6. FILES WITH NO ISSUES (clean)

These files had no violations, security issues, dead code, or smells:

- `dsl/__init__.py` (1 line, namespace marker)
- `dsl/builder.py` (14 lines, re-export shim)
- `dsl/contracts/__init__.py`
- `adapters/base.py`, `adapters/types.py`
- `di/types.py`, `di/decorators.py`
- `helpers/__init__.py`
- `models/agent_definition.py`, `models/__init__.py`
- `loaders/agent_loader.py`, `loaders/__init__.py`
- `service/facade.py`, `service/__init__.py`
- `workflow/spec/workflow.py`, `workflow/spec/policies.py`
- `workflow/gateways.py`, `workflow/builder/__init__.py`
- `engine/context.py`, `engine/exchange.py`, `engine/step_trace.py`, `engine/tracer.py`
- `enrichment/deadline.py`
- `eip/core.py`, `eip/messaging.py`, `eip/protocols.py`, `eip/streaming.py`

---

## 7. ARCHITECTURAL DEBT SUMMARY

The most impactful finding is the systematic pattern of DSL processors importing directly from `infrastructure/*` and `services/*` layers (87 violations). This defeats the purpose of layer isolation. The recommended remediation:

1. **Create capability-checked Protocol facades** in `core/` for each infrastructure/service dependency (Redis, S3, database, AI gateway, etc.)
2. **Use DI injection** via `BaseProcessor.__init__` or exchange properties to provide these facades at runtime
3. **Move `to_spec()` secret redaction** to a shared mixin — currently some processors redact, others leak
4. **Extract duplicated patterns** (`_apply_target`, `_resolve`, feature-flag guard, `_check_capability`) into `BaseProcessor` or shared mixins
5. **Delete 5 entirely dead builder files** and ~15 unused `_rpa_logger`/`_logger` imports
6. **Replace `pickle.loads`** in `marshal/formats.py` with explicit allowlist-gated deserialization
7. **Replace `urllib.request.urlopen`** in `content_mixin.py` with infrastructure HTTP client + SSRF protection
