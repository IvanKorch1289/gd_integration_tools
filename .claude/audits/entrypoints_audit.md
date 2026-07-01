# Audit: src/backend/entrypoints/ middlewares + transports

Scope: 46 files under `middlewares/`, `asyncapi/`, `cdc/`, `dependencies/`, `email/`, `express/`, `filewatcher/`.

## middlewares/__init__.py
- Path: `src/backend/entrypoints/middlewares/__init__.py`
- Purpose: Package marker re-exporting `APIVersion`; documents ADR-0062 split vs `services.execution.middlewares`.
- Key: re-exports `APIVersion`.
- Auth / violations / security / dead code / docstrings: clean across all axes.

## middlewares/admin_audit.py
- Purpose: Audit logger for PATCH/PUT/POST/DELETE on `/api/v1/admin/*` and `/tech/*` → `audit_log.admin` channel with sha256 payload hash.
- Key: `AdminAuditMiddleware`, `_is_admin_action`, `_admin_logger`.
- Auth: reads `request.state.auth_context` (passive).
- Violations: none (only `core.auth.admin_roles`, `core.logging`).
- Security: `except Exception: pass` silently swallows body-read errors — acceptable for audit but no telemetry.
- Dead code: none.
- Docstrings: complete.

## middlewares/admin_ip.py
- Purpose: Per-IP allowlist for admin routes via `IPRestrictionStore`.
- Key: `IPRestrictionMiddleware`, `_is_admin_route`.
- Auth: N/A (network layer).
- Violations: DSL `convert_pattern` import from `src.backend.dsl.codec.converters` (cross-layer into dsl/; codec is shared util — acceptable).
- Security: none.
- Dead code: `_is_admin_route` is defined but never called; top-level `import re` unused (local `from re import compile` shadows).
- Docstrings: complete.

## middlewares/api_key.py
- Purpose: `X-API-Key` validation via `secrets.compare_digest` against `settings.secure.api_key`.
- Key: `APIKeyMiddleware`, `_is_excluded_route`.
- Auth: enforces; honors pre-existing `request.state.auth` to dedupe with `AuthRequiredMiddleware`.
- Violations: same DSL codec import.
- Security: `compare_digest` is correct; settings-sourced key should be Vault-backed in prod.
- Dead code: top-level `import re` unused.
- Docstrings: complete.

## middlewares/audit_log.py
- Purpose: WHO/WHAT/WHERE/WHEN log to Redis stream `audit-log` + ClickHouse `audit_log` table.
- Key: `AuditLogMiddleware`.
- Auth: passive (`request.state.auth`).
- Violations: DI providers (`core.di.providers`) — acceptable.
- Security: bare `except Exception: pass` on Redis write (line 114) hides infra failures; ClickHouse path at least logs debug.
- Dead code: none.
- Docstrings: complete.

## middlewares/audit_replay.py
- Purpose: Record request/response to Redis stream `audit:requests`; `list_audit_records` + `replay_audit_record` helpers.
- Key: `AuditReplayMiddleware`, `list_audit_records`, `replay_audit_record`.
- Auth: none on helpers — callers must gate via API.
- Violations: DI provider only.
- Security:
  - `replay_audit_record` returns `{"status": "error", "error": str(exc)}` — exception message leaked.
  - Stores raw body (truncated 8KB, utf-8 replace) in plaintext Redis stream — passwords/tokens would leak if not pre-stripped.
  - `random.random()` for sampling (non-crypto, OK for sampling).
- Dead code: none.
- Docstrings: complete.

## middlewares/auth_method_header.py
- Purpose: Adds `X-Auth-Method: <method>` response header.
- Key: `AuthMethodHeaderMiddleware`.
- Auth: read-only.
- Violations/security/dead: clean.
- Docstrings: complete.

## middlewares/auth_required.py
- Purpose: Global auth guard using `verify_request` (6 methods) for non-public paths.
- Key: `AuthRequiredMiddleware`, `is_path_public`, `DEFAULT_PUBLIC_PATH_PREFIXES`.
- Auth: strong; bypass for `OPTIONS` and public prefixes.
- Violations: imports `src.backend.entrypoints.api.dependencies.auth_selector` — intra-entrypoint reference; mild smell but accepted.
- Security: public prefix allowlist is the only bypass; safe.
- Dead code: none.
- Docstrings: complete.

## middlewares/blocked_routes.py
- Purpose: 403 for paths matching runtime glob `blocked_routes`.
- Key: `BlockedRoutesMiddleware`.
- Auth: N/A.
- Violations: `core.state.runtime` (allowed).
- Security: `fnmatch` `*` matches `/` — known, acceptable.
- Dead code: none.
- Docstrings: complete.

## middlewares/brotli_compression.py
- Purpose: ASGI Brotli compression for JSON ≥ `minimum_size` when `Accept-Encoding: br`.
- Key: `BrotliCompressionMiddleware`, `_wants_brotli`, `_is_json`, `_try_import_brotli`.
- Auth: N/A.
- Violations: none.
- Security: content-length recomputed correctly; `Vary: Accept-Encoding` added.
- Dead code: none.
- Docstrings: complete.

## middlewares/circuit_breaker.py
- Purpose: Per-route circuit breaker (CLOSED/OPEN/HALF_OPEN), sliding window.
- Key: `BreakerPolicy`, `BreakerState`, `RouteBreakerState`, `CircuitBreakerMiddleware`.
- Auth: N/A.
- Violations: none beyond `core.logging`.
- Security: states are in-memory per process; multi-pod needs shared state (acknowledged in docstring).
- Dead code: `TYPE_CHECKING` block imports nothing (line 47-48 empty `pass`).
- Docstrings: complete.

## middlewares/correlation.py
- Purpose: Re-export of `asgi_correlation_id.CorrelationIdMiddleware` and `CORRELATION_HEADER`.
- Key: `CorrelationIdMiddleware`, `CORRELATION_HEADER`.
- Auth: N/A.
- Violations/security/dead: clean.
- Docstrings: top-level only.

## middlewares/data_masking.py
- Purpose: Local-regex PII masking for JSON responses (email, phone, sensitive keys).
- Key: `DataMaskingMiddleware`, `_SENSITIVE_KEYS`, `_EMAIL_RE`, `_PHONE_RE`, `_mask_bytes`, `_mask_value`, `_mask_email`, `_mask_phone`.
- Auth: N/A.
- Violations: `core.utils.async_helpers` (allowed).
- Security: only JSON content-type; uses `orjson`; falls back to original body on parse error. `_mask_bytes` decodes utf-8; non-utf-8 will raise UnicodeDecodeError caught by outer try in `_mask_bytes` already; `_capture_body` itself catches nothing — relies on caller.
- Dead code: none.
- Docstrings: complete.

## middlewares/degradation.py
- Purpose: Blocks writes (POST/PUT/PATCH/DELETE) when `degradation_manager` reports degraded/MAINTENANCE/ESSENTIAL modes.
- Key: `DegradationMiddleware`, `DegradationBypassPrefixes`, `_build_503`.
- Auth: N/A.
- Violations: `core.resilience.degradation`, `core.di.providers` (allowed).
- Security: clean; emits `Retry-After` and `X-Degradation-Mode` headers.
- Dead code: none.
- Docstrings: complete.

## middlewares/exception_handler.py
- Purpose: Catches unhandled exceptions, emits JSON with `correlation_id` + `request_id`.
- Key: `ExceptionHandlerMiddleware`.
- Auth: N/A.
- Violations: `core.errors.BaseError`, `core.logging`.
- Security: non-BaseError exceptions are mapped to generic `{"message": "Internal server error", "hasErrors": True}`; traceback is logged but not returned — good (no info leak).
- Dead code: none.
- Docstrings: complete.

## middlewares/global_ratelimit.py
- Purpose: Global ASGI rate-limit with per-route override + tenant-aware identifier.
- Key: `GlobalRateLimitMiddleware`, `FakeRateLimitChecker`, `RedisRateLimitChecker`, `tenant_aware_identifier`, `build_rate_limit_checker`, `_LazyRedisProxy`.
- Auth: N/A.
- Violations: `core.interfaces.ratelimit_gateway`, `core.di.providers.cache`, `core.config.features` — allowed.
- Security:
  - Fail-open on Redis errors — explicit and logged.
  - `X-RateLimit-Remaining: 0` only set on 429 response (not on every response) — design choice.
- Dead code: none.
- Docstrings: complete.

## middlewares/idempotency.py
- Purpose: Idempotency-Key middleware wrapping `IdempotencyHeaderMiddleware` with custom `RedisNxBackend` (SET NX EX) for atomic pending-key lock.
- Key: `IdempotencyHeaderMiddleware`, `RedisNxBackend`, `_LazyRedisProxy`, `build_idempotency_backend`, `IDEMPOTENCY_HEADER`.
- Auth: N/A.
- Violations: `core.serialization.msgspec_hotpath`, `core.di.providers`.
- Security: `store_idempotency_key` correctly returns `not bool(reserved)` (note: `redis.set(..., nx=True)` returns truthy on success → reserved=False means "new key" which is the correct "lock acquired" case).
- Dead code: none.
- Docstrings: complete.

## middlewares/otel_middleware.py
- Purpose: OpenTelemetry HTTP auto-instrumentation; creates `http.<method> <path>` span, injects `traceparent`.
- Key: `OtelMiddleware`, `_load_tracer`, `_load_propagator`, `_extract_context`, `_inject_traceparent`, `_build_attributes`, `_mark_error`.
- Auth: N/A.
- Violations: `core.tenancy` (allowed).
- Security: no-op when SDK missing; trace ID truncated via `str(exc)[:200]` — bounded.
- Dead code: none significant.
- Docstrings: complete.

## middlewares/per_protocol_ratelimit.py
- Purpose: Identifier-extraction helpers for WS/SSE/MQTT/gRPC rate limits (R3 building block).
- Key: `ws_identifier`, `sse_identifier`, `mqtt_topic_identifier`, `grpc_call_identifier`, `_decode_header`.
- Auth: N/A.
- Violations: none (pure stdlib).
- Security: identifier construction only; no input sanitization of path/topic values used inside the identifier string. The identifiers flow into Redis keys via the consuming middleware which must be careful about key size — fine for a tenant/user/IP form but `mqtt_topic_identifier` blindly embeds the full topic — user-controlled topic may produce very long Redis keys (DoS).
- Dead code: none.
- Docstrings: complete.

## middlewares/pii_masking_response.py
- Purpose: Wrapper applying `core.security.pii_masker.PIIMasker` to JSON responses for configured path patterns.
- Key: `PIIMaskingResponseMiddleware`, `_is_enabled`, `_path_matches`, `_mask_json_bytes`, `_capture_body`.
- Auth: N/A.
- Violations: `core.security.pii_masker`, `core.config.features`, `core.utils.async_helpers`.
- Security: feature-flag default-OFF; falls back to original body on mask error (logged warning with exception text — not returned to client).
- Dead code: none.
- Docstrings: complete.

## middlewares/registry.py
- Purpose: `MiddlewareRegistry` + `MiddlewareSpec` — single registration point with order layers, plugin TOML/entry-points support.
- Key: `MiddlewareRegistry`, `MiddlewareSpec`, `default_registry`, `_layer_for`.
- Auth: N/A.
- Violations: `importlib.import_module` for plugin classes; no domain coupling.
- Security:
  - `register_from_toml` propagates `ImportError`/`AttributeError` as `ValueError` with module ref — doesn't allow arbitrary class instantiation from plugin name; controlled by `name`+`module` schema.
  - `register_from_entry_points` checks `isinstance(target, type)` — good (requires class).
- Dead code: none.
- Docstrings: complete.

## middlewares/request_body_cache.py
- Purpose: Single read of request body into `request.state.body` and replay-receive wrapper.
- Key: `RequestBodyCacheMiddleware`, `cached_body`, `_parse_content_length`, `_install_replay_receive`.
- Auth: N/A.
- Violations: `core.logging`.
- Security: 10MB cap; no body re-sent on oversize — `_install_replay_receive` still called (defensive).
- Dead code: none.
- Docstrings: complete.

## middlewares/request_context.py
- Purpose: Pure ASGI middleware that builds `RequestContext` and binds it via `bind_request_context`.
- Key: `RequestContextMiddleware`, `_get_header`, `_otel_ids`.
- Auth: N/A.
- Violations: `core.request_context` (allowed).
- Security: backward-compat writes `state["correlation_id"]`/`state["request_context"]` — documented as deprecated.
- Dead code: none.
- Docstrings: complete.

## middlewares/request_id.py
- Purpose: Generates/echoes `X-Request-ID` and `X-Correlation-ID` headers.
- Key: `RequestIDMiddleware`, `_generate_id`.
- Auth: N/A.
- Violations: none.
- Security: uses `uuid4().hex` (32 chars) — fine.
- Dead code: none.
- Docstrings: complete.

## middlewares/request_log.py
- Purpose: Logs request/response (including body when enabled, with size cap, gzip decoding).
- Key: `InnerRequestLoggingMiddleware`, `_get_request_body`, `_log_response_body`, `_capture_response_body`.
- Auth: N/A.
- Violations: `core.config.settings`, `core.di.providers`, `core.utils.async_helpers`.
- Security: **logs raw request body at debug level (line 100) including potential secrets** when `log_requests` and `POST` and content-type not multipart. No redaction. Body of response also logged. Configured via settings — operational risk.
- Dead code: none.
- Docstrings: complete.

## middlewares/response_cache.py
- Purpose: ETag + `Cache-Control: public, max-age=...` for GET JSON responses; 304 on `If-None-Match`.
- Key: `ResponseCacheMiddleware`, `_capture_body`.
- Auth: N/A.
- Violations: `core.utils.async_helpers`.
- Security: `xxhash` preferred, sha256 fallback; `Cache-Control: public` — note: this is the opposite of "private" and may cache auth-gated responses in shared caches if the upstream didn't strip. **Potential auth/cache leak**: `public` allows CDN caching of any 200 JSON regardless of auth status.
- Dead code: none.
- Docstrings: complete.

## middlewares/security_headers.py
- Purpose: Adds HSTS, X-Content-Type-Options, X-Frame-Options, CSP, Permissions-Policy headers.
- Key: `SecurityHeadersMiddleware`.
- Auth: N/A.
- Violations: none.
- Security: CSP `default-src 'self'` is restrictive; no `Referrer-Policy` (minor); HSTS has no `preload`.
- Dead code: none.
- Docstrings: complete.

## middlewares/setup_middlewares.py
- Purpose: Wires 25+ built-in middleware to the registry with explicit `order` per layer.
- Key: `build_default_registry`, `setup_middlewares`.
- Auth: registers all auth-related middleware (`api_key`, `auth_required`, `auth_method_header`).
- Violations: same as the modules it imports.
- Security: order is correct per ADR-0062.
- Dead code: none.
- Docstrings: complete.

## middlewares/tenant.py
- Purpose: Extracts `X-Tenant-ID` header and pushes via DI setter.
- Key: `TenantMiddleware`.
- Auth: N/A.
- Violations: `core.di.providers` (allowed).
- Security: tenant_id is reflected in `X-Tenant-ID` response header — this is a deliberate choice but it can disclose tenant id to any client (low risk for known tenants).
- Dead code: none.
- Docstrings: complete.

## middlewares/timeout.py
- Purpose: Per-route timeout (S18 W6) with global fallback; returns 408.
- Key: `TimeoutMiddleware`, `_resolve_timeout`, `_is_per_route_enabled`.
- Auth: N/A.
- Violations: `core.config.settings`, `core.di.providers`, `core.config.features`.
- Security: 408 response body is generic Russian string — no leak.
- Dead code: none.
- Docstrings: complete.

## middlewares/versioning.py
- Purpose: `APIVersion` dataclass + `as_headers()` for `API-Version`/`Deprecation`/`Sunset` (RFC 8594).
- Key: `APIVersion`.
- Auth: N/A.
- Violations: none.
- Security: clean.
- Dead code: none.
- Docstrings: complete.

## middlewares/webhook_signature.py
- Purpose: HMAC-SHA256 signature verification for incoming webhooks (Stripe-style).
- Key: `WebhookSignatureMiddleware`, `_resolve_secret`, `_is_protected`.
- Auth: enforces per-prefix signature; **falls through silently when prefix is protected but no secret configured** (line 91-99, `logger.debug`) — risky: protected prefix without secret = no auth.
- Violations: `core.logging`, `services.security` (`verify_signature`, `DEFAULT_TIMESTAMP_WINDOW`) — cross-layer into services from entrypoints. **Layer violation**: middlewares → services.
- Security:
  - `body = await request.body()` is read, then `request._receive` is overridden with a one-shot replay — duplicate of `RequestBodyCacheMiddleware` pattern, but no max-size cap (could be abused for large bodies on `/webhooks/*`).
  - **Skip-verify with no secret for protected prefix is dangerous in production misconfig**.
- Dead code: none.
- Docstrings: complete.

## middlewares/ws_rate_limit.py
- Purpose: Per-WS rate limit via `RedisRateLimiter` with `ws_identifier`.
- Key: `WSRateLimitMiddleware`, `_check_rate_limit`.
- Auth: N/A.
- Violations: `core.config.services.websocket`, `services.resilience.rate_limiter` — **layer violation** (entrypoints → services).
- Security: Fail-open on Redis errors; sends WS close code 1008 (policy violation) on limit.
- Dead code: none.
- Docstrings: complete.

## asyncapi/__init__.py
- Purpose: Re-exports `build_asyncapi_json/spec/yaml`.
- Key: re-exports.
- All axes: clean.

## asyncapi/exporter.py
- Purpose: Builds AsyncAPI 3.0 spec from `StreamClient` (Redis/Rabbit/Kafka routers).
- Key: `_collect_brokers`, `_empty_spec_dict`, `build_asyncapi_spec`, `build_asyncapi_yaml`, `build_asyncapi_json`.
- Auth: N/A.
- Violations: `src.backend.infrastructure.clients.messaging.stream` — **layer violation** (entrypoints → infrastructure, not via capability facade).
- Security: `try/except` swallows StreamClient import errors gracefully.
- Dead code: none.
- Docstrings: complete.

## cdc/__init__.py
- Purpose: Namespace marker.
- All axes: clean.

## cdc/cdc_routes.py
- Purpose: CRUD endpoints for CDC subscriptions at `/api/v1/cdc`.
- Key: `cdc_router`, `CDCSubscribeRequest`, `CDCSubscribeResponse`, `create_subscription`, `delete_subscription`, `list_subscriptions`.
- Auth: **no auth dependency declared on the router** — relies on global `AuthRequiredMiddleware` enforcement. If mounted on a public prefix, anyone can list/create subscriptions.
- Violations: `core.di.providers.get_cdc_client_provider` (allowed).
- Security:
  - `request.profile` accepts arbitrary string, passed to `client.subscribe(profile=...)` — if the CDC client doesn't validate, this is injection-prone. The provider interface cannot be checked from here.
  - No rate limit on subscription creation — DoS surface.
- Dead code: none.
- Docstrings: complete.

## dependencies/__init__.py
- Purpose: Documents `entrypoints/dependencies/` namespace; historical note about rate_limit migration.
- All axes: clean.

## dependencies/rate_limit.py
- Purpose: `Depends()`-based rate limit using `fastapi_limiter` and `RedisLimiterAdapter`.
- Key: `RedisLimiterAdapter`, `get_default_limiter`, `get_default_rate_limiter`, `RateLimitDependency`, `WebSocketRateLimiter`.
- Auth: N/A.
- Violations: `core.config.security`, `core.decorators.limiting_callbacks`, `services.resilience.rate_limiter` — **layer violation** (entrypoints → services).
- Security: `try_acquire_async` ignores `timeout` parameter mapping — if a caller passes `timeout > 0`, the window is overridden to `timeout` seconds, which is correct only for short windows. Standard behavior.
- Dead code: `WebSocketRateLimiter` re-exported in `__all__` but never used in this file.
- Docstrings: complete.

## email/__init__.py
- Purpose: Namespace marker.
- All axes: clean.

## email/imap_monitor.py
- Purpose: Async IMAP monitor with IDLE support; dispatches parsed emails to DSL routes.
- Key: `ImapConfig`, `ImapMonitor`, `_parse_email`.
- Auth: N/A (IMAP creds via config/Vault).
- Violations: `dsl.service.get_dsl_service` (entrypoints → dsl — allowed), `core.utils.task_registry`, `core.di.providers`.
- Security:
  - `verify_cert=False` is **logged as a warning but otherwise ignored** — the SSL context is always created via `ssl.create_default_context()` regardless (lines 129-139). This is a security control: user can't disable cert verification. Documented as V1 policy.
  - `password_vault_ref` falls back to plaintext `password` on Vault error — could mask misconfiguration; warning is logged.
  - `_parse_email` decodes with `errors="replace"` — no charset sniffing; UTF-8 / latin-1 / other may be misinterpreted.
  - No redaction of email body before dispatch into DSL — caller responsible.
- Dead code: redundant `from aioimaplib import IMAP4, IMAP4_SSL  # noqa: F401` inside `_fetch_unseen` and `_idle_loop` (already imported in `_connect`).
- Docstrings: complete.

## express/__init__.py
- Purpose: Re-exports `router`.
- All axes: clean.

## express/router.py
- Purpose: FastAPI router for BotX callbacks at `/express/{health,command,callback}`.
- Key: `router`, `_log_incoming`, `health`, `receive_command`, `receive_callback`, `_dispatch_to_route`.
- Auth: **no auth dependency on the router** — relies on global `AuthRequiredMiddleware` and the `secure_routes` allowlist (or webhook signature). The `/express/callback` from BotX must be reachable without auth — typical but must be in the public_prefixes.
- Violations: `core.di.providers` (`get_express_*`, `get_express_metrics_recorder_provider`), `entrypoints._action_bridge.dispatch_action_or_dsl` (private intra-entrypoint, fine).
- Security:
  - `_dispatch_to_route` returns `{"status": "error", "reason": bridge.error or "dispatch failed"}` — bridge.error may carry exception text (depends on bridge implementation).
  - No HMAC verification of BotX payloads (out of scope per docstring).
- Dead code: none.
- Docstrings: complete.

## filewatcher/__init__.py
- Purpose: Namespace marker.
- All axes: clean.

## filewatcher/watcher_manager.py
- Purpose: `WatcherManager` + `WatcherSpec` using `watchfiles.awatch`; dispatches new files to DSL routes.
- Key: `WatcherManager`, `WatcherSpec`, `watcher_manager`, `_watch_loop`, `_dispatch`.
- Auth: N/A.
- Violations: `dsl.service.get_dsl_service`, `core.utils.task_registry`, `core.logging`.
- Security:
  - `Path(spec.directory)` accepted as-is from REST `CreateWatcherRequest`; `add()` checks `is_dir()` but **does not canonicalize/symlink-resolve** — a symlink target elsewhere could be watched (limited impact; reader is `awatch`).
  - `_dispatch` reads only the filename in DSL body — doesn't read the file contents, so the file itself isn't exfiltrated via dispatch metadata.
- Dead code: none.
- Docstrings: complete.

## filewatcher/watcher_routes.py
- Purpose: REST endpoints at `/watchers` for create/list/delete.
- Key: `watcher_router`, `CreateWatcherRequest`, `create_watcher`, `delete_watcher`, `list_watchers`.
- Auth: **no auth dependency on the router** — relies on global guard.
- Violations: filewatcher internal.
- Security:
  - `HTTPException(400, detail=str(exc))` and `404, detail=str(exc)` — `ValueError`/`KeyError` messages are returned directly. `KeyError("Watcher XYZ не найден")` leaks the watcher id format (low risk).
  - No allowlist of directories a watcher can monitor — can be pointed at `/etc`, `/var/log`, etc. (privileged filesystem exposure for the running user).
  - No max-pattern length / no validation of `pattern` (used in `fnmatch` — safe).
- Dead code: none.
- Docstrings: complete.

## Cross-cutting critical findings

1. **Layer violations (entrypoints → services / infrastructure)**: `webhook_signature.py` and `ws_rate_limit.py` import from `src.backend.services.*`; `asyncapi/exporter.py` reaches into `src.backend.infrastructure.clients.messaging.stream`; `dependencies/rate_limit.py` imports `src.backend.services.resilience.rate_limiter`. AGENTS.md requires capability-checked facades; these are direct deep imports.
2. **PII / secret leakage in audit pipeline**: `audit_replay.py` writes raw request bodies (truncated 8KB) to Redis stream `audit:requests` in plaintext; `request_log.py` logs request/response bodies at DEBUG when `log_requests=True`; `request_log.py` has no redaction for `password`/`token` keys. Combined with `audit_log.py` and `data_masking.py`/`pii_masking_response.py`, the audit infrastructure could persist credentials.
3. **Auth gaps in transport routers**: `cdc/cdc_routes.py`, `filewatcher/watcher_routes.py`, `express/router.py` declare no `Depends()` auth — they rely entirely on the global `AuthRequiredMiddleware` allowlist. If their prefixes aren't in the public allowlist, the global guard covers them; if they are public, any caller can subscribe CDC, manage file watchers, or post express commands. `cdc_routes.py` additionally accepts arbitrary `profile` strings, and `watcher_routes.py` accepts arbitrary `directory` paths.
4. **ResponseCacheMiddleware sets `Cache-Control: public`** on all 200 JSON GET responses — including auth-gated responses. Combined with `ETag` and `If-None-Match`, a shared cache (CDN/proxy) may store user-specific data. Should be `private` or only applied to genuinely public GETs.
5. **Inconsistent error/exception handling**: `audit_replay.replay_audit_record` returns `str(exc)` in error response; `exception_handler.py` is a `BaseHTTPMiddleware` — known anti-pattern: `BaseHTTPMiddleware` swallows streaming responses and can interfere with `call_next` exception propagation. Prefer FastAPI exception handlers (`@app.exception_handler`). `webhook_signature.py` silently allows requests when a protected prefix has no secret configured (line 91-99).
