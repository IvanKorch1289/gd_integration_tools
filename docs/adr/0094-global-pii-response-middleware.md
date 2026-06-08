# ADR-0094: Global PII response middleware (formalize S18 W3 + S-L8-4)

**Date:** 2026-06-08
**Status:** Accepted (S69 W2 — formalize decision, S66 W2 backlog)
**Sprint:** S69
**Deciders:** core/net + core/security team
**Supersedes:** — (formalizes S18 W3 + S-L8-4 + S22 W1 A-07 unification)
**Related:** ADR-0051, pii_masker.py, pii_masking_response.py

## Context

Backlog S66-W2: "Global PII response middleware" (от роевого анализа V22).
Подразумевалось что global PII redaction в HTTP responses отсутствует
или не покрывает все endpoint'ы.

Audit проведён 2026-06-08 — **Global PII response middleware ALREADY
PRODUCTION-READY** (1179 LOC, 6 модулей + DSL processors).

**Components (verified wc -l):**
```
src/backend/entrypoints/middlewares/pii_masking_response.py   154 LOC  (S18 W3, S-L8-4)
src/backend/entrypoints/middlewares/data_masking.py           109 LOC  (S8A legacy, regex)
src/backend/core/security/pii_masker.py                       235 LOC  (unified PIIMasker)
src/backend/core/security/pii_tokenizer.py                    437 LOC  (reversible tokens)
src/backend/infrastructure/observability/pii_filter.py         89 LOC  (logs PII filter)
src/backend/infrastructure/security/pii_streaming.py          155 LOC  (SSE/streaming PII)
Total:                                                        1179 LOC
```

**Plus:**
* `infrastructure/security/presidio_sanitizer.py` (Presidio lib fallback)
* `services/ai/gateway/langfuse_pii_callback.py` (Langfuse integration)
* `services/ai/ai_moderation.py` (PII detection + blocklist)
* `services/ai/eval/suites/safety_classifier.py` (K4 S6 W1, PII/harmful eval)
* DSL processors: `mask_pii.py`, `sanitizepii_processor.py`,
  `restorepii_processor.py`, `pii_mask.py`, `pii_unmask.py`
* `services/ai/pii/` (dedicated PII service module)

## Decision

Признать Global PII response middleware PRODUCTION-READY.
Реализация S18 W3 + S-L8-4 + S22 W1 A-07 (PII Masker Unification) closed.

**Features (verified в pii_masking_response.py):**
* **Feature-flag** `pii_response_middleware_enabled` (default-OFF)
* **Path patterns** — список regex ограничивает применение
* **Content-Type filter** — только `application/json` (не трогает binary)
* **Unified masker** — `default_masker` из `pii_masker.py` (S22 W1 A-07)
  vs legacy regex в `data_masking.py` (S8A deprecated)
* **Recursive** — `mask_dict()` обходит вложенные структуры
* **8 PII types** — jwt/iban/snils/card/passport/email/inn/phone

**Usage:**
```python
from fastapi import FastAPI
from src.backend.entrypoints.middlewares.pii_masking_response import (
    PIIMaskingResponseMiddleware,
)

app = FastAPI()
app.add_middleware(
    PIIMaskingResponseMiddleware,
    path_patterns=[r"^/api/v1/users(/.*)?$", r"^/api/v1/admin/.*$"],
)
```

**Architecture:**
* `pii_masking_response.py` — FastAPI middleware (response phase)
* `pii_masker.py` — unified masker (8 PII types, default patterns)
* `pii_tokenizer.py` — reversible tokens (для round-trip)
* `pii_filter.py` — observability/logs PII filter
* `pii_streaming.py` — SSE/streaming PII redaction
* `presidio_sanitizer.py` — Presidio fallback (advanced detection)

## Consequences

### Positive

* S22 W1 A-07: PII Masker Unification — single source of truth
  (default_masker) вместо N разных regex implementations
* 8 PII types покрыто из коробки (jwt/iban/snils/card/passport/
  email/inn/phone)
* Reversible tokens (pii_tokenizer.py) для round-trip в RAG
  и AI pipeline
* Streaming support (SSE/WebSocket) через pii_streaming.py
* Presidio integration — advanced detection для non-trivial patterns
* DSL processors — declarative PII masking в route.yaml
* Observability: pii_filter.py для logs (PII redaction в логах)
* Langfuse integration: langfuse_pii_callback.py для AI observability

### Negative

* Legacy `data_masking.py` (S8A) ещё существует — НЕ полностью
  мигрирован (S22 W1 A-07 partial)
* Default-OFF feature flag → нужен явный rollout
* Performance: recursive mask_dict может быть медленным для
  очень больших response bodies (no streaming optimization)

### Neutral

* 1179 LOC distributed across 6 модулей — clear separation
* Presidio — external lib (опциональный dep в `[security]` extra)
* DSL processors: 4 шт. (mask, sanitize, restore, agent_dsl)

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| `PIIMaskingResponseMiddleware` | DONE | entrypoints/middlewares/pii_masking_response.py |
| `default_masker` (8 PII types) | DONE | core/security/pii_masker.py |
| `PIIMasker.mask_dict()` (recursive) | DONE | core/security/pii_masker.py |
| `pii_response_middleware_enabled` flag | DONE | core/config/features/security.py |
| `pii_tokenizer.py` (reversible) | DONE | core/security/pii_tokenizer.py |
| `pii_filter.py` (logs redaction) | DONE | infrastructure/observability/pii_filter.py |
| `pii_streaming.py` (SSE/WebSocket) | DONE | infrastructure/security/pii_streaming.py |
| `presidio_sanitizer.py` (advanced) | DONE | infrastructure/security/presidio_sanitizer.py |
| `langfuse_pii_callback.py` (AI obs) | DONE | services/ai/gateway/langfuse_pii_callback.py |
| `ai_moderation.py` (PII+blocklist) | DONE | services/ai/ai_moderation.py |
| `safety_classifier.py` (eval) | DONE | services/ai/eval/suites/safety_classifier.py |
| DSL: `mask_pii.py`, `sanitizepii`, `restorepii` | DONE | dsl/engine/processors/{ai,}/ |
| DSL: `pii_mask.py`, `pii_unmask.py` | DONE | dsl/engine/processors/agent_dsl/ |
| `services/ai/pii/` (dedicated module) | DONE | services/ai/pii/ |
| Migration S8A → unified (S22 W1 A-07) | PARTIAL | data_masking.py (legacy) coexists |
| `pii_response_middleware_enabled` default-ON | TODO | out of scope (S69+ rollout) |
| PII admin UI (Streamlit page) | TODO | out of scope |
| Per-route PII override через DSL | TODO | out of scope (S67 backlog) |

## References

* `src/backend/entrypoints/middlewares/pii_masking_response.py` (154 LOC)
* `src/backend/entrypoints/middlewares/data_masking.py` (109 LOC, legacy S8A)
* `src/backend/core/security/pii_masker.py` (235 LOC)
* `src/backend/core/security/pii_tokenizer.py` (437 LOC)
* `src/backend/infrastructure/observability/pii_filter.py` (89 LOC)
* `src/backend/infrastructure/security/pii_streaming.py` (155 LOC)
* `src/backend/infrastructure/security/presidio_sanitizer.py`
* `src/backend/services/ai/gateway/langfuse_pii_callback.py`
* `src/backend/services/ai/ai_moderation.py`
* `src/backend/dsl/engine/processors/mask_pii.py`
* S18 W3: original middleware sprint
* S-L8-4: backlog item (resolved in S18 W3)
* S22 W1 A-07: PII Masker Unification (KNOW_ISSUES.md)
* ADR-0051 (parent: in-house security primitives)
