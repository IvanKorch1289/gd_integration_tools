# Envelope Encryption — REMOVED (Sprint 226)

**P1-4 (cycle 241/242) — STALE DOC FIX**:

`EnvelopeEncryptionService` (D174) был **REMOVED** в Sprint 226
(аудит 2026-08-18). Текущая PII-токенизация делается через
**Presidio** (`src/backend/core/security/pii_tokenizer.py`,
650 LOC) — см. `pii.md`.

**Причина замены**: EnvelopeEncryptionService был over-engineering
для текущей threat model. Presidio покрывает:
- Email, phone, passport, INN detection
- PII replacement/masking
- Compliance logging

**Migration**:
- Старый код: `EnvelopeEncryptionService.encrypt(plaintext, tenant_id)`
- Новый код: `PIITokenizer.mask(text)` / `GatewayPipeline._apply_input_sanitizers()`

**Дополнительные ресурсы**:
- `docs/security/pii.md` — PII detection (current)
- `src/backend/core/security/pii_tokenizer.py` — implementation
- `src/backend/core/ai/gateway_pipeline_mixin/sanitize_mixin.py` — sanitization gateway
- `docs/audit/ULTRA_RE_AUDIT_2026-08-19.md` — re-audit report
