# Фаза A2 — Security hardening

* **Статус:** done
* **Приоритет:** P0
* **Связанные ADR:** ADR-003 (CORS), ADR-004 (gRPC TLS + MQTT + IMAP)
* **Зависимости:** A1

## Цель

Закрыть все P0-дыры безопасности, выявленные в baseline-аудите: отсутствие
CORS, gRPC без TLS, MQTT без TLS, IMAP-пароли в конфиге, yaml-loader с
произвольным `getattr`, `git add -A` в Makefile, устаревшие `passlib` и
`async-timeout`, глобальный CircuitBreakerMiddleware.

## Выполнено

### CORS (ADR-003)

- `src/core/config/security.py` — поля `cors_origins`,
  `cors_allow_credentials`, `cors_allow_methods`, `cors_allow_headers`.
  Валидатор `_forbid_wildcard_in_prod` запрещает `"*"` в prod.
- `src/entrypoints/middlewares/setup_middlewares.py` — CORSMiddleware
  добавлен после `ExceptionHandlerMiddleware` как layer-1.

### gRPC TLS + AuthInterceptor (ADR-004)

- `src/core/config/services/queue.py :: GRPCSettings` — поля
  `tls_enabled`, `server_cert_path`, `server_key_path`, `ca_cert_path`,
  `require_client_auth`.
- `src/entrypoints/grpc/grpc_server.py`:
  - `_load_tls_credentials()` — mTLS-ready сборка credentials.
  - `AuthInterceptor` — server-interceptor на `x-api-key`/`Bearer`.
  - `serve()` выбирает `add_secure_port` или `add_insecure_port`
    (последний — warning в логах).

### MQTT mTLS (ADR-004)

- `src/entrypoints/mqtt/mqtt_handler.py :: MqttSettings` — поля
  `tls_enabled`, `ca_cert_path`, `client_cert_path`, `client_key_path`.
- `MqttHandler._build_tls_context()` — CERT_REQUIRED + hostname-check +
  опциональный `load_cert_chain` для mTLS; применяется к `Client()` для
  subscribe и publish.

### IMAP via Vault + aioimaplib (ADR-004)

- `src/entrypoints/email/imap_monitor.py` — полная переписка:
  - `imaplib` → `aioimaplib` (async, без `to_thread`).
  - `ImapConfig.password_vault_ref` — ссылка на Vault, резолвится через
    `VaultSecretRefresher.resolve()`.
  - `ImapConfig.starttls` (default True) — STARTTLS на plain-порт.
  - `_ssl_context()` с `verify_cert`.

### Убран CircuitBreakerMiddleware

- `src/entrypoints/middlewares/circuit_breaker.py` удалён полностью.
- Из `setup_middlewares.py` импорт и регистрация убраны, оставлен
  комментарий с отсылкой к ADR-005 (A4).
- Причина: `@circuit` был декоратором на module-level — один счётчик на
  всё приложение. Любой endpoint, триггеривший ошибку, размыкал CB для
  всех endpoint-ов. Теперь CB применяется per-route на уровне HTTP-клиентов
  (A4, ADR-005).

### YAML loader whitelist

- `src/dsl/yaml_loader.py :: _is_allowed_processor()`:
  - Разрешены только callable методы, объявленные в `RouteBuilder` (или
    миксинах). Приватные и dunder имена заблокированы.
  - Защита от `getattr(builder, '__class__')` и прочих SSRF-like эскалаций
    через декларативный YAML.

### passlib → argon2-cffi

- `src/infrastructure/database/models/users.py`:
  - Удалены `passlib.context.CryptContext` и
    `sqlalchemy_utils.types.PasswordType`.
  - Введён `argon2.PasswordHasher` с OWASP-рекомендованными параметрами
    (`time_cost=3`, `memory_cost=64MiB`, `parallelism=4`).
  - Методы `set_password()` + `verify_password()` — первое хешированием,
    второе с автоматическим re-hash при устаревших параметрах.
- Поле `password` теперь `String(255)` — PHC-format `$argon2id$...`.

### async-timeout → asyncio.timeout

- `src/infrastructure/clients/transport/smtp.py :: _create_connection` —
  `async with asyncio.timeout(...)` вместо `async_timeout.timeout`.

### Makefile safety

- Цель `commit` — `git add -A` заменён на explicit paths (`src/ docs/
  scripts/ tools/ ...`). Опциональные файлы добавляются условно.

### pyproject.toml

- **ADD**: `argon2-cffi ^23.1.0`, `redis ^5.0.0`, `aiomqtt ^2.0.0`,
  `aioimaplib ^1.0.0`, `pyyaml ^6.0.2`, `grpc-interceptor ^0.15.4`.
- **REMOVE**: `psycopg2`, `async-timeout`, `aioboto3`, `passlib`.
- Перемещено: `pyyaml` из dev в main (использовался в runtime
  `yaml_loader.py`).

## Definition of Done

- [x] CORSMiddleware добавлен, `cors_origins` валидирует prod-значения.
- [x] gRPC TLS credentials + AuthInterceptor реализованы.
- [x] MQTT tls_context + mTLS fields.
- [x] IMAP переведён на aioimaplib, пароль через Vault ref.
- [x] `CircuitBreakerMiddleware` удалён полностью.
- [x] YAML loader whitelist защищает от произвольного `getattr`.
- [x] `passlib` удалён, argon2-cffi настроен, миграция в модели.
- [x] `async-timeout` заменён на `asyncio.timeout`.
- [x] Makefile `git add -A` удалён.
- [x] pyproject.toml синхронизирован с планом (ADD/REMOVE).
- [x] ADR-003 + ADR-004 записаны.
- [x] PROGRESS.md / PHASE_STATUS.yml обновлены (A2 → done).
- [x] Коммит `[phase:A2] ...` с упоминанием ADR-003 + ADR-004.

## Как проверить вручную

```bash
# CORS: в prod-env '*' должно падать валидацией
APP_ENV=prod python -c "
from app.core.config.security import SecureSettings
import os; os.environ['SEC_CORS_ORIGINS']='[\"*\"]'
SecureSettings()  # ValidationError
"

# gRPC: без TLS credentials — warning в логе
grep "gRPC сервер запущен без TLS" логи

# IMAP: в конфиге ImapConfig(password_vault_ref='vault:...') — пароль
# не попадает в дампы памяти и дебаг-логи.

# YAML whitelist: spec {'__class__': {}} должен падать с
# 'Unknown or forbidden processor'.
```

## Follow-up

- A3 (DI consolidation) — удалит `service_registry`.
- A4 (Resilience) — перепишет RetryProcessor на tenacity, per-route CB.
