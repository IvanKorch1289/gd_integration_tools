# ADR-0066 — AIGateway — единая точка входа в AI

* Статус: **Accepted** (S29 T9, 2026-05-26 — ModelRouter LiteLLM fallback chain + E2E tests)
* Связано с: `gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 1 (orchestration consolidation), PLAN.md V22.4 §S25, ADR-NEW-19.
* Память: [[feedback_gap_analysis_ai_2026_05_22]], [[feedback_v11_manifest_design]].

## Контекст

В проекте действуют **3 параллельных кодопути LLM-вызовов**:

1. `src/backend/services/ai/ai_graph.py` — LangGraph ReAct (multi-step reasoning).
2. `src/backend/services/ai/agents_pydantic/base.py` — PydanticAI 0.5 (type-safe tools).
3. `src/backend/services/ai/ai_agent.py` — ручной fallback chain (Perplexity → HF → OpenWebUI).

Каждый путь **самостоятельно** решает:
- маскировать ли PII (`PIIMasker` опционально);
- применять ли guardrails (`Rebuff`/`Lakera` опционально);
- логировать ли в Langfuse (`v2 callback` опционально);
- считать ли cost-budget (`budget_facade.py` опционально);
- проверять ли capability (`CapabilityGate` опционально).

**Проблема**: невозможно гарантировать defense-in-depth — слой защиты опционален, разработчик нового LLM-вызова может пропустить любой из них; нет audit-trail единой схемы; дублирование retry/cost-логики между 3 файлами.

**ADR-NEW-1 AuthorizationGateway** уже принят и работает по паттерну «единый фасад с обязательным pipeline». Тот же паттерн нужен для AI.

## Решение (Draft)

**`AIGateway`** — единственная точка входа в LLM-вызов, по аналогии с `OutboundHttpClient` для HTTP и `AuthorizationGateway` для auth.

### Pipeline (9 шагов)

```python
class AIGateway:
    async def invoke(self, request: AIRequest) -> AIResponse:
        # 1. PolicyResolver → AIPolicySpec (workflow_id + tenant_id)
        policy = await self._policy_resolver.resolve(
            workflow_id=request.workflow_id,
            tenant_id=request.tenant_id,
        )
        # 2. CapabilityGate intercept: `ai.invoke.<workflow_id>`
        await self._capability_gate.check(
            f"ai.invoke.{request.workflow_id}", tenant=request.tenant_id,
        )
        # 3. Input sanitizers (PII через PIITokenizer)
        sanitized_input = await self._apply_sanitizers(
            request.prompt, policy.input_sanitizers,
        )
        # 4. Input guards (NeMo Colang + Rebuff/Lakera)
        await self._apply_guards(sanitized_input, policy.input_guards, stage="input")
        # 5. PromptRenderer (Langfuse PromptRegistry + tiktoken trim)
        rendered = await self._prompt_renderer.render(
            request.prompt_ref, request.context, budget=policy.budget,
        )
        # 6. ModelRouter (LiteLLM primary + fallback chain)
        completion = await self._model_router.invoke(
            rendered, model=policy.model_router, stream=request.stream,
        )
        # 7. Output guards (Llama Guard 3)
        await self._apply_guards(completion, policy.output_guards, stage="output")
        # 8. Output sanitizers (Presidio + JSONSchema через Outlines)
        sanitized_output = await self._apply_sanitizers(
            completion, policy.output_sanitizers,
        )
        # 9. Audit + Cost (через AuditService + Langfuse v3 OTel)
        await self._audit.emit("ai.invocation.completed", ...)
        await self._cost_tracker.track(policy.model_router.primary, ...)
        return AIResponse(content=sanitized_output, ...)
```

### Dataclasses

```python
@dataclass(frozen=True, slots=True)
class AIRequest:
    workflow_id: str                  # "credit_check"
    tenant_id: str                    # из RequestContext
    correlation_id: str               # из RequestContext (ADR-NEW-3)
    prompt_ref: str | None            # Langfuse PromptRegistry ref
    prompt_inline: str | None         # альтернатива prompt_ref (deprecated path)
    context: dict[str, Any]           # вводные для template
    stream: bool = False

@dataclass(frozen=True, slots=True)
class AIResponse:
    content: str
    structured: Any | None            # Pydantic-модель (Instructor/Outlines)
    tokens_prompt: int
    tokens_completion: int
    cost_usd: float
    model_used: str                   # фактическая модель fallback chain
    pii_detected: bool
    guardrails_verdict: dict[str, str]  # {"input": "safe", "output": "safe"}
```

### Feature-flag и обратная совместимость

- **`AI_GATEWAY_ENFORCE`** default-OFF (S25 W0 backbone).
- При OFF: scaffold-pass-through (вызов через `_legacy_invoke()`).
- При ON (S27 closure): 100% LLM-вызовов через `AIGateway`.
- 3 existing кодопути **обёрнуты** в S25 W3, не переписаны.

### CI-gate

`tools/checks/check_ai_gateway_coverage.py` (AST-checker, по шаблону `check_grep_violations.py`):
- ищет прямые вызовы `litellm.completion()`, `client.chat.completions.create()`, `agent.run()`, `Agent.run()`;
- exit 0 если все обёрнуты;
- warn-only первый месяц → strict в S27 closure.

## Альтернативы (отвергнуто на этом этапе)

* **DI-injection** `LLMService` без фасада — не закрывает 3 кодопути одинаково (каждый решает что вызвать).
* **Middleware-only** (без явного AIGateway-класса) — нарушает ADR-NEW-1 паттерн.
* **Plugin-pattern** (Composio-стиль) — слишком расширяемо, не подходит для core защитного слоя.

## Открытые вопросы (решаются в wave S25 W1)

* **Streaming** — `stream=True` → как применить output guards (Llama Guard) к streaming? Buffered chunks с window?
* **PydanticAI 0.5 → 1.85 upgrade** — отдельная wave перед S25 W3 или включить в W3 adapter-wrap?
* **Sync compatibility** — `AIGateway.invoke()` async-only? Существуют ли sync-вызывающие места (manage.py CLI)?
* **Budget enforcement** — hard limit (raise BudgetExceeded) или soft (warn + truncate)?

## Зависимости

* `core/plugin_runtime/capability_gate.py` — capability `ai.invoke.<workflow_id>`.
* `core/ai/policy/spec.py::AIPolicySpec` — ADR-NEW-20 (S25 W2).
* `core/security/pii_tokenizer.py::PIITokenizer` — ADR-NEW-21 (S25 W4).
* `services/ai/prompt_registry.py` — Langfuse PromptRegistry (S26 W2 расширение).
* `services/ai/gateway/client.py` — LiteLLM ModelRouter (существующий низкоуровневый).
* `infrastructure/observability/audit_service.py` — Unified AuditService (S17/K3).
* `services/ai/gateway/langfuse_callback_v3.py` — OTel GenAI (S25 W5 upgrade).

## DoD-критерии scaffold → Accepted

* [ ] `core/ai/gateway.py::AIGateway` создан с 9-step pipeline (pass-through scaffold).
* [ ] `AIRequest`/`AIResponse` dataclass.
* [ ] Feature-flag `AI_GATEWAY_ENFORCE` default-OFF в `core/config/ai.py`.
* [ ] Capability `ai.invoke.<workflow>` зарегистрирована в schema.
* [ ] `tests/unit/core/ai/test_gateway_pipeline.py` — smoke pass-through + 9 steps order verification.
* [ ] `tools/checks/check_ai_gateway_coverage.py` AST-checker scaffold (warn-only mode).
* [ ] Makefile target `ai-gateway-coverage`.
* [ ] 3 кодопути обёрнуты в S25 W3 (regress-free golden-snapshot).
* [ ] AIGateway включён ON в production config (S27 closure DoD).
* [ ] Sphinx page по AI Platform architecture.

## Связи с другими ADR

* **ADR-NEW-1 AuthorizationGateway** — pattern reuse (единый фасад с обязательным pipeline).
* **ADR-NEW-3 RequestContext** — `correlation_id`/`tenant_id` обязательны в `AIRequest`.
* **ADR-0050 WAF strict single-entry** — паттерн `OutboundHttpClient` для HTTP — то же для AI.
* **ADR-NEW-20 AIPolicySpec** (S25 W2) — основа для policy_resolve.
* **ADR-NEW-21 PIITokenizer** (S25 W4) — основа для input/output sanitizers.
* **ADR-NEW-22 SkillRegistry V11.2** (S26 W5) — skill_invoke через AIGateway.
* **ADR-NEW-24 AI Audit Unified** (S27 W5) — `ai.invocation.*` события из AIGateway.
* **ADR-NEW-S22-followup Langfuse PII callback** (S25 W5) — последний шаг pipeline.
