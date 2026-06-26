# Envelope Encryption (S171 M10 P1, D174)

**EnvelopeEncryptionService** — at-rest encryption с per-tenant DEK
(Data Encryption Key) для banking-домена.

## Pattern

```
┌────────────────────┐
│   KEK (master)     │  ← Vault transit engine (prod) / local (dev)
│   Key Encryption   │
└────────┬───────────┘
         │ encrypts DEK
         ▼
┌────────────────────┐    ┌────────────────────┐
│  DEK (per-tenant)  │ →  │   AES-256-GCM      │
│  Data Encryption   │    │   ciphertext       │
└────────────────────┘    └────────────────────┘
```

## Использование

```python
from src.backend.core.security.encryption.envelope import (
    EnvelopeEncryptionService,
)

# Production
svc = EnvelopeEncryptionService(
    kek_source="vault_transit",
    kek_id="banking-prod-kek-2024",
)

# Dev (local)
svc = EnvelopeEncryptionService(
    kek_source="local",
    kek_id="dev-kek-1",
)

# Encrypt
plaintext = b"customer_ssn=123-45-6789"
envelope = svc.encrypt(plaintext, tenant_id="tenant-bank-1")
# → {"ciphertext": "...", "encrypted_dek": "...", "tenant_id": "tenant-bank-1", ...}

# Decrypt
recovered = svc.decrypt(envelope)
assert recovered == plaintext
```

## Properties

- **Tenant isolation**: каждый tenant имеет свой DEK
- **Key rotation**: KEK можно ротировать без расшифровки данных
- **Per-tenant revocation**: удалить DEK = забыть данные
- **AAD (Additional Authenticated Data)**: `tenant_id` используется как AAD
  — ciphertext нельзя переиспользовать между tenants

## Refs

- D174 EnvelopeEncryption pattern
- https://en.wikipedia.org/wiki/Key_encapsulation
