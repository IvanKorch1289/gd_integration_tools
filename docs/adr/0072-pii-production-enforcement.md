# ADR-0072 — PII production enforcement (Presidio + Langfuse + RAG ingest + MCP authz + Policy gate)

* Статус: **Accepted** (2026-05-22, Phase A Block 1 closure).
* Связано с: ADR-0063 (Presidio + ru NER, Accepted после S24 W1), ADR-0066 (AI Gateway facade), ADR-0070 (MCP namespaces), PLAN.md V22.4 §S25-S27, директива пользователя 2026-05-22 (10 блоков AI-доработок).
* Память: [[feedback_sprint24_w1_presidio]], [[feedback_gap_analysis_ai_2026_05_22]], [[feedback_plan_v22_4_ai_platform]].

## Контекст

После S24 W1 closure (commits `33e1f280` / `4d9621b3` / `8070067d` / `f274ae71`) PresidioSanitizerAdapter, AsyncPIISanitizerProtocol, capability vocabulary `pii.{read,write,audit}` и DI-провайдер switch уже реализованы. Однако осталось 5 critical gap'ов перед production rollout (директива 2026-05-22, Phase A Block 1):

1. **prod.yml не активирует Presidio** — `feature_flags.presidio_pii_enabled` default-OFF. AIDataSanitizer (regex, 8 паттернов) остаётся primary, ru NER не подключён → compliance-риск (152-ФЗ).
2. **Langfuse traces содержат raw PII** — `LangFuseCostCallback` отправляет `messages` + `output` без анонимизации. Langfuse SaaS UI хранит данные клиентов в plain.
3. **RAG ingest сохраняет PII** — `RAGIngestService._build_chunk_metadata` пишет `chunk_text` в Qdrant без маскирования. Retrieval возвращает unmasked context в LLM-prompt.
4. **MCP tools без per-tool authz** — `mcp_server.py` регистрирует все Tier 1+2 actions для всех клиентов. Tenant isolation отсутствует.
5. **AIAgentService без policy gate** — `chat()` вызывается без AuthorizationGateway.check(tenant_id, resource="ai:llm", action="call").

Compliance-impact:
- 152-ФЗ "О персональных данных" — утечка через Langfuse / RAG / MCP.
- Internal AI policy — каждый LLM-вызов должен иметь explicit per-tenant authz.

## Решение

**Включить 5 production-enforcement gates как блокирующие для prod-config**:

### 1.1 Presidio в prod (DONE this ADR)

- `config_profiles/prod.yml::features.presidio_pii_enabled: true`.
- Prometheus counter `presidio_fallback_total{reason}` для алертов на utratu NER-покрытия.
- Алерт: `rate(presidio_fallback_total[5m]) > 0` в prod → page on-call.
- Fallback стратегия: Presidio ImportError / init_error → legacy AIDataSanitizer (regex) + counter inc.

### 1.2 Langfuse traces sanitize (NEXT)

- `LangFuseSettings.sanitize_traces: bool = True` (default-ON, single source of truth).
- `LangFuseCostCallback.__call__` обёртывает `messages`/`output`/`metadata` через `anonymize_trace_payload` (уже существует — см. `langfuse_pii_callback.py`).
- Аналогично `LangFuseCallbackV3.__call__` для SDK 3.x ветки.
- Audit event `pii.anonymized{source=langfuse}` на каждый replacement.

### 1.3 RAG ingest masking (NEXT)

- `RagIngestSettings.pii_mask_on_ingest: bool = False` (default-OFF в base, ON в staging/prod).
- `RAGIngestService` маскирует `chunk.text` через `get_ai_sanitizer_provider()` до записи в Qdrant.
- `chunk.metadata.pii_masked: bool` + `chunk.metadata.pii_masker_version: str` для retrieval-side проверки.
- Replacements `mapping` НЕ сохраняется в Qdrant (one-way anonymize — restore не предполагается на retrieval).

### 1.4 MCP per-tool authz (NEXT)

- `McpSettings.tool_authz_enabled: bool = False` (default-OFF, ON в staging/prod).
- `mcp_server._register_single_tool` обёртывает handler через `CapabilityGate.check(caller, f"mcp.tool.{action_name}")`.
- `list_tools` фильтрует по `tenant_id` (из MCP session context). Без tenant_id → public tools only.
- Audit event `mcp.tool.denied{action, tenant}` на любой блок.
- Связь с ADR-0070 (namespace prefix `<domain>.<action>`).

### 1.5 Policy gate для AIAgentService (NEXT)

- `AIAgentSettings.policy_gate_enabled: bool = False` (default-OFF, ON в dev/staging/prod).
- `AIAgentService.chat()` первый шаг: `await AuthorizationGateway.check(tenant_id, resource="ai:llm", action="call", attrs={"model": ..., "route": ...})`.
- **Fail-closed**: AuthorizationGateway unavailable → deny + audit event `ai.llm.policy.gate.unavailable`. Никогда `allow on error`.
- Связь с ADR-NEW-19 (AI Gateway facade) — этот gate станет частью `AIGateway.invoke()` pipeline в S25.

## Альтернативы (отвергнуто)

* **Включить через ENV только** (без YAML) — переменные окружения теряются при k8s ConfigMap reload; YAML profile + ENV override (приоритет ENV) даёт оба способа.
* **Single `pii_strict_mode` master flag** — слишком coarse-grained; разные failure modes требуют точечного контроля (например, Langfuse off, но Presidio on на dev_light для отладки).
* **Sync-only enforcement** — async path (RAG retrieval, multi-agent) требует AsyncPIISanitizerProtocol (уже в `core/interfaces/sanitization.py`).

## Verification

### CI gates

```bash
# 1.1 — Presidio active
FEATURE_PRESIDIO_PII_ENABLED=true pytest tests/integration/ai/test_presidio_active.py -v

# 1.2 — Langfuse sanitize
pytest tests/unit/services/ai/gateway/test_langfuse_payload_no_pii.py -v

# 1.3 — RAG ingest mask
FEATURE_PRESIDIO_PII_ENABLED=true RAG_INGEST_PII_MASK_ON_INGEST=true \
  pytest tests/unit/services/ai/test_rag_pii_mask.py -v

# 1.4 — MCP authz
MCP_TOOL_AUTHZ_ENABLED=true pytest tests/integration/test_mcp_tool_authz.py -v

# 1.5 — Policy gate
FEATURE_AI_AGENT_POLICY_GATE=true pytest tests/unit/services/ai/test_ai_agent_policy_gate.py -v
```

### Production monitoring

- `presidio_fallback_total{reason}` — Prometheus alert: `rate > 0` per 5m в prod → page.
- `pii_anonymized_total{source}` (Langfuse / RAG / MCP) — observability dashboard.
- `mcp_tool_denied_total{action, tenant}` — security audit dashboard.
- `ai_policy_gate_denied_total{tenant, reason}` — compliance dashboard.

## Migration

Phase A (этот ADR) — Blocks 1.1, 1.2, 1.3, 1.4, 1.5 + 2.1, 2.2, 2.3 (Block 2 параллельно).

Sequence:
1. `feat(ai): [K4] PII hardening — Presidio enabled in prod (#gap-ai-1.1)` — этот ADR.
2. `feat(ai): [K4] PII hardening — Langfuse trace sanitization (#gap-ai-1.2)`.
3. `feat(ai): [K4] PII hardening — RAG ingest PII masking (#gap-ai-1.3)`.
4. `feat(ai): [K4] PII hardening — MCP per-tool authz (#gap-ai-1.4)`.
5. `feat(ai): [K4] PII hardening — AIAgentService policy gate (#gap-ai-1.5)`.

Block 2 (Agent layer) идёт параллельно — Blocks 2.1/2.2/2.3 не зависят от Block 1 acquisition order.

## Consequences

### Positive

- 152-ФЗ compliance gap закрыт для prod-rollout.
- Langfuse SaaS не содержит plain PII клиентов банка.
- MCP tools имеют per-tenant authz из коробки.
- AI policy gate унифицирует authz через AuthorizationGateway (V22 backbone).
- Все 5 gates default-OFF в `base.yml` → dev_light/dev/staging обратно совместимы.

### Negative

- Latency overhead Presidio: +20–50ms p95 на 4kb текста (carryover S24 perf wave).
- Langfuse trace volume +5–10% (audit events `pii.anonymized` через structured log).
- Qdrant storage не растёт значимо (metadata booleans).
- MCP — `tool_authz_enabled=True` сломает клиентов без tenant_id в session — миграция тестируется в staging до prod-flip.

### Carryover

- ADR-0078 Guardrail Enforcer (Phase C Block 7) — PromptInjectionScanner + Toxic + Cost.
- ADR-0079 OTel GenAI conventions (Phase E Block 8.1) — `gen_ai.*` атрибуты на каждом LLM-span.
- Sphinx page `docs/source/ai/pii_layer.md` — carryover S24/S27.

## Связи с другими ADR

* ADR-0063 — Presidio + ru NER (Accepted; этот ADR enforce'ит).
* ADR-0064 — NeMo Guardrails + Llama Guard 3 (Draft; defense-in-depth, Phase C).
* ADR-0066 — AI Gateway facade (Accepted; AIAgentService policy gate станет частью).
* ADR-0067 — AI Policy Spec DSL (Draft; PolicyResolver на стороне gate).
* ADR-0068 — PIITokenizer reversible (Draft; вариант для финансовых use-cases).
* ADR-0070 — MCP gateway namespaces (Accepted; namespace-prefix для tool authz).
* ADR-0050 — WAF strict single-entry — PII layer работает после WAF.
