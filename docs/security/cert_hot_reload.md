# Cert Hot-Reload (S171 M16, D245)

## Назначение

Автоматическая перезагрузка TLS-сертификатов при изменении файловой
системы. При добавлении/изменении/удалении `.pem`/`.crt` файла в
директории `cert_watch_path` CertStore автоматически обновляется
+ уведомляет подписчиков через `subscribe_updates`.

## Архитектура

```
┌──────────────────────┐    watchfiles.awatch     ┌────────────────┐
│ cert_watch_path/    │ ───────────────────────► │ CertFileWatcher│
│ *.pem, *.crt        │   (add/modify/delete)   │  (asyncio)     │
└──────────────────────┘                          └───────┬────────┘
                                                         │
                                                         ▼
                                              ┌────────────────────┐
                                              │ CertStore.set/del  │
                                              │ + notify subscribers│
                                              └────────────────────┘
```

## Использование

```python
from pathlib import Path
from src.backend.core.config.cert_store import cert_store_settings
from src.backend.infrastructure.security.cert_store import (
    CertStore,
    CertFileWatcher,
)

# 1. Создать CertStore (lazy — не auto-start watcher)
store = CertStore.from_settings(cert_store_settings)

# 2. Запустить watcher (opt-in через cert_watch_enabled)
if cert_store_settings.watch_enabled:
    watcher = CertFileWatcher(
        path=Path(cert_store_settings.watch_path),
        store=store,
    )
    await watcher.start()  # background task
    # ... приложение работает, добавление .pem → store обновляется ...
    await watcher.stop()  # graceful shutdown
```

## Settings

```python
# src/backend/core/config/cert_store.py
watch_enabled: bool = False  # opt-in (default OFF)
watch_path: str = "/etc/certs"  # default path
```

Environment overrides:
```bash
export CERT_STORE_WATCH_ENABLED=true
export CERT_STORE_WATCH_PATH=/etc/ssl/certs
```

## Backends с hot-reload (5)

| Backend | Hot-reload |
|---------|------------|
| vault | ✅ (Vault KV v2) |
| postgres | ✅ (таблица `certs` + `cert_history`) |
| mongo | ✅ (lazy pymongo) |
| memory | ✅ (in-process dict) |
| consul | ✅ (Consul KV — alternative hot-reload) |

## TDD test coverage (4/4 GREEN)

- `test_instantiates` — watcher создаётся с path + store
- `test_handles_pem_extension` — фильтрация по `.pem`/`.crt`
- `test_on_add_calls_store_set` — событие add → `store.set()`
- `test_on_delete_calls_store_delete` — событие delete → `store.delete()`

## Production checklist

1. ✅ `cert_watch_enabled=true` (через env / config_profiles/prod.yml)
2. ✅ `cert_watch_path` указывает на реальную директорию с сертификатами
3. ✅ Backend выбран (vault — prod, postgres — fallback)
4. ✅ Watcher запущен в `lifespan.startup`
5. ✅ Graceful shutdown в `lifespan.shutdown`
6. ✅ Проверка `subscribe_updates` (subscribers получают уведомления)

## Refs

- D245 (Cert hot-reload opt-in pattern)
- D237 (TDD discipline)
- watchfiles (rust-based, кросс-платформенный)
- Sprint 171 M16 commit `10d2aee`
