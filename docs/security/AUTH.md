# Authentication & Authorization — gd_integration_tools

> Комплексный обзор auth-стратегии ядра, требований к
> production-окружению и пошаговых процедур для разработчиков.

## Содержание

1. [Login flow v2 (step-up)](#login-flow-v2-step-up)
2. [CSRF cookie hardening (B-04)](#csrf-cookie-hardening-b-04)
3. [Public path allowlist](#public-path-allowlist)
4. [Operational checklists](#operational-checklists)

---

## Login flow v2 (step-up)

> B-04 fix (cycle 33): ``/api/v1/auth/login`` больше не в public
> allowlist. Защищён ``X-Step-Up-Token`` header + per-IP rate-limit
> ``10 attempts / 5 min``.

### Зачем step-up

Pre-fix сценарий: ``/api/v1/auth/login`` был открытым endpoint'ом
(public allowlist). Это позволяло:

* Brute-force credential stuffing без pre-auth rate-limit'а на уровне
  ``AuthRequiredMiddleware``.
* CSRF-атаки на login form с автоматической отправкой credentials
  жертвы (sophisticated phishing + cookie replay).
* DDoS на login endpoint без дополнительного слоя защиты.

Step-up добавляет обязательный pre-auth token: клиент сначала
запрашивает short-lived ``X-Step-Up-Token`` через отдельный endpoint
(``POST /api/v1/auth/step-up-request`` — out of scope этого PR,
запланирован в Sprint 37), затем использует его в login-запросе.
Это:

* Сужает surface для credential stuffing (без валидного token'а
  запрос отклоняется **до** обращения к auth-handler).
* Позволяет задавать разные rate-limit'ы на разные источники
  (IP, tenant, session).
* Совместимо с bot-detection (Cloudflare Turnstile, hCaptcha) —
  pre-auth endpoint может выполнять challenge, а login — нет.

### Контракт

**``POST /api/v1/auth/login``** — теперь требует:

| Header | Required | Описание |
|---|---|---|
| ``X-Step-Up-Token`` | ✓ | Short-lived token из ``/step-up-request``. Non-empty, non-whitespace. |
| ``Content-Type`` | ✓ | ``application/json``. |
| ``X-Forwarded-For`` | — | Первый IP используется для rate-limit (за reverse proxy). |

**Response codes:**

| Status | Когда | Headers |
|---|---|---|
| ``200 OK`` | Успешная аутентификация (downstream решил) | — |
| ``401 Unauthorized`` | Отсутствует / пустой ``X-Step-Up-Token`` | ``Content-Type: application/json`` |
| ``429 Too Many Requests`` | > 10 attempts / 5 min с одного IP | ``Retry-After``, ``X-RateLimit-Scope: login_step_up`` |
| ``503 Service Unavailable`` | Rate-limit backend (Redis) недоступен (fail-closed) | ``X-RateLimit-Scope: login_step_up`` |

### Архитектура

```
Client → POST /api/v1/auth/login (+ X-Step-Up-Token)
    │
    ▼
┌─────────────────────────────────────────────────┐
│ LoginStepUpMiddleware (B-04, cycle 33, pure ASGI)│
│                                                  │
│ 1. OPTIONS preflight → bypass                    │
│ 2. Path != /api/v1/auth/login → bypass           │
│ 3. Method != POST → bypass                       │
│ 4. X-Step-Up-Token missing/empty → 401            │
│ 5. Rate-limit per-IP exceeded → 429              │
│ 6. OK → downstream (auth-handler)                │
└─────────────────────────────────────────────────┘
    │
    ▼
Auth handler (внутренний) — login business logic
```

### Rate-limit detail

* **Лимит**: ``LOGIN_RATE_LIMIT = 10`` attempts
* **Окно**: ``LOGIN_WINDOW_SECONDS = 300`` (5 min)
* **Backend**:
  * Production: ``RedisRateLimitChecker`` через
    ``build_rate_limit_checker`` (token-bucket в Redis).
  * Dev/test: ``FakeRateLimitChecker`` (in-memory).
* **Fail-mode**: **fail-closed** (deny). Если Redis недоступен →
  ``503 Service Unavailable``. Альтернатива fail-open недопустима
  для login (anti-brute-force security-critical endpoint).
* **Identifier**: ``login_stepup:ip:<client_ip>``, где client_ip =
  первый IP из ``X-Forwarded-For`` (если есть) или ``scope['client'][0]``.

### Конфигурация

``src/backend/entrypoints/middlewares/login_step_up.py``:

```python
LOGIN_PATH = "/api/v1/auth/login"
LOGIN_RATE_LIMIT = 10
LOGIN_WINDOW_SECONDS = 300
```

Tunables определены как module-level constants и могут быть
overridden через DI-фабрику ``rate_limit_factory`` в middleware
constructor.

### Совместимость

* **Breaking change** для существующих login-flows (Streamlit Login
  page, programmatic API clients).
* Migration plan:
  1. Frontend запрашивает ``X-Step-Up-Token`` через
     ``POST /api/v1/auth/step-up-request`` перед login.
  2. Token включается в header каждого login-запроса.
  3. Token TTL: 60 сек (достаточно для одной попытки).
* Streamlit Login page: требует обновления в Sprint 37 (отдельный
  B-task).

### Тестирование

``tests/unit/entrypoints/middlewares/test_login_step_up.py`` —
3 unit-класса:

* ``TestLoginStepUpMissingToken`` — token missing / empty / OPTIONS /
  GET bypass / non-login-path bypass.
* ``TestLoginStepUpRateLimit`` — 11-й attempt → 429, per-IP isolation,
  XFF header respected.
* ``TestLoginStepUpSuccessPath`` — valid token → 200, WebSocket bypass.
* ``TestCSRFCookieDefaults`` — ``HttpOnly`` + ``SameSite=strict``
  присутствуют в CSRF cookie (cross-cutting regression для B-04).

---

## CSRF cookie hardening (B-04)

> B-04 fix (cycle 33): ``CSRFMiddleware`` ужесточает default cookie:
> ``HttpOnly`` + ``SameSite=strict`` + ``Secure`` (production).

### Pre-fix проблемы

* ``httponly=False`` — cookie readable из JavaScript → XSS-based
  token theft → session hijack.
* ``SameSite=lax`` — разрешает cross-site GET-initiated requests
  с cookie (CSRF через ``<a ping>``, ``<img src>``, ``<form method=GET>``).
* ``Secure`` — вычислялся через legacy ``settings.secure.cookie_secure``
  (отсутствует в ``SecureSettings``), fallback ``True``.

### Post-fix invariants

| Attribute | Value | Зачем |
|---|---|---|
| ``HttpOnly`` | ✓ | Cookie не readable из JS — XSS-resistant. |
| ``SameSite`` | ``strict`` | Cookie НЕ отправляется на cross-origin запросы — CSRF-resistant. |
| ``Secure`` | ``settings.app.environment == "production"`` | TLS-only в prod. |

Production deployment **обязан** иметь ``APP_ENVIRONMENT=production``
(или эквивалент через pydantic-settings env loading) — иначе
``Secure`` flag не сработает.

### Ограничения

* ``SameSite=strict`` блокирует cookie при cross-origin navigation
  (top-level redirect, link click). Для банковской шины — допустимо
  (нет cross-origin embed use-case'ов).
* ``HttpOnly`` ломает JavaScript-driven CSRF token refresh —
  клиенты должны читать token из cookie через server-side endpoint.

---

## Public path allowlist

> ``DEFAULT_PUBLIC_PATH_PREFIXES`` в
> :mod:`src.backend.entrypoints.middlewares.auth_required`.

### Текущий список (cycle 33)

| Prefix | Зачем |
|---|---|
| ``/health``, ``/healthz``, ``/readyz``, ``/livez`` | Liveness/readiness probes (k8s, ALB). |
| ``/metrics`` | Prometheus scrape. |
| ``/asyncapi`` | AsyncAPI spec (S97 W2). |
| ``/docs``, ``/redoc``, ``/openapi.json`` | Swagger UI / API docs (S97 W2). |
| ``/static``, ``/favicon.ico`` | Static assets. |
| ``/api/v1/auth/methods`` | List available auth methods (Login page). |

**``/api/v1/auth/login`` УДАЛЁН** из allowlist (B-04 fix). Защищён
``LoginStepUpMiddleware`` (step-up token + rate-limit).

### Правила изменения

* Каждое добавление в allowlist = явный code-review approval.
* ``OPTIONS`` preflight bypass — внутри ``AuthRequiredMiddleware``
  (не в allowlist), см. ``auth_required.py:147-148``.

---

## Operational checklists

### Pre-deployment (production)

* [ ] ``APP_ENVIRONMENT=production`` (для ``Secure`` cookie flag).
* [ ] ``REDIS_URL`` доступен (для ``RedisRateLimiterChecker``).
* [ ] Frontend обновлён для ``X-Step-Up-Token`` flow (Sprint 37 B-task).
* [ ] Streamlit Login page поддерживает ``X-Step-Up-Token`` header
      (Sprint 37 B-task).

### Monitoring

* Метрики: ``security.auth.login_step_up.denied{missing_token,rate_limit}``
  (counter) — алерт на rate > 100/min sustained.
* Logs: ``security.auth.ratelimit.rate_limit_exceeded`` —
  warning level, отправляется в SIEM.

### Incident response

* Brute-force detected → ``redis-cli KEYS 'login_stepup:ip:*'`` →
  block IP на WAF layer.
* ``503 Service Unavailable`` spike → check Redis health,
  ``REDIS_FAILOVER_ENABLED=true`` для automatic recovery.