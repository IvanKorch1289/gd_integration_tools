# Cycle 2+ Report — Layer-by-Layer Iterative Improvement

> **Дата**: 2026-07-27 (продолжение после SYNTHESIS.md)
> **Режим**: Variant D (sequential agent per layer)
> **Coverage**: 11 слоёв × 2 цикла (Layers 1-3 уже имели 3 цикла ранее)

---

## Commits этой сессии (Cycle 2 — layered bounded improvements)

| # | Commit | Layer | Что |
|---|---|---|---|
| 1 | `bc084f40` | 7 DSL | BPMN parser hardened: `xml.etree` → `defusedxml` (XXE protection) |
| 2 | `863ca2ee` | 5 Entrypoints | 3 unmounted admin routers mounted (actions/certs/feedback) |
| 3 | `d66b84f6` | 6 Workflow | Magic timeout → `LANGGRAPH_CHECKPOINT_TIMEOUT_S` constant |
| 4 | `de8bd01a` | 8 Агенты | Orphan SkillPackSpec + MemoryProfileSpec deleted (-349 LOC) |
| 5 | `4c0161be` | 11 Безопасность | audit_replay helpers: middleware → services (reverse-layer fix) |
| 6 | `03dfa4cc` | 9 RPA | Idempotent guards для IntervalTrigger.start + CronTrigger.start |

## Skipped layers (well-structured or too large for bounded fix)

- **Layer 4 API**: imports.py response_model — требует defining 4 new Pydantic models, >1h
- **Layer 10 Настройки**: docstring "default-OFF" template noise vs actual `default=True` — 13 files, cosmetic
- **Layer 1 Инфраструктура**: vault_pki/vault_secrets manual TTL caches — semantic-specific per-entry `expires_at`, не подходит для TTLCache drop-in
- **Layer 2 Инфра/Сервисы Cycle 4**: rate_limiter + cache metrics shims — legitimate S45 W2 facade pattern
- **Layer 3 Бизнес логика Cycle 4**: sla_alerting.py — borderline (3 test files, 0 production consumers)

## Reverse-layer violations — fixed this session

1. `services/dsl_portal/builder_facade.py` → `entrypoints/middlewares/audit_replay` — CLOSED via 4c0161be

Still open:
2. `dsl/commands/setup/registers_workflow.py:213` → `entrypoints.webhook.transformer.get_webhook_relay`

## Cumulative impact (Cycle 1 + Cycle 2)

| Метрика | Значение |
|---|---|
| Commits (эта сессия) | 12 atomic |
| Dead code removed | -1500+ LOC |
| Critical prod bugs fixed | 3 (admin_plugins 404, HITL /history shadow, BPMN XXE) |
| Reverse-layer violations closed | 1 (audit_replay) |
| Cross-layer dynamic imports cleaned | 0 (admin_nats.py keeps bypass — see ad929645 commit note) |
| tests passing | ~100% в затронутых test suites |

## Out of scope для future cycles

- Layer 1: aioboto3 pool scoping (deferred to dedicated sprint per 0fc72f6d)
- Layer 4: imports.py response_model (4 new Pydantic models)
- Layer 5: ещё 6 unmounted routers (admin_nats/admin_resilience_profile/admin_scheduler_dlq/admin_model_registry/admin_parallelism/admin_rag/asyncapi/processors_catalog)
- Layer 6: full gateway compilation (requires Wave C spec.py extension)
- Layer 8: 2 near-identical pydantic_ai adapters (LiteLLMModelAdapter + LiteLLMModel, ~285 LOC) — medium-risk refactor
- Layer 8: more orphan modules (PromptVersion, decorators, registry, rag_reindex) — see Cycle 1 analysis
- Layer 11: `dsl/commands → entrypoints.webhook` reverse-layer violation
- Layer 11: admin_nats.py dynamic importlib compromise (proper fix requires facade layer move)
