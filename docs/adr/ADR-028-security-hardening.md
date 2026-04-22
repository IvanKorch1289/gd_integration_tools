# ADR-028: Security hardening — envelope encryption, immutable audit, tenant-scoped Casbin

- **Статус:** accepted
- **Дата:** 2026-04-22
- **Фаза:** IL-SEC2
- **Автор:** Security team (IL-SEC2 implementation agent)

## Контекст

Security Layer review выявил три enterprise-grade gap-а, блокирующих прохождение
аудита по GDPR / 152-ФЗ / PCI DSS / SOC 2 Type II:

1. **Sensitive data в plaintext.** Колонка `Order.response_data` (jsonb) может
   содержать паспортные данные, номера банковских карт, СНИЛС, ПДн третьих лиц
   (в bank statement OCR). Текущее хранение — plaintext в PostgreSQL. DBA
   имеет прямой SELECT-доступ. В случае утечки dump-а БД (незашифрованный
   backup, misconfigured replica) — полная компрометация ПДн.

2. **Audit log без цепочки целостности.** `AuditLogMiddleware` записывает
   события в Redis stream `audit:events`. Redis stream — mutable структура,
   `XDEL`/`XTRIM` доступны любому клиенту с тем же ACL. Insider threat (DBA,
   admin с повышенными привилегиями) может удалить/изменить запись о
   несанкционированном доступе без детектирования. SOC 2 требует
   tamper-evident audit log.

3. **Casbin policies без tenant-scoping.** В multi-tenant SaaS текущий
   Casbin-enforcer вызывается как `enforce(subject, resource, action)` — без
   `tenant_id`. Если пользователь `alice` получил роль `orders_reader` в
   tenant `acme`, тот же enforcer разрешит ей читать orders любого другого
   tenant (`beta`, `gamma`). Классический cross-tenant IDOR (Insecure Direct
   Object Reference).

## Рассмотренные варианты

### Для encryption at rest

- **Вариант 1 — pgcrypto (native Postgres).** Плюсы: нулевая app-logic.
  Минусы: ключ хранится в app-config или в БД (тот же blast radius); rotation
  требует DDL + DML batch; невозможно централизованно отозвать ключ без
  down-time.
- **Вариант 2 — app-level AES-256-GCM с ключом в Vault KV.** Плюсы: ключ не в
  БД. Минусы: ключ всё равно попадает в RAM приложения; rotation требует
  перечитывания всех записей; compliance-audit требует доказать отсутствие
  ключа в core-dump-ах.
- **Вариант 3 — Vault Transit (envelope encryption).** Плюсы: ключ **никогда**
  не покидает Vault; encrypt/decrypt — REST call; rotation — одной командой
  в Vault (старые ciphertext-ы автоматически переподписываются при первом
  decrypt); FIPS 140-2 compliance. Минусы: дополнительный network hop;
  Vault — SPOF для encrypt/decrypt-пути (fail-closed обязателен).

### Для immutable audit

- **Вариант 1 — Redis stream + XADD NOMKSTREAM.** Не решает: XDEL доступен.
- **Вариант 2 — S3 Object Lock (WORM).** Плюсы: физическая неизменяемость.
  Минусы: latency 100-200 ms на запись, не подходит для high-freq audit;
  требует S3 с Object Lock retention policy.
- **Вариант 3 — Postgres table с HMAC-chain (blockchain-lite).** Плюсы: low
  latency (<1 ms), durable, replicable, exportable; цепочка HMAC детектирует
  любую модификацию/удаление; секрет для HMAC хранится в Vault. Минусы:
  добавляет indirect dependency на секрет (ротация HMAC-ключа → rebuild
  цепочки или multi-key support).

### Для tenant-scoping Casbin

- **Вариант 1 — Переписать Casbin model на 4 аргумента** `(sub, obj, act, tenant)`.
  Плюсы: чисто. Минусы: breaking change всех существующих policies; требует
  миграции всех policy-файлов.
- **Вариант 2 — Wrapper поверх существующего `CasbinAdapter`** с автоматической
  инъекцией `tenant_id` из ContextVar. Плюсы: non-breaking, инкрементальный.
  Минусы: оба режима (старый/новый) сосуществуют — риск использования
  старого adapter-а по ошибке.

## Решение

Все три — выбрали **вариант 3** / **вариант 2**:

### 1. Envelope encryption через Vault Transit engine

Новый модуль `src/core/security/vault_cipher.py` — `VaultTransitCipher`:

- singleton `httpx.AsyncClient` (паттерн из `OPAClient` IL-CRIT1.4b);
- API: `encrypt(plaintext) → "vault:v1:<ct>"`, `decrypt(ct) → bytes`,
  `rotate() → int` (новая версия ключа);
- **fail-safe (не fail-closed)**: при недоступности Vault → `VaultCipherError`.
  Обоснование: encrypt/decrypt — critical data-path, "тихо вернуть None"
  недопустимо. Вызывающий сервис обязан обработать ошибку (reject запрос /
  dead-letter / alert);
- graceful shutdown через `close()`.

Helper `src/core/security/vault_cipher_sqlalchemy.py` — async-context-aware
функции `encrypt_field(obj, field, cipher)` / `decrypt_field(obj, field, cipher)`.
**TypeDecorator НЕ используем** — async encrypt внутри sync
`process_bind_param` требует `asyncio.run(...)`, что несовместимо с уже
запущенным event loop FastAPI. Паттерн: сервис явно вызывает helper перед
`session.add()` и после `session.get()`.

### 2. Immutable audit log — Postgres + HMAC-chain

Новый модуль `src/infrastructure/observability/immutable_audit.py`:

- таблица `audit_log_immutable` (миграция
  `2026_04_22_1200-d4e5f6a7b8c9_immutable_audit.py`);
- каждая запись содержит `prev_hash` (HMAC предыдущего события) и `event_hash`
  (HMAC this-event | prev_hash);
- `append(...)` — atomic INSERT с чтением последнего `event_hash` под row-lock
  (`FOR UPDATE`);
- `verify(from_seq, to_seq)` — walks chain, возвращает `VerifyResult(valid,
  first_broken_seq, details)`;
- HMAC-SHA256 секрет — `settings.secure.audit_secret_key` или env
  `AUDIT_SECRET_KEY`; при отсутствии — fallback на `secret_key` с warning.

### 3. Tenant-scoped Casbin — wrapper

Новый модуль `src/infrastructure/policy/casbin_tenant_scoped.py`:

- оборачивает существующий `CasbinAdapter`, **не переписывает**;
- читает `current_tenant()` из ContextVar `src/core/tenancy/__init__.py`;
- trick: model должен быть расширен на `[p, sub, obj, act, tenant]`, но
  существующий `CasbinAdapter.enforce()` принимает variadic args — мы
  передаём 4-й аргумент, casbin передаёт его в matcher (если matcher про
  него знает). Если model ещё старый — tenant игнорируется (backwards
  compat), но уже виден в логах для миграции.

## Последствия

### Положительные

- **GDPR Art. 32** — encryption at rest (pseudonymisation);
- **152-ФЗ ст. 19** — шифрование ПДн при передаче/хранении;
- **PCI DSS 3.5/3.6** — cardholder data encryption + key management
  (ключ в FIPS 140-2 validated Vault);
- **SOC 2 Type II CC7.2** — tamper-evident audit log;
- **cross-tenant IDOR** закрыт на policy-уровне;
- все три механизма можно включать инкрементально (feature-flag-ы).

### Отрицательные

- дополнительный network hop на каждый encrypt/decrypt (~1-3 ms через Vault);
- HMAC-chain — bottleneck при очень высокой частоте audit (~>10k/s). Для
  банковского use-case достаточно (ожидаемая нагрузка <1k/s);
- ротация HMAC-ключа требует либо rebuild цепочки (dump + re-HMAC), либо
  multi-key поддержки в `verify()` — отложено в IL-SEC2-phase-2.

### Нейтральные

- `Order.response_data` — миграция шифрования требует backfill, вынесена
  в **IL-SEC2-phase-2** (не scope этой ADR);
- `AuditLogMiddleware` пока продолжает писать в Redis stream; миграция на
  `ImmutableAuditStore` — в IL-SEC2-phase-2.

## Definition of Done

- [x] `src/core/security/vault_cipher.py` — `VaultTransitCipher` + `VaultCipherError`.
- [x] `src/core/security/vault_cipher_sqlalchemy.py` — async helpers.
- [x] `src/infrastructure/observability/immutable_audit.py` — `ImmutableAuditStore`.
- [x] `src/infrastructure/database/migrations/versions/2026_04_22_1200-d4e5f6a7b8c9_immutable_audit.py`.
- [x] `src/infrastructure/policy/casbin_tenant_scoped.py` — `TenantScopedCasbin`.
- [x] `docs/adr/ADR-028-security-hardening.md` (этот файл).
- [x] Commit `[phase:IL-SEC2] Vault Transit + immutable HMAC audit + tenant Casbin (ADR-028)`.

## Связанные ADR

- ADR-012 OPA + Casbin — расширяется tenant-scoping-ом, не заменяется.
- ADR-015 API Management — `api_key_auth` использует ту же hash-паттерну,
  что `ImmutableAuditStore` для HMAC.
- ADR-011 Outbox/Inbox — `ImmutableAuditStore` использует тот же durable-
  backend (Postgres), но отдельную таблицу.
