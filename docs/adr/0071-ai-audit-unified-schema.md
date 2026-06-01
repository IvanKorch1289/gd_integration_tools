# ADR-0071 — AI Audit Unified Schema — `ai.invocation.*` события

* Статус: **Draft** (Sprint 27 candidate, [wave:s27/w5-audit-unified])
* Связано с: `gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 8 (audit unified), PLAN.md V22.4 §S27, ADR-NEW-24.
* Память: [[feedback_wave_8_rag]], [[feedback_sprint10_closure]] (carryover S9 audit), ADR-NEW-S17/K3 (Unified AuditService).

## Контекст

Текущее состояние AI-аудита — **3 разрозненных стока без единой схемы**:

1. `core/ai/workspace_manager.py::cleanup_loop` — workspace lifecycle events → ClickHouse legacy `audit_clickhouse.py`.
2. `services/ai/gateway/langfuse_callback.py` (v2) и `langfuse_callback_v3.py` — LLM-вызовы → Langfuse SaaS (PII не маскируется).
3. `services/ai/costs/dashboard.py` + `services/ai/metrics.py` — cost-tracking → Prometheus + Streamlit.
4. Sentry — exception capture (стандартный SDK).
5. `core/audit/clickhouse_audit_sink.py` (S17/K3 ADR-NEW) — Unified AuditService уже принят, но не расширен для AI events.

**Проблема**:
- Нельзя задать query «дай мне все события одной LLM-инвокации по correlation_id» — данные раскиданы по 4 систем.
- Langfuse traces содержат raw PII (не маскируются перед отправкой).
- ClickHouse legacy `audit_clickhouse.py` дублирует Unified AuditService.
- Нет единой схемы события `ai.invocation.{requested|completed|denied|failed}`.

## Решение (Draft)

**Унифицированная AI Audit Schema** — расширение Unified AuditService (S17/K3) для 9 типов событий + cut-over legacy ClickHouse.

### 9 типов событий

```python
AI_INVOCATION_EVENTS = [
    "ai.invocation.requested",          # AIGateway.invoke() called
    "ai.invocation.policy_resolved",    # PolicyResolver returned AIPolicySpec
    "ai.invocation.sanitized",          # input_sanitizers applied (PII)
    "ai.invocation.guarded",            # input/output guards verdicts (NeMo/Llama Guard)
    "ai.invocation.completed",          # LLM responded successfully
    "ai.invocation.denied",             # guard blocked OR capability denied
    "ai.invocation.failed",             # exception (timeout, network, parsing)
    "ai.invocation.pii.mask",           # PIITokenizer.mask_reversible
    "ai.invocation.pii.unmask",         # PIITokenizer.unmask
]
```

### Схема события

```json
{
  "event_id": "01J9HX4Z8KT5Y6...",                  // UUIDv7
  "event_type": "ai.invocation.completed",
  "timestamp": "2026-05-22T15:30:45.123Z",
  "schema_version": 1,
  
  "correlation_id": "req-abc-123",                  // из RequestContext (ADR-NEW-3)
  "tenant_id": "credit_premium",
  "workflow_id": "credit_check",
  "session_id": "user-xyz-789",
  
  "policy_name": "credit_check_strict",
  "policy_version": 1,
  
  "model": "openrouter/anthropic/claude-3.5-sonnet",
  "model_fallback_chain": ["primary->fallback"],
  "tokens_prompt": 1234,
  "tokens_completion": 567,
  "cost_usd": 0.0089,
  "duration_ms": 2345,
  
  "pii_detected": true,
  "pii_entities": ["PERSON", "PHONE"],              // только типы, не значения
  
  "guardrails_input": {"verdict": "safe", "guards_applied": ["nemo:topics", "rebuff"]},
  "guardrails_output": {"verdict": "safe", "guards_applied": ["llama_guard:safe_v3"]},
  
  "prompt_ref": "credit_check.production",
  "prompt_version": 7,
  
  "extra_attrs": {"compliance": "152-FZ"},          // из AIPolicySpec.audit.extra_attrs
  "actor": "user@bank.internal"                     // из AuthN
}
```

### Sink: Unified AuditService

```python
await self._audit.emit(
    event_type="ai.invocation.completed",
    correlation_id=request.correlation_id,
    tenant_id=request.tenant_id,
    payload=event_payload,
)
```

`AuditService` (S17/K3) уже маршрутизирует в ClickHouse через `ClickHouseAuditSink`. Расширения:

1. **Langfuse v3 OTel-exporter** — `LangfuseAuditSink` (новый) — экспортирует `ai.invocation.*` в Langfuse traces через OTel.
2. **PII masking** — все события проходят через `PIITokenizer.mask_irreversible()` ДО записи в любой sink.
3. **Удаление legacy `audit_clickhouse.py`** — миграция через S26 dual-write window.

### Langfuse v3 OTel-exporter

```python
class LangfuseOTelAuditSink(AuditSink):
    """Экспортирует ai.invocation.* как OTel GenAI spans в Langfuse.
    
    Используется существующий OTel SDK (S16 W1).
    """
    async def emit(self, event: AuditEvent) -> None:
        if not event.event_type.startswith("ai.invocation."):
            return  # фильтр: только AI events
        span = tracer.start_span(...)
        span.set_attribute("gen_ai.system", event.model)
        span.set_attribute("gen_ai.usage.prompt_tokens", event.tokens_prompt)
        # ...
        span.end()
```

### Cut-over legacy ClickHouse

- S26 dual-write: `audit_clickhouse.py` + `Unified AuditService` пишут в ClickHouse.
- S27 W5 cut-over: `audit_clickhouse.py` deleted, `Unified AuditService` единственный источник.
- Migration script для existing data: `manage.py audit migrate-legacy`.

## Альтернативы (отвергнуто на этом этапе)

* **Только Langfuse как primary** — потеря compliance audit-trail (Langfuse не immutable, не на-prem ClickHouse).
* **Только ClickHouse** — потеря OTel GenAI cross-tool observability.
* **OpenTelemetry без AuditService** — не закрывает structured event-payload schema (audit-events ≠ traces).
* **Sentry as AI audit sink** — Sentry для exceptions, не для structured events.

## Открытые вопросы (решаются в wave S27 W5)

* **PII в audit** — какой scope masking? `mask_irreversible(ru_strict)` для всех или только для legal/compliance domain?
* **Retention policy** — ClickHouse 90 days vs Langfuse 30 days?
* **Sampling** — для high-volume queries → sample 1% (только metadata, без content)?
* **Streaming events** — `ai.invocation.streaming.chunk` для streaming LLM? Aggregated?
* **Cost attribution** — `cost_usd` per-event или aggregate per-invocation (start+end)?

## Зависимости

* `infrastructure/observability/audit_service.py` — Unified AuditService (S17/K3).
* `core/audit/clickhouse_audit_sink.py` — existing ClickHouse sink.
* `services/ai/gateway/langfuse_callback_v3.py` — Langfuse v3 OTel client (S25 W5).
* `core/security/pii_tokenizer.py::PIITokenizer.mask_irreversible` — для PII в payload.
* `core/ai/gateway.py::AIGateway` — единственный эмитент `ai.invocation.*` событий.
* OTel SDK (S16 W1) — для Langfuse OTel-exporter.

## DoD-критерии scaffold → Accepted

* [ ] 9 типов событий `ai.invocation.*` зарегистрированы в `AuditService` event taxonomy.
* [ ] JSON-Schema для event payload в `services/schema_registry/`.
* [ ] `LangfuseOTelAuditSink` в `infrastructure/observability/sinks/`.
* [ ] PII в audit маскируется через `mask_irreversible()` ДО записи в любой sink.
* [ ] Legacy `audit_clickhouse.py` deleted; dual-write window закрыт.
* [ ] `tests/audit/test_ai_invocation_events.py` — 9 событий emit + verify.
* [ ] ClickHouse query: `SELECT count() FROM audit_events WHERE event_type LIKE 'ai.invocation.%' AND correlation_id = ?` возвращает корректную трассу.
* [ ] Langfuse trace содержит correlation_id + tenant_id + 0 PII raw.
* [ ] `manage.py audit migrate-legacy` migration script.
* [ ] Sphinx page по AI Audit Unified Schema.

## Связи с другими ADR

* **ADR-NEW-S17/K3 Unified AuditService** — основа для расширения.
* **ADR-NEW-3 RequestContext** — correlation_id source.
* **ADR-NEW-19 AIGateway** — единственный эмитент `ai.invocation.*`.
* **ADR-NEW-21 PIITokenizer** — PII masking для audit payload.
* **S16 W1 OTel OTLP metrics** — OTel SDK для Langfuse exporter.
* **ADR-NEW-S22-followup Langfuse PII callback** (S25 W5) — preceding wave.
