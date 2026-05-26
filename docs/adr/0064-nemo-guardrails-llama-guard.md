# ADR-0064 — NeMo Guardrails + Llama Guard 3 defense-in-depth

* Статус: **Proposed** (S29, T11 — GPU-check scaffolding + nemo_client.py)
* Связано с: GAP-2026-05-22 P0-2 (`gap-analysis/AI-GAP-ANALYSIS-gd_integration_tools-2026-05-22.md` Зона 8), PLAN.md V22.3 §S24, ADR-NEW-17.
* Память: [[feedback_gap_analysis_ai_2026_05_22]], [[feedback_wave_k1_security]].

## Контекст

Действующий guardrails-стек:

1. `src/backend/services/ai/guardrails/rebuff_client.py` — async REST Rebuff API (no-op без API-key).
2. `src/backend/services/ai/guardrails/lakera_client.py` — Lakera REST API (требует key).
3. `src/backend/services/ai/guardrails/tenant_config.py` — per-tenant policies.
4. `src/backend/services/ai/eval/suites/safety_classifier.py` — regex PII + harmful-token filter (nightly eval, **не** runtime).
5. `src/backend/services/ai/ai_moderation.py` — общая модерация.

**Не покрыто**:
* Self-hosted jailbreak detection (perplexity-thresholds, Colang DSL).
* Self-hosted output safety classifier для конкретного LLM-вызова.
* Topic filter (banking-specific: «не выдавай инвестиционные советы», «не диагностируй болезни»).
* Defense-in-depth pipeline (input → LLM → output).

**Риск (H)**: prompt injection / jailbreak в банковской среде может вызвать раскрытие внутренних данных, мошеннические инструкции, repuational damage.

## Решение (Draft)

**Внедрить self-hosted defense-in-depth pipeline**:

```text
[Client request]
    ↓
WAF (ADR-0050)
    ↓
NeMo Guardrails INPUT rails (Colang flows: jailbreak detect, topic filter, PII pre-check)
    ↓
LiteLLM router → LLM
    ↓
NeMo Guardrails OUTPUT rails (factuality check, refusal patterns)
    ↓
Llama Guard 3 (self-hosted vLLM/TGI: harmful content classifier)
    ↓
Presidio PII (ADR-NEW-16) — output anonymize
    ↓
Audit log
    ↓
[Response]
```

1. **NeMo Guardrails** (NVIDIA):
   - Colang DSL для conversational flows.
   - Jailbreak detection через perplexity-thresholds.
   - Topic filter per-tenant (banking-specific topic blocks).
   - Input + Output rails раздельно.
2. **Llama Guard 3** weights через HuggingFace:
   - Self-hosted deployment на vLLM или TGI (uses GPU pool).
   - Binary classifier: safe / unsafe + категории (S1..S6 hazards).
   - Применяется на response LLM перед отправкой клиенту.
3. **Сохраняем Rebuff / Lakera как opt-in** для tenant-ов, имеющих API-keys (capability `net.outbound.*.lakera.ai:external` + WAF allowlist).
4. **Per-tenant policy** через `tenant_config.py` расширение — выбор: NeMo+LlamaGuard / + Rebuff / + Lakera / all.

## Альтернативы (отвергнуто на этом этапе)

* **Только Rebuff/Lakera SaaS** — внешние зависимости, latency через WAF, cost.
* **Только Llama Guard без NeMo** — нет Colang DSL для conversational flows, hard-coded в Python.
* **Только regex-extension** — не масштабируется на jailbreak detection.
* **Внешний SaaS NeMo Cloud** — vendor lock + cost + WAF egress.

## Открытые вопросы (решаются в wave S24 W2)

* **GPU deployment Llama Guard 3** — shared inference pool (LiteLLM) vs dedicated vLLM service?
* **Latency budget** — target p95 ≤ 50ms (NeMo) + ≤ 30ms (Llama Guard) = 80ms overhead на каждый LLM-вызов. Приемлемо?
* **Colang flows base library** — какие топики мы блокируем по умолчанию (banking-specific «не давай инвестиционных советов», «не диагностируй медицинские проблемы»)?
* **Fail-closed vs fail-open** — если NeMo/LlamaGuard упали, блокировать запрос или пропускать с alert?
* **Streaming compatibility** — Llama Guard работает на полный response; как deal с streaming generation?

## Зависимости

* `nemoguardrails>=0.10` [ctx7: nemo-guardrails@latest], `colang` syntax.
* `transformers>=4.40` (уже в стеке) + Llama Guard 3 weights (HuggingFace, через HuggingFace Hub login).
* `vllm` или `text-generation-inference` deployment (GPU).
* Capability: `ai.guardrail.evaluate.<tenant>`, `ai.guardrail.policy_read.<tenant>`.

## DoD-критерии scaffold → Accepted

* [ ] PoC NeMo input rails + Llama Guard output на 100 jailbreak-prompts из gold-set (block rate ≥ 95%).
* [ ] Latency bench p95 ≤ 80ms combined.
* [ ] Per-tenant policy через `tenant_config.py`.
* [ ] Fail-closed логика согласована (block + alert at MetricsRegistry).
* [ ] Audit-log каждое block-событие.
* [ ] Capability `ai.guardrail.*` в plugin.toml schema.
* [ ] Sphinx page по defense-in-depth архитектуре.

## Связи с другими ADR

* ADR-0050 (WAF strict) — guardrails работают после WAF.
* ADR-NEW-16 (Presidio + ru NER) — PII последний этап pipeline.
* ADR-NEW-S22-followup (Langfuse PII callback) — каждый guardrail-block логируется в Langfuse.
