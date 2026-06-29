# Cert Loading — Comprehensive Onboarding Guide (S171 M20, D254)

> **Назначение**: полный гайд по загрузке SSL-сертификатов в проекте.
> Для нового разработчика + DevOps + интегратора.

## Архитектура cert-store

```
┌─────────────────────────────────────────────────────────┐
│  CertStoreSettings (pydantic-settings, D248)            │
│  ─ backend (5 вариантов)                                │
│  ─ fallback_enabled (auto-wrap в FallbackCertBackend)    │
│  ─ watch_enabled + watch_path (CertFileWatcher, D245)   │
│  ─ hot_cache_ttl, vault_path, mongo_collection          │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  CertStore (high-level API)                              │
│  ─ get(service_id) → CertEntry | None                    │
│  ─ set(service_id, pem) → save through backend          │
│  ─ subscribe_updates(callback) → invalidation chain     │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│  CertBackend (ABC, 5+3 implementations)                  │
│  ─ vault: HashiCorp Vault KV v2 (prod primary)            │
│  ─ postgres: SQL таблица (fallback)                      │
│  ─ mongo: коллекция (alternative primary)                │
│  ─ memory: in-process dict (tests only)                 │
│  ─ consul: Consul KV (alternative)                        │
│  ─ file: .pem/.crt files (dev/edge, D248)               │
│  ─ env_inline: CERT_INLINE_<cert_id> (terminal, D248)  │
│  ─ fallback: chain primary→secondary→tertiary (D248)      │
└─────────────────────────────────────────────────────────┘
```

## 5 production backends — таблица

| Backend | Когда использовать | Плюсы | Минусы |
|---------|-------------------|-------|--------|
| **vault** | Prod primary | Rotation, audit, RBAC | Требует Vault infra |
| **postgres** | Prod fallback | Already deployed, native | Manual rotation |
| **mongo** | Alternative primary | Document-oriented | Требует Mongo |
| **memory** | Tests only | Fast, in-process | Не persistent |
| **consul** | Alternative | KV stores, watches | Consul infra |
| **file** | Dev/edge fallback | Simple, file-based | No versioning |
| **env_inline** | Terminal fallback | Zero infra | Insecure at scale |
| **fallback** | Production chain | Resilience | More code |

## 3 шага для нового разработчика

### Шаг 1: Выбрать backend через YAML

```yaml
# config_profiles/prod.yml
cert_store:
  backend: "vault"          # primary
  fallback_enabled: true     # auto-wrap in FallbackCertBackend
  vault_path: "secret/certs"
  hot_cache_ttl: 300
  expire_warn_days: 30
  watch_enabled: true        # S171 M16 (D245)
  watch_path: "/etc/certs"
```

### Шаг 2: Положить сертификат в хранилище

**Variant A — Vault (prod):**
```python
from src.backend.core.config.cert_store import cert_store_settings
from src.backend.infrastructure.security.cert_store import CertStore

store = CertStore.from_settings(cert_store_settings)
await store.set("skb_api", pem=PEM, expires_at=date(2027, 1, 1))
# → попадает в vault_path/skb_api как KV v2 secret
```

**Variant B — File (dev/edge fallback):**
```bash
# cert_id = filename без расширения
mkdir -p /etc/certs
echo "-----BEGIN CERTIFICATE-----" > /etc/certs/skb_api.pem
# ... содержимое PEM ...
# FileCertBackend прочитает автоматически при get("skb_api")
```

**Variant C — Env inline (terminal fallback):**
```bash
# cert_id → UPPERCASE, "-" / "." → "_"
# skb_api    → CERT_INLINE_SKB_API
# my-service.io → CERT_INLINE_MY_SERVICE_IO
export CERT_INLINE_SKB_API='-----BEGIN CERTIFICATE-----
MIIDXT...
-----END CERTIFICATE-----'
```

### Шаг 3: Production chain (recommended)

```python
# Автоматически через fallback_enabled=True
# Или вручную:
from src.backend.infrastructure.security.cert_store import (
    CertStore, FallbackCertBackend,
)
from src.backend.infrastructure.security.cert_store.backend_file import FileCertBackend
from src.backend.infrastructure.security.cert_store.backend_env import EnvInlineCertBackend
from src.backend.infrastructure.security.cert_store.backend_vault import VaultCertBackend

primary = VaultCertBackend(base_path="secret/certs")
secondary = FileCertBackend(path=Path("/etc/certs"))
tertiary = EnvInlineCertBackend()
backend = FallbackCertBackend(primary=primary, secondary=secondary, tertiary=tertiary)
store = CertStore(backend=backend, settings=cert_store_settings)
# get(): vault → file → env_inline, первое не-None
```

## Формат файлов

- **Только PEM** (BEGIN CERTIFICATE/END CERTIFICATE блок)
- Расширения `.pem` или `.crt` (оба принимаются)
- **`cert_id = filename без расширения`** — `foo.pem` → `cert_id="foo"`
- Права: **владелец только** (`chmod 0o600` после `set()`)

## Env var `CERT_INLINE_<cert_id>`

| cert_id | ENV var |
|---------|---------|
| `skb_api` | `CERT_INLINE_SKB_API` |
| `my-service.io` | `CERT_INLINE_MY_SERVICE_IO` |
| `prod.tls.cert` | `CERT_INLINE_PROD_TLS_CERT` |

Правила транслитерации: `cert_id.upper().replace('-', '_').replace('.', '_')`

**Security warning**: ENV vars попадают в docker inspect / logs.
Используйте только для dev/edge. Production: vault + file.

## Vault auth (hvac, token-based)

```python
# src/backend/infrastructure/security/cert_store/backend_vault.py
# Lazy import hvac; только token из settings
# Path: {vault_path}/{service_id} (KV v2)
# Future: AppRole/K8s auth (D255, M21+)
```

## Fallback chain (D248)

```
vault (primary)
  ↓ miss/error
file (secondary)
  ↓ miss/error
env_inline (tertiary)
  ↓ miss/error
None (logged as warning)
```

`save()`/`set()` делегирует ТОЛЬКО в primary (canonical).
`delete()` пробует удалить во ВСЕХ backends.

## Watcher setup (lifespan startup, D253)

```python
# src/backend/entrypoints/lifespan.py
from contextlib import asynccontextmanager
from src.backend.core.config.cert_store import cert_store_settings
from src.backend.infrastructure.security.cert_store import (
    CertStore, CertFileWatcher,
)


@asynccontextmanager
async def lifespan(app):
    store = CertStore.from_settings(cert_store_settings)
    app.state.cert_store = store

    if cert_store_settings.watch_enabled:
        watcher = CertFileWatcher(
            path=Path(cert_store_settings.watch_path),
            store=store,
        )
        await watcher.start()
        app.state.cert_watcher = watcher

    yield

    if hasattr(app.state, "cert_watcher"):
        await app.state.cert_watcher.stop()
```

## Invalidation pattern (`subscribe_updates`)

```python
# Subscribe на изменения
async def on_cert_updated(cert_id: str, action: str) -> None:
    # Invalidate локальный кэш
    cache.delete(f"cert:{cert_id}")
    # Уведомить другие инстансы через Redis Pub/Sub
    await redis.publish("cert:updated", cert_id)

store.subscribe_updates(on_cert_updated)
```

> **Note**: `subscribe_updates` контракт готов, **Redis Pub/Sub transport impl — DEFER to M21+** (D257).

## Consul backend (D258)

```python
from src.backend.infrastructure.security.cert_store.backend_consul import ConsulCertBackend
# KV v2 в Consul (alternative to Vault)
# Path: {base_path}/{service_id}
# Backend = consul в CertStoreSettings
```

## List expiring + мониторинг

```python
# В CertBackend API:
async def list_expiring(before: datetime) -> list[CertEntry]:
    """Все сертификаты, истекающие до `before`."""

# Admin endpoint (M21+ roadmap):
# GET /api/v1/admin/certs/expiring?days=30
# → JSON список с {cert_id, expires_at, days_remaining}
# → integration с Prometheus alert
```

## Добавление нового backend (extension pattern)

```python
from src.backend.infrastructure.security.cert_store.backend_base import (
    CertBackend, CertEntry,
)

class MyCustomCertBackend(CertBackend):
    """Новый backend — implementation CertBackend ABC."""

    async def get(self, service_id: str) -> CertEntry | None:
        # ... ваша логика
        ...

    async def set(self, service_id: str, pem: str) -> None:
        # ... save to MyCustomStore
        ...

    # + save/history/list_expiring/list_all/delete

# Регистрация через CertStore.from_settings (M21+ plugin pattern)
```

## Production checklist

- ✅ `fallback_enabled=true` в prod YAML
- ✅ `watch_enabled=true` + `watch_path` в prod YAML
- ✅ Watcher запущен в `lifespan.startup` (см. pattern выше)
- ✅ Backend выбран (`vault` для prod, `postgres` для fallback)
- ✅ Graceful shutdown в `lifespan.shutdown` (`watcher.stop()`)
- ✅ Проверка `subscribe_updates` (subscribers получают уведомления)
- ✅ `list_expiring` (admin/alerting)

## Tests

- `tests/unit/infrastructure/security/test_cert_fallback.py` (9 tests) — file/env/fallback
- `tests/unit/infrastructure/security/test_cert_fallback_integration.py` (2 tests) — from_settings
- `tests/unit/infrastructure/security/test_cert_hot_reload.py` (4 tests) — watcher (D245)
- `tests/unit/security/test_cert_store_memory.py` (~234 LOC) — MemoryCertBackend
- `tests/unit/infrastructure/security/cert_store/test_backend_consul.py` (~285 LOC) — Consul
- `tests/integration/security/test_cert_store_integration.py` — Vault через mock hvac

## Refs

- D245 (S171 M16): Cert hot-reload (watchfiles)
- D247 (S171 M16.2): TDD pattern для hot-reload
- D248 (S171 M18): Cert fallback chain (vault→file→env)
- D252 (S171 M20.1): Fallback интеграция в from_settings
- D253 (S171 M20.2): Lifespan startup wiring
- D254 (S171 M20.3): This document (consolidated guide)
