# ADR-0057 — Pure ASGI Middleware Chain

* Статус: Accepted (Sprint 3, К5 W3, 2026-05-13)
* Связано с: V15 R-V15-7 (FastStream/APScheduler/Temporal стек), V15 Security
  Constraints; PLAN.md V18.1 §S3 К5 W3 шаг 3.

## Контекст

Текущая FastAPI middleware-цепочка собирается через ``app.add_middleware(...)``
со starlette-стилем BaseHTTPMiddleware. Это имеет несколько проблем:

* BaseHTTPMiddleware **переписывает request body** в memory — проблема для
  multipart uploads > 100 MiB (Wave 8 RAG /upload).
* BaseHTTPMiddleware **проглатывает StreamingResponse** — невозможно
  применить streaming PII redaction (Wave К1 step 4 streaming filter).
* **Порядок middleware** определяется порядком регистрации — неявно;
  нет proof-checking на correctness.

Целевая цепочка (K5 W3 + V15):
``correlation_id → tenant_context → audit → waf → rate_limit → idempotency``.

## Решение

1. **Pure ASGI middleware** — все 6 middleware (idempotency, rate-limit,
   correlation-id, error-envelope, tenant-context, audit, waf) переписаны как
   pure ASGI callable, принимающее ``scope, receive, send`` и проксирующее
   через self.app. Никакого ``BaseHTTPMiddleware``.

2. **Декларативная регистрация** — ``setup_pure_chain_middlewares(app)`` в
   ``entrypoints/middlewares/setup_middlewares.py``. Порядок зафиксирован
   explicitly:
   ```python
   def setup_pure_chain_middlewares(app: FastAPI) -> None:
       app.add_middleware(CorrelationIdMiddleware)
       app.add_middleware(TenantContextMiddleware)
       app.add_middleware(AuditMiddleware)
       app.add_middleware(WafMiddleware)
       app.add_middleware(RateLimitMiddleware)
       app.add_middleware(IdempotencyMiddleware)
   ```

3. **Feature-flag для миграции** — ``ASGI_PURE_CHAIN=True`` (default
   ``False``) переключает между legacy и pure chain. Default-off до
   staging-smoke; default-on в Sprint 5 R2 после coverage ≥ 70% и
   resilience-suite green.

4. **Backwards compat** — ``setup_middlewares(app)`` остаётся как fallback;
   все existing tests гоняются против legacy chain до Sprint 5.

5. **Streaming-aware** — IdempotencyMiddleware и AuditMiddleware
   используют ``send_wrapper`` pattern (не ``response.body_iterator =
   iterator()``), что позволяет StreamingResponse проходить без in-memory
   аккумуляции.

## Последствия

* `+` Streaming uploads > 100 MiB работают без OOM (Wave 8 RAG /upload).
* `+` Streaming PII redaction в response (Wave К1 W1 step 4) применима
  через AuditMiddleware send-wrapper.
* `+` Порядок middleware explicit; не зависит от import-order.
* `+` Pure ASGI совместимо с Granian / Hypercorn без BaseHTTPMiddleware
  performance-penalty (-20% throughput, измерено в Wave 7).
* `−` Migration: 6 middleware × ~50 LOC переписывания = 300 LOC; legacy
  оставлен до Sprint 5 как fallback.
* `−` Тесты middleware требуют ``TestClient`` с lifespan-enabled scope; не все
  legacy fixtures совместимы (требует update).

## Альтернативы рассмотрены и отклонены

* **Starlette BaseHTTPMiddleware с patches** — отклонено: streaming-проблема
  не решается без полного переписывания.
* **Hypercorn lifespan-only middleware** — отклонено: Hypercorn не default
  runner (Granian — основной).
* **Connexion / fastapi-utils middleware** — отклонено: добавляет зависимости
  без явной пользы.

## CI gates (Sprint 3 К5 W3)

* ``tests/asgi/test_pure_chain.py`` — 3 теста: default-off (legacy),
  flag-on (pure chain), middleware order verification.
* ``tools/checks/check_layers.py`` — запрещает прямой import
  ``BaseHTTPMiddleware`` в production-коде.
* ``make pr`` — composite (ci + docs).

## Roadmap

* **Sprint 3 W3 (текущий)** — pure chain implementations + feature-flag.
* **Sprint 5 R2** — staging-smoke → ``ASGI_PURE_CHAIN=True`` в production.
* **Sprint 6** — удаление legacy ``setup_middlewares`` после coverage ≥ 70%.
