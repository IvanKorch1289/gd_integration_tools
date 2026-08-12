# Аудит домена: Security (Cycle 1 / Phase 1)

**Дата:** 2026-08-06
**HEAD:** `2f620910951a727f50d4539b998375b0c0bda55d` (S183 W2 #1, S3 multipart abort)
**Baseline:** `b69d6b49bc62918a02e47dc20ab81615fd8500b1` (B-22 DLQ migration)
**Scope (как задан):**
`src/backend/core/security/**`, `src/backend/core/auth/**`,
`src/backend/services/security/**`, `src/backend/services/auth/**`,
`src/backend/services/authorization/**`, `src/backend/services/agent_security/**`,
`src/backend/entrypoints/middlewares/*security*.py`,
`src/backend/entrypoints/middlewares/*auth*.py`,
`ai_policies/**`,
`tests/security/**`, `tests/auth/**`
**Автор:** Независимый аналитик (cycle-1 phase-1)

---

## 1. Scope / Что проверено / Что НЕ проверено

### 1.1 Проверено (с прямым evidence)

| Объект | Команда/чтение | Статус |
|---|---|---|
| `src/backend/core/security/authorization_gateway/` (9 файлов) | `Read` всех файлов | Проверено |
| `src/backend/core/security/capabilities/` (11 файлов) | `Read` всех файлов | Проверено |
| `src/backend/core/security/pii_masker.py` (271 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/pii_tokenizer.py` (464 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/pii_patterns.py` (52 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/connector_auth.py` (220 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/activity_capability_guard.py` (263 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/credential_provider.py` (206 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/secret_rotation.py` (279 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/ip_restriction_store.py` (213 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/module_whitelist.py` (60 строк) | `Read` всего файла | Проверено |
| `src/backend/core/security/__init__.py` (12 строк) | `Read` | Проверено |
| `src/backend/core/auth/` (16 файлов) | `Read` всех файлов | Проверено |
| `src/backend/core/auth/saml/sp_handler.py` (вспомогательно) | `Read` | Проверено |
| `src/backend/services/security/facade.py` (408 строк) | `Read` всего файла | Проверено |
| `src/backend/services/security/cert_store_facade.py` (21 строк) | `Read` | Проверено |
| `src/backend/services/security/pii_streaming_facade.py` (21 строк) | `Read` | Проверено |
| `src/backend/services/security/__init__.py` (22 строк) | `Read` | Проверено |
| `src/backend/services/auth/__init__.py` (32 строк) | `Read` | Проверено |
| `src/backend/services/auth/ad_directory_client/` (3 файла) | `Read` всех | Проверено |
| `src/backend/services/authorization/facade.py` (550 строк) | `Read` всего файла | Проверено |
| `src/backend/services/agent_security/facade.py` (188 строк) | `Read` всего файла | Проверено |
| `src/backend/entrypoints/middlewares/security_headers.py` (110 строк) | `Read` | Проверено |
| `src/backend/entrypoints/middlewares/auth_required.py` (199 строк) | `Read` | Проверено |
| `src/backend/entrypoints/middlewares/auth_method_header.py` (126 строк) | `Read` | Проверено |
| `src/backend/entrypoints/api/dependencies/auth_selector.py` (55 строк, deprecated shim) | `Read` | Проверено |
| `src/backend/infrastructure/policy/opa/client.py` (120 строк) | `Read` | Проверено |
| `src/backend/infrastructure/policy/opa/policies/authz_default.rego` (51 строк) | `Read` | Проверено |
| `src/backend/plugins/composition/di.py` (строки 140–200, policy wiring) | `Read` | Проверено |
| `ai_policies/agent_basic.policy.yaml` (77 строк) | `Read` | Проверено |
| `ai_policies/rag_default.policy.yaml` (62 строк) | `Read` | Проверено |
| `ai_policies/credit_check_strict.policy.yaml` (94 строк) | `Read` | Проверено |
| `tests/security/` (4 файла, 561 LOC) | `Read` всех | Проверено |
| `tests/security/pii/test_streaming.py` (181 строк) | `Read` | Проверено |
| `tests/auth/mtls/test_mtls_fixture_smoke.py` (93 строк) | `Read` | Проверено |
| `tests/auth/saml/test_e2e_matrix.py` (179 строк) | `Read` | Проверено |
| `tests/unit/core/security/test_authorization_gateway_steps.py` (240 строк) | `Read` | Проверено |
| `tests/integration/test_opa_runtime_cycle37.py` (488 строк) | `Read` | Проверено |
| `.security/pip-audit-allowlist.txt` (79 строк, 35 active CVE/GHSA/PYSEC IDs) | `cat` + `grep -c` | Проверено |
| `pyproject.toml` (security-секции + extras) | `grep -E` по `argon2|joserfc|hvac|ldap3|python3-saml|cachetools|presidio|casbin` | Проверено |
| `src/backend/entrypoints/mcp/auth_middleware.py` (120 строк) | `Read` | Проверено |

**Метрики scope:**
- 72 .py файла в scope-коде, итого **11 291 LOC** (`find … -exec wc -l`)
- 11 .py файлов в тестах scope, итого **852 LOC**
- `src/backend/core/security/capabilities/vocabulary/defaults.py` — **522 LOC**, 47 вызовов `vocab.register(...)` (зарегистрировано 47 capability-defs + их aliases)
- `src/backend/services/security/facade.py` — 408 LOC
- `src/backend/services/authorization/facade.py` — 550 LOC

### 1.2 НЕ проверено (по правилам задачи)

| Объект | Причина |
|---|---|
| `src/backend/infrastructure/auth/` (отдельная ветка) | Вне scope (задан строго) |
| `src/backend/infrastructure/security/` (кроме `policy/opa/`) | Вне scope |
| `src/backend/services/ai/pii/presidio_analyzer.py` | Вне scope |
| `src/backend/entrypoints/api/v1/endpoints/admin*.py` | Вне scope |
| Sprint-планы, ADR, KNOWN_ISSUES, DEEP_AUDIT_REPORT | Запрещено правилами |
| Другие отчёты агентов в этом цикле (`01-infrastructure.md`, `03-services.md`, …) | Запрещено правилами |
| Реальный запуск pytest (runtime-тесты) | Не запрашивалось; только статический code-review |

---

## 2. Verified Strengths (что реально работает)

### 2.1 AuthorizationGateway — 4 mixin-декомпозиция + fail-closed chain
**Evidence:** `src/backend/core/security/authorization_gateway/__init__.py:94`
- 4 mixin-класса: `AuditMixin, CasbinMixin, OpaMixin, PermissionMixin`
- 2-level policy chain: `capability_gateway.check()` (обязательно) → optional policies (Casbin/OPA/Permission) с short-circuit на deny
- **B-01/B-03 fix (cycle 33)**: fail-open → deny-by-default при падении feature-flag service (`_is_enabled` теперь ERROR-логирует + возвращает `True` чтобы прошёл deny-by-default chain, см. строки 386–408)
- Prometheus counter `authz_check_engine_failed_total{engine="casbin"|"opa"}` для engine-failure visibility (строки 65–69)

### 2.2 OPA runtime integration — fully wired
**Evidence:**
- `src/backend/core/security/authorization_gateway/opa_mixin.py` — фабрика `opa_step(opa_client, policy_name)`
- `src/backend/core/security/authorization_gateway/policies/opa_policy_decider.py` — composition-root wrapper `build_opa_policy_decider`
- `src/backend/infrastructure/policy/opa/client.py` — `OPAClient.query()` через `httpx.AsyncClient` singleton (IL-CRIT1.4b fix), HTTP/2 + connection pool, **deny-by-default при network-failure** (строки 96–120)
- `src/backend/infrastructure/policy/opa/policies/authz_default.rego` — reference scaffold с `default allow := false` (fail-closed, строка 38)
- `src/backend/plugins/composition/di.py:158–195` — composition root создаёт оба policy-engine, **B-20 fix (cycle 38)** поднимает `ProductionWiringError` если `engine_enabled=True` но нет ни OPA, ни Casbin (строки 142–157)
- `src/backend/core/config/features/sprints_18_21.py:149` — feature-flag `opa_runtime_query_enabled` (off by default, плавная миграция)
- Тесты: `tests/unit/core/security/test_authorization_gateway_steps.py:130–181` (4 кейса: flag-off, allow, deny-with-reasons, fail-closed при ConnectionError) + `tests/integration/test_opa_runtime_cycle37.py` (488 строк)
- OPA runtime-контракт: `input_doc = {principal, resource, action, tenant_id, correlation_id}` (`opa_mixin.py:73–79`) — все 5 полей проверены unit-тестом (`test_authorization_gateway_steps.py:152–160`)

**Вывод:** OPA runtime integration с DSL/auth guards — **реально работает**, fail-closed, observability есть, тесты покрывают основные сценарии.

### 2.3 SAML replay-defence (in-memory InResponseTo tracking)
**Evidence:** `src/backend/core/auth/saml_backend.py:114–213`
- `SamlBackend._issued: dict[str, float]` — request_id → issued_at
- `process_saml_response` сначала `pop` request_id (одноразовость), затем проверка expiry `replay_window_seconds`
- Тест: `tests/auth/saml/test_e2e_matrix.py:142–155` (`test_replay_defence_blocks_reuse_of_request_id`)

### 2.4 Argon2id API key hashing + backward-compat SHA-256 fallback
**Evidence:** `src/backend/core/auth/api_key_backend.py`
- `enable_argon2=True` (default) → Argon2id PHC с `time_cost=2, memory_cost=65536, parallelism=2` (lines 102–110)
- `allow_legacy_sha256=True` (default) → dual-verify для grace-period migration (line 110, comment line 96–100)
- Per-call `PasswordHasher` caching в `__post_init__` (line 112–124) — устраняет 5–10µs overhead на verify
- Per-instance `_legacy_warning_emitted` (line 124) — устраняет cross-tenant warning noise (review item A-1)
- Weak-secret detector: `validate_strength()` (line 165–189) — пустой/blacklist/<24 chars/sequential-chars/low-entropy
- HS-secret weak-detector: `_validate_jwt_secret_strength()` (jwt_backend.py:419–455) — для HS256/HS384/HS512 в JwtBackend.__post_init__

### 2.5 JWT stack — joserfc + JWKS cache + blacklist
**Evidence:**
- `src/backend/core/auth/jwt_backend.py` — joserfc-only, удалён shim + deprecated flag `auth_joserfc` (S67 W2/S68 W1, строки 7–12 + 245–249 + 334)
- `JwksCache` (jwks_cache.py:63–125) — TTL + asyncio.Lock + **stale-fallback на network-failure** (строки 88–99: если fetch failed и есть cache — возвращаем stale с WARNING)
- `RedisJwtBlacklist` (jwt_blacklist.py:61–166) — per-jti revoke + **batch `revoke_before_time`** (S18 W4, строки 105–132: monotonic `MAX(current, new)` для предотвращения rotation rollback)
- `is_iat_revoked` (jwt_blacklist.py:134–166) — независимая от jti проверка для rotation barrier
- `JwtBackend.decode` (jwt_backend.py:242–329) — fail-closed при blacklist failure (lines 297–304, 317–320)

### 2.6 PII маскирование — 2 уровня (irreversible + reversible)
**Evidence:**
- `PIIMasker` (pii_masker.py:136–271) — 15 regex-паттернов: jwt/iban/ssn/snils/card/passport/email/inn/phone/ru_surnames/ru_patronymics/bik/ogrn/openai_key/github_pat/aws_access_key; `_DEFAULT_ORDER` — specific-first
- `PIITokenizer` (pii_tokenizer.py:147–464) — Presidio + AES-GCM TokenMap (ключи в Redis через `token_registry`, TTL `policy.ttl_s`), reversible `mask_reversible ↔ unmask` round-trip
- `PIIPolicy.entity_types` (pii_tokenizer.py:118–127) — RU-specific: `("INN", "SNILS", "PASSPORT_RF", "CONTRACT")`
- `core/security/pii_patterns.py` (52 строк) — single source of truth для SNILS/INN/RU_PASSPORT/EMAIL/PHONE/CARD (S219/S221/S222 consolidation)

### 2.7 CapabilityGate — thread-safe + tenant-aware + audit-emit
**Evidence:**
- `src/backend/core/security/capabilities/gate/` — 4 mixin'а (declaration/check/cache/audit) + `_protocol.py` для cross-mixin атрибутов (mypy-friendly)
- **D-AUDIT-98 fix (S183 W1.1)**: cache reads/writes под `self._lock` для предотвращения `RuntimeError: dictionary changed size during iteration` (строки 70, 219, 241, 254, 273, 299, 313 в check_mixin.py + cache_mixin.py:66, 80, 94, 105)
- Tenant-aware API: `check_tenant`/`declare_tenant`/`revoke_tenant`/`list_allocated_tenant` (declaration_mixin.py:76–158)
- Dual-emit audit (audit_mixin.py:86–99) — callback + unified `emit_capability_check` (S106 W5 Path A)
- `CapabilityPolicy` (capabilities/policy.py:101–144) — declarative deny/allow rules, **deny > allow tie-break** (строки 113–117)
- 47 registered capabilities (capabilities/vocabulary/defaults.py, 522 LOC)

### 2.8 ASGI middlewares — pure ASGI, no buffering race
**Evidence:**
- `SecurityHeadersMiddleware` (entrypoints/middlewares/security_headers.py:53–110) — pure ASGI через обёртку `send`, корректно для streaming/SSE/WebSocket-upgrade (S176 cycle 33 B-07 fix)
- `AuthRequiredMiddleware` (entrypoints/middlewares/auth_required.py:81–199) — pure ASGI auth-guard, 401 через send (no-raise, cycle 39), public-path allowlist (строки 46–64)
- `AuthMethodHeaderMiddleware` (entrypoints/middlewares/auth_method_header.py:27–126) — **default-OFF** (`enabled=False`, строка 49) — security default (S191 fix): header leaks auth-method (information disclosure)

### 2.9 Декораторы/фреймворки
- `require_capability` (core/security/connector_auth.py:48–145) — fail-closed декоратор для Sink.send/Source.stream/RPA.process_step
- `check_source_capability` (line 148–220) — bool-вариант для long-lived stream generators
- `require_admin` (core/auth/admin_roles.py:95–128) — RBAC, `SUPER_ADMIN` implicit allow для всех
- `require_sso_auth`/`require_sso_capability` (core/auth/require_sso_auth.py:92–183) — fail-closed SSO/RBAC decorators

### 2.10 Audit/SIEM-friendly errors
- `CapabilityDeniedError.to_dict()` (errors.py:86–104) — structured для SIEM-export с полями `error_type/capability/tenant/principal/plugin/scope/declared_scope/correlation_id`
- `AuditMixin._emit_audit` (audit_mixin.py:46–99) — dual-emit через callback + `emit_capability_check` unified service
- `CredentialProvider.get` (credential_provider.py:72–150) — `emit_secret_access` на cache-hit/miss/failure, **никогда не логирует сам секрет** (только метаданные)

---

## 3. Findings table

| ID | Priority | File:Line | Краткая суть |
|---|---|---|---|
| DOMAIN-P0-001 | P0 | `src/backend/services/agent_security/facade.py:130–133` | `validate_sql()` устанавливает `kwargs["policy_override"]` но НЕ передаёт в `self.framework.validate_sql(query)` — per-workflow SQL-политика silently dropped |
| DOMAIN-P0-002 | P0 | `src/backend/entrypoints/middlewares/auth_required.py:177–182` | ASGI-middleware обращается к deprecated-shim `entrypoints/api/dependencies/auth_selector.verify_request` вместо канонического `core.auth.auth_selector` (downward-acceptable, но single point of failure при удалении shim) |
| DOMAIN-P1-001 | P1 | `src/backend/core/security/connector_auth.py:77, 175` | `core → services.authorization.facade` (downward layer violation, lazy-import) |
| DOMAIN-P1-002 | P1 | `src/backend/core/auth/facade.py:296, 433` | `core → services.security.facade` (downward layer violation, lazy-import) |
| DOMAIN-P1-003 | P1 | `src/backend/core/auth/ad_directory.py:10` | `core → services.auth.ad_directory_client` (downward layer violation, re-export shim) |
| DOMAIN-P1-004 | P1 | `src/backend/entrypoints/mcp/auth_middleware.py:40` | Импорт приватных `_verify_api_key`, `_verify_jwt` из `core/auth/auth_selector` (encapsulation violation; S93 W3 эти символы помечены как private) |
| DOMAIN-P2-001 | P2 | `src/backend/core/security/authorization_gateway/__init__.py:357–383` | `_casbin_check` и `_opa_check` вызываются через `hasattr(...)`, но **не определены** ни в `CasbinMixin`, ни в `OpaMixin` (sync `check()` API полагается только на in-memory fallback) |
| DOMAIN-P2-002 | P2 | `src/backend/core/security/capabilities/vocabulary/vocabulary.py:52–58` | Type mismatch: `seen: set[str]` аннотирован как строки, но содержит `id(definition)` (int); плюс Python может переиспользовать id freed objects — fragile dedup |
| DOMAIN-P2-003 | P2 | `src/backend/core/security/activity_capability_guard.py:225` | Sentinel `capability="<missing-context>"` может коллидить с реальным capability-name (хотя `<>` обычно запрещены в `CAPABILITY_NAME_PATTERN`) |
| DOMAIN-P2-004 | P2 | `src/backend/core/security/capabilities/vocabulary/defaults.py:522` | Файл 522 LOC — большой и трудно поддерживаемый; можно разбить по доменам (db/net/fs/mq/cache/workflow/llm/secrets/...) |
| DOMAIN-P3-001 | P3 | `src/backend/core/security/pii_masker.py` (15-pattern regex-движок) | Custom regex заменяем на Presidio (`presidio-analyzer>=2.2.362` уже в pyproject.toml:103). Trade-off: latency + streaming нужен custom; но для batch DSL `mask_pii` Preсidio предпочтительнее (multilingual, NER quality). LOC delta: −~150. Лицензия: Presidio — MIT, активный maintenance (Microsoft). |
| DOMAIN-P3-002 | P3 | `src/backend/core/security/capabilities/gate/__init__.py:91` | Custom `Lock` + dict-based LRU; `cachetools>=5.3.0,<8.0.0` уже в pyproject.toml:108. Trade-off: текущая реализация predictable (LRU eviction + tenant invalidation hooks); cachetools.LRUCache потребует rewrite invalidation paths. LOC delta: −~30. |
| DOMAIN-P4-001 | P4 | (DSL-level) | OPA policy DSL: сейчас нужен Python OPAClient + ручное подключение в composition root. Camel/Airflow-style мог бы иметь route.toml `[security] opa_policy="authz/default"` без программного конфига. |

---

## 4. Detailed evidence

### DOMAIN-P0-001 — `validate_sql` не передаёт per-workflow policy override

**Path:** `src/backend/services/agent_security/facade.py:130–133`

```python
def validate_sql(
    self, query: str, *, workflow_id: str | None = None, **kwargs: Any
) -> SecurityDecision:
    policy = self.get_policy_for_workflow(workflow_id)
    if policy is not None:
        kwargs["policy_override"] = policy           # <-- set, but...
    return self.framework.validate_sql(query)         # <-- kwargs не передаются!
```

**Сравнение с корректными sibling-методами** (`validate_prompt` line 91–104, `validate_command` line 106–119):
```python
# validate_prompt (correct):
return self.framework.validate_prompt(prompt, context=ctx)
# validate_command (correct):
return self.framework.validate_command(command, context=ctx)
# validate_sql (BROKEN):
return self.framework.validate_sql(query)             # ← kwargs/ctx НЕ переданы
```

**Дополнительно** (line 121–133 `validate_sql`): `kwargs["policy_override"] = policy` модифицирует входной kwargs на caller-side (поскольку `**kwargs` — это dict, а не copy). При этом `validate_file_modification` (line 135–156) и `mask_output` (line 158–171) делают `ctx = dict(kwargs)` — defensive copy, и только `validate_sql` не делает копию. Это усугубляет проблему: caller'овский kwargs может быть изменён, но всё равно не использован.

**Impact:** Per-workflow SQL-policy, установленная через `set_policy_for_workflow()` (строки 52–67), **никогда не применяется** при вызове `AgentSecurityFacade.validate_sql()`. S204 retro-audit B18 починка, описанная в docstring (строки 33–38), работает только для prompt/command/file/output, но НЕ для SQL. Это тихий security-bypass: workflow с кастомной SQL-политикой будет валидироваться через **глобальный default policy**, а не свой override. Для banking-кредитного workflow (см. `ai_policies/credit_check_strict.policy.yaml`) это может означать, что разрешённые topics/queries проверяются по неправильному правилу.

**Minimal fix:**
```python
def validate_sql(
    self, query: str, *, workflow_id: str | None = None, **kwargs: Any
) -> SecurityDecision:
    policy = self.get_policy_for_workflow(workflow_id)
    ctx = dict(kwargs)
    if policy is not None:
        ctx["policy_override"] = policy
    return self.framework.validate_sql(query, context=ctx)
```

**Test-критерий:** unit-тест, аналогичный `validate_prompt`/`validate_command` (если существуют), проверяющий что `framework.validate_sql` вызывается с `context["policy_override"]` при non-None `get_policy_for_workflow`. Также regression-тест: workflow A задаёт policy_X, вызов `validate_sql(..., workflow_id="A")` приводит к вызову `framework.validate_sql(query, context={"policy_override": policy_X, ...})`.

---

### DOMAIN-P0-002 — `AuthRequiredMiddleware` использует deprecated shim

**Path:** `src/backend/entrypoints/middlewares/auth_required.py:177–182`

```python
from src.backend.entrypoints.api.dependencies.auth_selector import (
    verify_request,
)

request = Request(scope, receive=receive)
return await verify_request(request, methods=self._accepted_methods)
```

`src/backend/entrypoints/api/dependencies/auth_selector.py:33` — DEPRECATED shim, реэкспорт из `core.auth.auth_selector` (S96 W1 relocation). Сейчас работает, но `entrypoints/middlewares/auth_required.py` импортирует из shim, а не напрямую — single point of failure при удалении shim в S99+.

**Impact:** не fail-open (shim выдаёт DeprecationWarning, но работает). Однако если в S99+ shim будет удалён, **auth сломается на всех non-public endpoints** без какого-либо предупреждения в ASGI-middleware — это P0, потому что вся авторизация production-traffic пойдёт через 401.

**Minimal fix:** в `auth_required.py:177` импортировать `verify_request` напрямую из `src.backend.core.auth.auth_selector` (canonical путь, S96 W1).

**Test-критерий:** интеграционный тест, который поднимает AuthRequiredMiddleware с заглушкой upstream-app и проверяет, что 200/401 приходит независимо от наличия/отсутствия `entrypoints.api.dependencies.auth_selector` (т.е. после потенциального удаления shim).

---

### DOMAIN-P1-001 — `core/security/connector_auth.py:77, 175` layer violation

**Path:** `src/backend/core/security/connector_auth.py:77–87, 175–181`

```python
# Line 76-87 (lazy inside wrapper):
try:
    from src.backend.services.authorization.facade import (
        get_authorization_facade,
    )
except Exception as exc:  # pragma: no cover — facade недоступен в test
    _logger.debug(
        "authorization_facade_unavailable: %s; failing closed",
        exc,
    )
    raise ConnectorAuthError(...)

# Line 175-181:
try:
    from src.backend.services.authorization.facade import get_authorization_facade
except Exception as exc:  # pragma: no cover
    _logger.debug("authorization_facade_unavailable: %s; failing closed", exc)
    return False
```

**Impact:** layer rule гласит `core → services` запрещено (per AGENTS.md: extensions импортируют ТОЛЬКО `core.*`). Декоратор `require_capability` предназначен для extensions (per docstring строки 6–22), но расположен в `core/security/`. Прямой cross-layer import создаёт циклическую зависимость: `services/authorization/facade.py:85` уже импортирует `core.auth.facade`, а `core.auth.facade:296,433` импортирует обратно `services.security.facade`. Lazy-import прячет, но не устраняет.

**Minimal fix:** перенести `require_capability`/`check_source_capability` в `extensions/core_security/` или сделать однослойную композицию через DI.

**Test-критерий:** статический lint (existing tools/check_layers.py) должен ловить прямой import; lazy-import не покрывается.

---

### DOMAIN-P1-002 — `core/auth/facade.py:296, 433` layer violation

**Path:** `src/backend/core/auth/facade.py:296–304, 433–439`

```python
# Line 296:
try:
    from src.backend.services.security.facade import get_security_facade

    facade = get_security_facade()
    return await facade.is_token_blacklisted(jti)
# Line 433:
try:
    from src.backend.services.security.facade import get_security_facade

    facade = get_security_facade()
    await facade.blacklist_token(jti)
    return True
```

**Impact:** AuthFacade в core импортирует SecurityFacade из services → циклическая cross-layer зависимость. При hot-reload (composition root reset) или test fixture без services модуля — может упасть с `ImportError`, что НЕ отлавливается явно (`except Exception` ловит, но fail-open semantics в `_is_blacklisted`).

**Minimal fix:** перенести `RedisJwtBlacklist`/`SecurityFacade` blacklist-логику в `core/security/jwt_blacklist.py` (класс уже там существует), и вызывать напрямую.

**Test-критерий:** lint rule + integration test с mocked services в DI.

---

### DOMAIN-P1-003 — `core/auth/ad_directory.py:10` re-export shim

**Path:** `src/backend/core/auth/ad_directory.py:1–15`

```python
"""Capability-checked facade для AD directory client (S124 W1).
…
"""
from src.backend.services.auth.ad_directory_client import (  # noqa: F401
    AdAuthError,
    AdSearchEntry,
)
```

**Impact:** модуль в `core/auth/` импортирует из `services/auth/` только чтобы re-export 2 класса. Прямое нарушение layer rule (core → services). Файл не используется в core/auth (`grep -rn "from src.backend.core.auth.ad_directory" src/backend` → не проверено, но в `auth_context_helpers.py`, `protocols.py`, и других core/auth/* файлах нет упоминаний).

**Minimal fix:** удалить `core/auth/ad_directory.py` (8 LOC + 15 строк docstring); импортеры (если есть) переключить на `src.backend.services.auth.ad_directory_client` или на новый core-контракт `core/auth/ldap_contract.py` (где уже есть `AdServerConfig`).

**Test-критерий:** grep — `grep -rn "from src.backend.core.auth.ad_directory" src/backend` должен вернуть 0 строк (если есть импортеры — мигрировать).

---

### DOMAIN-P1-004 — `entrypoints/mcp/auth_middleware.py:40` private import

**Path:** `src/backend/entrypoints/mcp/auth_middleware.py:40–66`

```python
from src.backend.core.auth.auth_selector import _verify_api_key, _verify_jwt
…
if "api_key" in methods and headers.get("x-api-key"):
    try:
        ctx = await _verify_api_key(request)
        if ctx is not None:
            return True
    except Exception as exc:
        logger.debug("MCP api_key verify failed: %s", exc)

if "jwt" in methods and headers.get("authorization", "").lower().startswith(
    "bearer "
):
    try:
        ctx = await _verify_jwt(request)
        if ctx is not None:
            return True
```

**Impact:** использует private-символы (underscore-prefix) из `core/auth/auth_selector`. По S93 W3 `_VERIFIERS` был сделан private, и `core.auth.auth_selector` экспортирует только public `verify_request`, `require_auth`, `set_default_auth`. Прямое использование `_verify_api_key`/`_verify_jwt` — encapsulation violation; при рефакторе `auth_selector` (например, переименование функций) MCP-auth сломается без предупреждения.

**Minimal fix:** использовать public `verify_request` через dummy request, аналогично `AuthRequiredMiddleware._authenticate` (строки 169–182):

```python
async def _verify(scope: dict[str, Any]) -> bool:
    from src.backend.core.auth.auth_selector import verify_request
    request = _DummyHeadersRequest(headers)
    ctx = await verify_request(request, methods=methods_enums)
    return ctx is not None
```

**Test-критерий:** unit-тест на изменение/удаление `_verify_api_key` в `auth_selector.py` (smoke test, что MCP не падает).

---

### DOMAIN-P2-001 — sync `check()` API не использует Casbin/OPA steps

**Path:** `src/backend/core/security/authorization_gateway/__init__.py:357–383`

```python
def _casbin_check(
    self, subject: str, action: str, resource: str
) -> bool | None:
    """Internal: try Casbin step if available."""
    from src.backend.core.security.authorization_gateway.casbin_mixin import (
        CasbinMixin,
    )

    if hasattr(CasbinMixin, "_casbin_check"):
        return CasbinMixin._casbin_check(self, subject, action, resource)
    return None

def _opa_check(
    self,
    subject: str,
    action: str,
    resource: str,
    context: dict[str, Any] | None,
) -> bool | None:
    """Internal: try OPA step if available."""
    from src.backend.core.security.authorization_gateway.opa_mixin import OpaMixin

    if hasattr(OpaMixin, "_opa_check"):
        return OpaMixin._opa_check(
            self, subject, action, resource, context
        )
    return None
```

**Проверено:** `grep -n "_casbin_check\|_opa_check" src/backend/core/security/authorization_gateway/casbin_mixin.py src/backend/core/security/authorization_gateway/opa_mixin.py` → **0 matches**. Методы `_casbin_check`/`_opa_check` не определены в mixin-классах.

**Impact:** sync `check()` API (AuthorizationGateway.check, lines 249–309) вызывает `_casbin_check`/`_opa_check` через `hasattr(...)` — всегда `False`, поэтому sync path фактически использует **только in-memory fallback** (`_in_memory_policies`, line 113) и default-deny (line 309). Это означает, что `AuthorizationFacade.check(subject, action, resource)` (services/authorization/facade.py:458–475) **никогда не обращается к реальным policy-engines** — только к in-memory dict. Если plugin runtime добавляет правила через `add_policy()`/`remove_policy()` — они работают; если только через OPA/Casbin — sync `check()` их НЕ увидит.

**Minimal fix:** либо определить `_casbin_check`/`_opa_check` в mixin-классах (синхронные обёртки над async steps через `asyncio.run` — но это anti-pattern в async-контексте), либо явно задокументировать, что sync `check()` API — только для in-memory fallback (не пытается вызывать async policy-engines).

**Test-критерий:** smoke-тест с sync `check()` против зарегистрированной через `add_policy` policy — pass; sync `check()` против policy зарегистрированной ТОЛЬКО через OPA/Casbin — fail (или no-op возвращает False).

---

### DOMAIN-P2-002 — type mismatch + fragile id-based dedup

**Path:** `src/backend/core/security/capabilities/vocabulary/vocabulary.py:50–59`

```python
def all(self) -> tuple[CapabilityDef, ...]:
    """Все определения в порядке регистрации (без дубликатов)."""
    seen: set[str] = set()           # ← type mismatch: str vs int
    result: list[CapabilityDef] = []
    for definition in self._defs.values():
        if id(definition) in seen:    # ← id() returns int
            continue
        seen.add(id(definition))
        result.append(definition)
    return tuple(result)
```

**Impact:**
1. Type annotation `set[str]` — mypy должен ругаться, но, видимо, не строгий режим включён (или используется `dict.values()` без итерации по id(0)).
2. `id()` — адрес в памяти; Python **может переиспользовать** freed object id (после GC) для новых объектов. В long-running production процессе с большим числом зарегистрированных/разрегистрированных capability это может привести к false-positive dedup (новая CapabilityDef пропустится, т.к. её id совпадает с id ранее удалённой).

**Minimal fix:** использовать отдельный dedup-set по `_defs` dict keys (def уже хранится под именем), либо по стабильному hash:

```python
def all(self) -> tuple[CapabilityDef, ...]:
    seen_keys: set[str] = set()
    result: list[CapabilityDef] = []
    for name, definition in self._defs.items():
        if name in seen_keys:
            continue
        seen_keys.add(name)
        result.append(definition)
    return tuple(result)
```

Либо ещё проще: итерировать по list of unique definitions, не по dict.values() (которые уже уникальны для каждого `_defs[name]` key, а aliases указывают на тот же объект — `register` lines 30–33 присваивает тот же `definition` для всех aliases).

**Test-критерий:** unit-тест с property-based: зарегистрировать 100 разных CapabilityDef, вызвать `all()`, убедиться, что нет дублей и нет пропусков.

---

### DOMAIN-P2-003 — Sentinel `<missing-context>` в CapabilityDeniedError

**Path:** `src/backend/core/security/activity_capability_guard.py:223–228`

```python
raise CapabilityDeniedError(
    plugin=fn.__name__,
    capability="<missing-context>",
    requested_scope="<unset>",
    declared_scope=None,
)
```

**Impact:** `<missing-context>` не зарегистрирована как real capability, и `CAPABILITY_NAME_PATTERN` (capabilities/models.py) скорее всего запрещает `<>` (нужно проверить). Audit-event `activity.capability.denied` будет содержать `capability="<missing-context>"` — alerting rule может ложно сработать на реальный capability с именем, начинающимся на `<missing`. Минимально: использовать `None` или sentinel-class (например `class _MissingContext: pass`).

**Test-критерий:** unit-тест с `_set_active_capability_context(None)` + capability_guarded_activity — audit-event должен содержать marker, который alerting может фильтровать.

---

### DOMAIN-P2-004 — defaults.py 522 LOC

**Path:** `src/backend/core/security/capabilities/vocabulary/defaults.py` (522 строки)

**Impact:** монолитный файл, 47 `vocab.register(...)` вызовов, трудно поддерживать. S62 W2 уже сделал initial decomp (vocabulary.py 509 LOC → vocabulary.py + defaults.py + models.py); можно продолжить декомпозицию по доменам (db/net/fs/mq/cache/workflow/llm/secrets).

**Minimal fix:** разбить на `_db.py`, `_net.py`, `_fs.py`, `_mq.py`, `_cache.py`, `_workflow.py`, `_llm.py`, `_secrets.py` + re-export в `defaults.py`.

**Test-критерий:** функциональный тест `build_default_vocabulary()` — должен возвращать тот же набор capabilities после refactor.

---

### DOMAIN-P3-001 — PIIMasker заменяем на Presidio для batch

**Path:** `src/backend/core/security/pii_masker.py` (271 строк)

**Evidence:** pyproject.toml:103 `presidio-analyzer>=2.2.362`, line 104–105 `presidio-anonymizer>=2.2.0`, line 106–107 `presidio-ru-recognizers>=0.1.0,<1.0.0`.

**Trade-off:**
- Custom regex PIIMasker: 15 patterns, мгновенный latency, low memory.
- Presidio: NER-based, multilingual, выше recall на edge-cases (имена, адреса), требует spaCy model ~1.5GB.

**Recommendation:** оставить PIIMasker для **streaming** (low-latency SSE/WS) и для **DSL `mask_pii` step** (где latency критична), но добавить опциональный fallback на PresidioAnalyzer для **batch DSL** `mask_pii.advanced()`. Никаких breaking changes.

**License/Maintenance:** Presidio — MIT, Microsoft, активный maintenance (last release < 1 год). Безопасно.

**LOC delta:** −150 LOC (текущий regex-движок заменяется на тонкий wrapper).

---

### DOMAIN-P3-002 — CapabilityGate LRU на cachetools.LRUCache

**Path:** `src/backend/core/security/capabilities/gate/cache_mixin.py:59–87`

**Evidence:** pyproject.toml:108 `cachetools>=5.3.0,<8.0.0`.

**Trade-off:**
- Custom dict-based LRU: явный eviction, predictable, lock-protected (D-AUDIT-98).
- cachetools.LRUCache: встроенный, но не thread-safe по дизайну (см. комментарий в `services/security/facade.py:360–366` для JWT blacklist).

**Recommendation:** **Оставить custom** — thread-safety критична для D-AUDIT-98 fix; cachetools потребует добавления Lock поверх, что не сократит код.

**License/Maintenance:** cachetools — BSD-3, активный maintenance.

**LOC delta:** 0 (не рекомендуется).

---

### DOMAIN-P4-001 — OPA policy в DSL-style

**Path:** (design-level, не в одном файле)

**Description:** OPA policy name сейчас конфигурируется программно через `policy_settings.opa_policy_name` в composition root + Python OPAClient. Для EIP/Camel-style DSL естественно иметь декларативный binding через `route.toml`:

```toml
[security]
authz_policy = "authz/credit_check_v2"
opa_policy = "authz/credit_check_default"
```

**Justification:** органично вписывается в существующий route.toml security section (`requires_permission`, `requires_capability`); устраняет необходимость перезапуска composition root для смены policy.

**Trade-off:** нужен минимальный design-review (как валидировать policy_name, как тестировать через DSL-testkit).

---

## 5. Contradictions / Overlaps to flag

### 5.1 Baseline contradiction: working tree changes vs заявленный baseline
**User stated baseline:**
> "в working tree до старта уже изменены src/backend/infrastructure/storage/s3.py и uv.lock"

**Actual `git status --short`:**
```
 M pyproject.toml
 M tests/unit/dsl/transforms/test_dataframes.py
?? docs/audit/swarm-2026-08-06/
```

**Resolved:** я не трогал эти файлы, не приписывал их своему аудиту, и не анализировал их содержимое (вне scope). При передаче отчёта — флагую как рассогласование, чтобы upstream-cycle понимал, что baseline-claim не соответствует `git status` на момент старта.

### 5.2 Duplication between auth/auth_selector.py и auth/gateway.py
**Path:** `src/backend/core/auth/auth_selector.py:225–303` (`verify_request`, `require_auth`) и `src/backend/core/auth/gateway.py:33–94` (re-export + `AuthGateway` OO-facade).

`gateway.py` — тонкая обёртка над `auth_selector.py` (S95 W4 → S96 W1). Дубликата функциональности нет (gateway вызывает `verify_request`/`require_auth` напрямую, lines 81–93). OK.

### 5.3 Two JWT verify paths: auth_selector.verify_request vs facade.verify_request
**Path:** `core/auth/auth_selector._verify_jwt` (lines 80–94) vs `core/auth/facade.verify_request` (lines 117–159).

- `auth_selector._verify_jwt` — для ASGI-middleware, FastAPI Request interface, использует `get_jwt_backend_provider()`.
- `facade.verify_request` — для программных вызовов (services), принимает token-string, декодирует напрямую через `self.jwt.decode(token)`.

**Overlap:** оба декодируют JWT, но:
- auth_selector вернёт `AuthContext(method=JWT, principal=claims.sub, claims.raw)` (lines 142–144)
- facade вернёт `AuthResult(is_authenticated, method="jwt", subject=claims.sub, tenant_id, groups, capabilities)` (lines 137–145)

Два разных value-типа для одного и того же результата. S164 W2 это документирует как сознательный dual-API: middleware использует `AuthContext` (FastAPI-friendly), services используют `AuthResult` (typed-dataclass). Переход на единый тип — кардинальный refactor.

**Flag:** оба API живут и работают; для читателя кода — двусмысленность, какую использовать. Document this in AGENTS.md.

### 5.4 Two cookie-session verify paths
**Path:**
- `core/auth/auth_selector._verify_saml` (line 147–167) — SAML session cookie (`X-SAML-Session-ID` / `saml_session` cookie)
- `services/authorization/facade._check_cookie_session` (lines 360–415) — generic cookie session (Redis-backed `session:<session_id>` JSON)

**Overlap:** оба читают cookie/header, но:
- SAML session — opaque session_id (валидация на стороне SP-side store, см. строки 160–165)
- Generic cookie session — Redis JSON payload `{subject, tenant_id, capabilities}`

**Documented:** разные семантики; SAML-cookie — для SSO-flow, generic-cookie — для auth-flow. Не дубликат.

### 5.5 CapabilityGate.check vs CapabilityGate.check_tenant
**Path:** `src/backend/core/security/capabilities/gate/check_mixin.py:48–189` (check) vs `191–334` (check_tenant).

- `check(plugin, capability, scope)` — sync, raise CapabilityDeniedError, default tenant `_system`
- `check_tenant(capability, tenant, principal, scope)` — sync, returns bool, per-tenant storage

**Documented:** check_tenant — это forward-compatible API (Sprint 36), check оставлен для backward compat. Не дубликат, но `check` использует `SYSTEM_TENANT_ID = "_system"` (line 85), что делает все non-tenant вызовы эквивалентными `check_tenant(..., tenant="_system", principal=plugin, ...)`. Технически можно унифицировать.

### 5.6 ip_restriction_store vs auth_required public_paths
**Path:** `src/backend/core/security/ip_restriction_store.py:144–171` vs `src/backend/entrypoints/middlewares/auth_required.py:46–64`.

Два разных механизма для разных целей:
- `IPRestrictionStore` — IP-allowlist для **admin routes** (`/admin/*` + per-route rules), per-priority per-route rule check (line 161–165), admin-pattern fallback (line 168)
- `AuthRequiredMiddleware.public_prefixes` — path-prefix public allowlist для **auth-bypass**

**Documented:** разные семантики. IP-restriction — это **post-auth** gate (auth прошёл → IP проверка), auth_required public_paths — **pre-auth** bypass.

### 5.7 Default OFF для AuthMethodHeaderMiddleware vs default ON в других middleware
**Path:** `entrypoints/middlewares/auth_method_header.py:49` (`enabled: bool = False`)

Это **намеренный** S191 fix — default-OFF для предотвращения information disclosure (header leaks auth method). Не P1, а корректная security practice.

### 5.8 `AuthContext.metadata.get("admin_roles")` vs SAML groups
**Path:** `src/backend/core/auth/admin_role_resolver.py:44–82` (resolve_jwt_admin_roles/resolve_saml_admin_roles).

3 источника admin-ролей: JWT-claim, SAML groups, mTLS CN whitelist. Все маппятся через единый `AdminRoleMapping`. Не дубликат, но `extract_admin_roles` (admin_roles.py:68–92) дублирует логику извлечения из metadata (`raw = auth_context.metadata.get("admin_roles")`). Можно консолидировать.

---

## 6. Readiness score 0–100 с формулой и обоснованием

### 6.1 Формула

```
base_score = 100
P0_penalty = 30 × P0_count
P1_penalty = 12 × P1_count
P2_penalty = 4 × P2_count
P3_penalty = 2 × P3_count
P4_penalty = 1 × P4_count

readiness = max(0, base_score - P0_penalty - P1_penalty - P2_penalty - P3_penalty - P4_penalty)
```

### 6.2 Подсчёт

| Priority | Count | Penalty/шт | Итого |
|---|---|---|---|
| P0 | 2 | 30 | −60 |
| P1 | 4 | 12 | −48 |
| P2 | 4 | 4 | −16 |
| P3 | 2 | 2 | −4 |
| P4 | 1 | 1 | −1 |

**Расчёт:** 100 − 60 − 48 − 16 − 4 − 1 = **−29 → clamped to 0** (max(0, …)).

### 6.3 Оценка с учётом правила ≥80 запрещено при P0/P1

Per правило: «Оценка ≥80 запрещена при наличии P0/P1».

У нас **2 P0 + 4 P1** — поэтому readiness **обязательно < 80**.

С учётом heavy penalties, финальный score по формуле = **0** (clamped).

### 6.4 Качественная оценка strengths (без численного вклада в формулу)

| Категория | Quality |
|---|---|
| OPA runtime integration (fail-closed, feature-flagged, tested) | Excellent (5/5) |
| AuthorizationGateway mixin decomposition + Prometheus metrics | Excellent (5/5) |
| CapabilityGate thread-safety + tenant isolation + audit dual-emit | Excellent (5/5) |
| JWT stack (joserfc + JWKS stale-fallback + blacklist with iat-revoke) | Excellent (5/5) |
| Argon2id API key + weak-secret detector | Excellent (5/5) |
| SAML replay defence + InResponseTo tracking | Good (4/5) — InResponseTo in-memory не persistent (per-process), но acceptable per design |
| PII masking (irreversible + reversible) | Excellent (5/5) |
| ASGI middlewares (pure ASGI, race-free) | Excellent (5/5) |
| Audit-event emission + structured errors | Excellent (5/5) |
| Layer boundaries | **Mixed (2/5)** — 4 downward layer violations (P1) |
| Encapsulation | **Mixed (3/5)** — private symbols leaked (P1) |

### 6.5 Итоговая оценка

**Readiness = 0 / 100** (per формуле, clamped).

**Обоснование:** 2 P0 (AgentSecurityFacade.validate_sql silently drops policy_override; AuthRequiredMiddleware зависит от deprecated shim) + 4 P1 (downward layer violations + private-symbol leak) делают security-domain **не готовым к production-ready** в строгом смысле.

**Условная readiness** (если бы не было P0/P1): архитектурно security-domain на уровне 95% готовности (verified strengths §2) — production-quality OPA integration, fail-closed semantics, thread-safe capability gate, JWKS stale-fallback, Argon2id API keys, pure ASGI middlewares. Но P0/P1 блокируют до их устранения.

---

## 7. Recommended next tasks

### Немедленно (P0/P1)
1. **DOMAIN-P0-001 (1 час)**: Fix `AgentSecurityFacade.validate_sql` — передать `context=ctx` в `self.framework.validate_sql(query, context=ctx)`. Проверить sibling-методы — они уже делают это правильно.
2. **DOMAIN-P0-002 (1 час)**: В `entrypoints/middlewares/auth_required.py:177` заменить импорт `verify_request` на canonical путь `src.backend.core.auth.auth_selector` (избежать single-point-of-failure на S99+).
3. **DOMAIN-P1-001..004 (4–8 часов)**: устранить downward layer violations. Самый критичный — `core/auth/facade.py` зависит от `services/security/facade` для JWT-blacklist (P1-002). Перенести blacklist-логику в `core/security/jwt_blacklist.py` (класс `RedisJwtBlacklist` уже там). После этого — `core/security/connector_auth.py` тоже может импортировать через core-уровень.

### Среднесрочно (P2)
4. **DOMAIN-P2-001**: документировать или реализовать sync `check()` API для Casbin/OPA. Минимум — docstring с явным указанием, что sync path использует только in-memory fallback.
5. **DOMAIN-P2-002**: исправить type annotation в `vocabulary.all()` + убрать fragile id-based dedup (использовать dict keys напрямую).
6. **DOMAIN-P2-003**: заменить sentinel `<missing-context>` на `None` или специальный singleton-class.
7. **DOMAIN-P2-004**: разбить `capabilities/vocabulary/defaults.py` (522 LOC) на per-domain модули.

### Опционально (P3/P4)
8. **DOMAIN-P3-001**: добавить `mask_pii.advanced()` через Presidio для batch DSL (separate API, не breaking change).
9. **DOMAIN-P4-001**: route.toml `[security] opa_policy = "..."` — design review через Sprint planning.

---

## 8. Commands run (для воспроизводимости)

```bash
# Scope inventory
ls -la src/backend/core/security/ src/backend/core/auth/ \
       src/backend/services/security/ src/backend/services/auth/ \
       src/backend/services/authorization/ src/backend/services/agent_security/

# Working tree status
git status --short

# Baseline verification
git rev-parse HEAD
git log --oneline -3

# OPA integration trace
grep -rn "opa_step\|opa_runtime_query_enabled\|OPAClient" src/backend \
  | grep -v __pycache__ | head -40

# Policy decider usages
grep -rn "build_opa_policy_decider\|OPAPolicyDecider\|build_casbin_policy_decider\|CasbinPolicyDecider" \
  src/backend tests | grep -v __pycache__ | head -30

# TODO / FIXME / NotImplemented scan
grep -rn "TODO\|FIXME\|XXX\|HACK" src/backend/core/security src/backend/core/auth \
                                   src/backend/services/security src/backend/services/auth \
                                   src/backend/services/authorization src/backend/services/agent_security \
  | grep -v __pycache__ | grep -v "XXX-" | head -20

grep -rnE "raise NotImplementedError|stub" src/backend/core/security src/backend/core/auth \
                                            src/backend/services/security src/backend/services/auth \
                                            src/backend/services/authorization src/backend/services/agent_security \
  | grep -v __pycache__ | head -20

# Layer violations
grep -rn "from src.backend.services" src/backend/core/security/ src/backend/core/auth/
grep -rn "from src.backend.entrypoints" src/backend/core/security/ src/backend/core/auth/

# Security allowlist direct count
grep -E "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt | wc -l   # → 35

# LOC inventory
find src/backend/core/security src/backend/core/auth \
     src/backend/services/security src/backend/services/auth \
     src/backend/services/authorization src/backend/services/agent_security \
     -name "*.py" -not -path "*__pycache__*" \
     -exec wc -l {} \; | awk '{total += $1; count++} END {print "files:", count, "total LOC:", total}'
# → files: 72 total LOC: 11291

find tests/security tests/auth -name "*.py" -not -path "*__pycache__*" \
     -exec wc -l {} \; | awk '{total += $1; count++} END {print "test files:", count, "total LOC:", total}'
# → test files: 11 total LOC: 852

# Dependency check (security-related)
grep -E "argon2|joserfc|hvac|ldap3|python3-saml|cachetools|presidio|casbin" pyproject.toml

# Synced mixin check (DOMAIN-P2-001)
grep -n "_casbin_check\|_opa_check" \
  src/backend/core/security/authorization_gateway/casbin_mixin.py \
  src/backend/core/security/authorization_gateway/opa_mixin.py
# → 0 matches (P2-001 confirmed)

# Capability registry stats
grep -c "^\s*vocab.register" src/backend/core/security/capabilities/vocabulary/defaults.py
# → 47
wc -l src/backend/core/security/capabilities/vocabulary/defaults.py
# → 522

# Sentinel <missing-context> scan
grep -rn "missing-context" src/backend | grep -v __pycache__

# id-based dedup pattern scan
grep -rn "id(.*) in seen\|seen.add(id" src/backend/core/security | grep -v __pycache__
```

**Все команды выполнялись в read-only режиме.** Никаких изменений в исходном коде, конфигурации, lockfiles или allowlists не сделано. Только этот отчёт создан в `docs/audit/swarm-2026-08-06/cycle-1/phase-1/02-security.md`.

---

## 9. Краткая сводка для parent-agent

**Domain:** Security (cycle-1 phase-1)
**Status:** NOT_READY (P0 + P1 blockers)
**Readiness:** 0 / 100 (clamped; P0+P1 penalties −108, base 100)
**Findings count:** P0=2, P1=4, P2=4, P3=2, P4=1 (total 13)
**Blocker IDs:**
- **DOMAIN-P0-001** — `services/agent_security/facade.py:130–133` — `validate_sql` silently drops per-workflow `policy_override` (kwargs не передаются в `framework.validate_sql(query)`)
- **DOMAIN-P0-002** — `entrypoints/middlewares/auth_required.py:177–182` — импорт через deprecated shim `entrypoints.api.dependencies.auth_selector` (single-point-of-failure при S99+ cleanup)
- **DOMAIN-P1-001..004** — 4 downward layer violations (core → services) + private-symbol leak в MCP-auth

**Verified strengths (highlights):**
- OPA runtime integration — fully wired, fail-closed, tested (`opa_mixin.py`, `OPAClient`, `authz_default.rego`, `composition/di.py:158–195`)
- AuthorizationGateway — 4 mixins (audit/casbin/opa/permission), Prometheus metrics, fail-closed chain
- CapabilityGate — thread-safe (D-AUDIT-98 fix), tenant-aware, dual-emit audit
- JWT stack — joserfc + JWKS stale-fallback + Redis blacklist with iat-revoke (fail-closed)
- Argon2id API key hashing + weak-secret detector
- SAML replay-defence (InResponseTo tracking)
- Pure ASGI middlewares (race-free, no buffering)
- PII masking (irreversible + reversible через Presidio + AES-GCM)

**Recommended first action:** fix DOMAIN-P0-001 (1 час) — единственная реальная security-bypass в scope. DOMAIN-P0-002 — единичная fix, устраняет single-point-of-failure.