# M-C: Per-Tenant Cryptographic Isolation (revert path)

> **Status**: 🟡 BACKLOG (post-V22).
> **Source**: PLAN.md V22 §S18 W14 (ADR-NEW-9 / B-6).
> **Decision date**: 2026-05-25 (M-B scope reduction landed).

## Контекст

V22 закрепляет multi-tenancy на уровне **M-B (Multi-BU одного банка)**:

- `TenantContext` остаётся источником `tenant_id` для audit/RLS/cache.
- Разграничение между BU реализуется через:
  - `TenantContextMiddleware` + ACL в коде;
  - per-BU rate-limit (S18 K5 W1 — `multi_tenant_rate_limit_enabled`);
  - per-BU Casbin/OPA policies (S17 ADR-NEW-1 chain + S18 K1 W3);
  - audit `tenant_id` label во всех metrics (S17 W11 DEFAULT_LABELS).
- Per-tenant **cryptographic** isolation (отдельный KMS-ключ на BU,
  encryption-at-rest with per-tenant DEK) — **НЕ реализуется** в V22.

## Что было исключено в V22

- `infrastructure/security/tenant_encryption.py` — **никогда не создавалась**
  как production-ready реализация; задача отложена до M-C use case.
- IDS-per-tenant (отдельные detection rules per BU) — общий SIEM через
  Graylog считается достаточным для M-B scope.

## Когда переходить на M-C

Триггеры:

1. Compliance-требование (152-ФЗ Класс защиты КЗ-1 или ПДн-2/-1) для
   конкретного BU требует cryptographic separation.
2. Бизнес-заказчик подписывает SLA с per-tenant KMS-ключом.
3. Внешний аудит фиксирует риск insider-threat при общем DEK.

## Архитектурный план M-C (для будущей wave)

1. **Per-tenant DEK через Vault Transit**:
   - `infrastructure/security/tenant_kms.py::TenantKMSAdapter`.
   - Vault path `transit/keys/tenant/<tenant_id>`.
   - DEK rotation N дней (configurable per tenant).

2. **Транспарентное шифрование на уровне DB**:
   - PostgreSQL: pgcrypto + tenant-aware DEK wrapper.
   - Application-level: SQLAlchemy event listener для encrypted columns.

3. **Key management**:
   - Tenant onboarding workflow → KMS key provisioning.
   - Tenant offboarding → ключ архивируется (не удаляется N лет per
     compliance).

4. **Cost model**:
   - +N% overhead на storage (encrypted columns).
   - KMS-calls billing (per encrypt/decrypt operation).

## Зависимости

- ADR-NEW-12 RLS Strategy (S21 K1 W1) — фундамент для DB-level isolation.
- Vault Transit setup (ops infra).
- Compliance review (152-ФЗ КЗ-1 mapping).

## Reverting M-B → M-C migration path

1. Re-enable `tenant_encryption_enabled` feature-flag (создать в S21 W1).
2. Lifespan-bootstrap: TenantKMSAdapter init после Vault.
3. Alembic migration: add `encryption_key_version` column на tenant-aware tables.
4. Backfill: для existing rows — encrypt с tenant DEK lazy при first read.
5. Validation: chaos-test cross-tenant data access denied at DB level.
