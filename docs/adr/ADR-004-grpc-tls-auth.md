# ADR-004: gRPC TLS + AuthInterceptor + MQTT TLS + IMAP STARTTLS

* Статус: accepted
* Дата: 2026-04-21
* Автор: claude
* Связанные фазы: A2 (Security hardening)

## Контекст

Три транспорта приложения работали без транспортного шифрования и/или без
авторизации:

1. **gRPC** — `add_insecure_port(...)`. Допустимо только для unix-socket
   внутри одного namespace; для любого TCP-listener — нарушение PCI DSS и
   152-ФЗ.
2. **MQTT** — `aiomqtt.Client(...)` без `tls_context`. Логин и пароль в
   plain-text на каждом коннекте.
3. **IMAP** — `imaplib.IMAP4` (синхронный) под `asyncio.to_thread`, пароль
   в конфиге в явном виде.

## Решение

### gRPC

- `GRPCSettings` расширен полями `tls_enabled`, `server_cert_path`,
  `server_key_path`, `ca_cert_path`, `require_client_auth`.
- В `grpc_server.serve()` добавлена функция `_load_tls_credentials()` —
  читает PEM-файлы и собирает `ssl_server_credentials`. Поддерживается mTLS.
- `AuthInterceptor` — server-interceptor, проверяет metadata-ключ
  `x-api-key` (или `authorization: Bearer <key>`). Недействительный или
  отсутствующий ключ → `StatusCode.UNAUTHENTICATED` через `context.abort`.
- Для dev/unix-socket TLS остаётся опциональным (warning в логах).

### MQTT

- `MqttSettings` расширен полями `tls_enabled`, `ca_cert_path`,
  `client_cert_path`, `client_key_path`.
- `MqttHandler._build_tls_context()` создаёт `ssl.SSLContext` с
  `check_hostname=True`, `verify_mode=CERT_REQUIRED`. При наличии
  клиентских файлов подключает mTLS через `load_cert_chain`.
- Контекст передаётся в `aiomqtt.Client(tls_context=...)` для subscribe
  и publish единообразно.

### IMAP

- `imaplib` полностью заменён на `aioimaplib` (async).
- `ImapConfig.password_vault_ref: str` — формат `vault:<path>#<key>` —
  пароль резолвится в рантайме через `VaultSecretRefresher.resolve()`.
  Явный `password` оставлен только для dev.
- `ImapConfig.starttls: bool` (default `True`) — STARTTLS enforced на
  plain-порт 143.
- `ssl.create_default_context()` используется и для IMAPS (993), и для
  STARTTLS.

## Альтернативы

- **gRPC через reverse proxy (envoy)** — отвергнуто: proxy не знает про
  metadata-auth нашего приложения.
- **MQTT username/password без TLS** — недопустимо, пароль уходит в
  открытом виде.
- **imaplib + to_thread** — блокирующий I/O в thread-pool, невозможно
  корректно обработать TLS-ошибки и таймауты.

## Последствия

- В prod-окружении `GRPC_TLS_ENABLED=true` обязателен (валидация на старте).
- `aioimaplib` становится hard dependency (больше не optional).
- Переменные `MQTT_TLS_ENABLED`, `MQTT_CA_CERT_PATH` — часть секрет-менеджмента.
- Smoke-проверка: `grpcurl -plaintext localhost:9999 list` → UNAVAILABLE
  в prod-конфиге.
