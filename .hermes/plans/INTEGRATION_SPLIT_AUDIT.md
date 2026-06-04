# integration.py Split Audit (S39 W4)

**Date**: 2026-06-04 | **Source**: `src/backend/dsl/builders/integration_core.py` (IntegrationCoreMixin)
**Status**: SKELETON (orchestrator follow-up для actual method moves)

## Группировка (2 groups per subagent classification)

### Group A — Runtime Invocation (6 methods)

Методы, которые делегируют выполнение к action handlers, workflows,
sub-routes и Python function references. Returns `self._add(Processor)` via MRO contract.

| # | Method | Processor | Signature |
|---|--------|-----------|-----------|
| 1 | `dispatch_action` | DispatchActionProcessor | `(action, *, payload_factory=None, result_property='action_result')` |
| 2 | `invoke` | InvokeProcessor | `(action, *, mode='sync', payload_factory=None, reply_channel=None, result_property='invoke_result', invocation_id_property='invocation_id', timeout=None, correlation_id=None)` |
| 3 | `to_route` | PipelineRefProcessor | `(route_id, *, result_property='sub_result')` |
| 4 | `invoke_workflow` | InvokeWorkflowProcessor | `(name, *, mode='async-api', args=None, namespace='default', ...)` |
| 5 | `call_function` | CallFunctionProcessor | `(func, *, result_property='call_result', ...)` |
| 6 | `__call__` / extras | — | TBD |

**File**: `src/backend/dsl/builders/integration_group_a.py`

### Group B — Data / AI / ML / Documents / Utility (9 methods)

Методы, которые process, generate, validate или persist data on the exchange.
Mostly write into `exchange.body` / `exchange.properties` rather than calling
out to a downstream dispatch chain.

| # | Method | Processor | Signature |
|---|--------|-----------|-----------|
| 1 | `audit` | AuditProcessor | `(*, action=None, action_from=None, actor='system', ...)` |
| 2 | `scan_file` | ScanFileProcessor | `(*, s3_key_from=None, data_property=None, on_threat='fail', result_property='antivirus_scan_result')` |
| 3 | `get_setting` | GetSettingProcessor | `(path, *, to='body.setting', default=None)` |
| 4 | `validate_response` | ResponseValidatorProcessor | `(*, schema=None, on_error='fail', source='out_body')` |
| 5 | `render_docx` | RenderDocxProcessor | `(*, template, context_from=None, output_to='docx_path')` |
| 6 | `render_pdf` | RenderPdfProcessor | `(*, template, context_from=None, output_to='pdf_path')` |
| 7 | `embed` | EmbeddingsProcessor | `(text, *, model=None, to='body.embedding', ...)` |
| 8 | `extract_pii` | PIIExtractProcessor | `(*, input_from=None, mask=False, to='body.pii')` |
| 9 | `redact` | RedactProcessor | `(*, fields=None, to='body.redacted')` |

**File**: `src/backend/dsl/builders/integration_group_b.py`

## Cross-cutting concerns

None identified на этапе classification. Group A = I/O-bound dispatch,
Group B = data transformation. Чёткое разделение.

## LSP-ДИАГНОСТИКА: required для orchestrator

Перед перемещением method bodies orchestrator должен проверить:
- `pyright src/backend/dsl/builders/integration_group_a.py` — нет ли circular imports
- `pyright src/backend/dsl/builders/integration_group_b.py` — нет ли type errors
- `pytest tests/unit/dsl/` — все существующие tests проходят после split

## S39 W4 Status

- [x] Subagent classification (6 + 9 methods)
- [x] Skeleton files (IntegrationGroupA, IntegrationGroupB)
- [x] Test file (4 tests per group + 3 audit tests)
- [ ] **Orchestrator follow-up**: move 15 method bodies с LSP verification
- [ ] **Orchestrator follow-up**: update IntegrationCoreMixin MRO (delete migrated methods)
- [ ] **Orchestrator follow-up**: integration test (route using both GroupA+GroupB methods)

Refactored LOC (planned): 145 LOC → 2 × ~80 LOC mixin files + cleaner IntegrationCoreMixin (~30 LOC).
