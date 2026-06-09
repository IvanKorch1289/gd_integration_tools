# Итерация 5: Документация, CI/CD, мёртвый код, зависимости

## 5.1 Документация и навигация — 7/10
**Плюсы:** Diátaxis-структура (15 tutorials, 20+ runbooks), 52 ADR с INDEX.md, ARCHITECTURE.md V22 (L1-L10, GAP-аудиты), README отличный (545 строк), CLAUDE.md фантастический (463 строки), CLI-навигация (make targets, graphify), русский язык docstrings, Google-style.
**Минусы:** 14 000+ сгенерированных `.rst` закоммичены в репо (должны генерироваться в CI). `CONTRIBUTING.md` отсутствует. ~20 ADR без статуса. 649 docstring-нарушений в allowlist. Битые ссылки в tutorials. Graphify требует ручного `graphify update .`.

## 5.2 CI/CD — 7/10
**Плюсы:** 15 workflows (test, lint, type, security, chaos, perf, api-fuzz, zap, sbom, ai-eval, ai-pr-review, docs, release). Cancel-in-progress, caching (uv, Sphinx doctrees, Docker). Security: pip-audit blocking, OWASP ZAP blocking, SBOM+cosign. Chaos через toxiproxy. Pre-prod gate 38 проверок.
**Минусы:** Flaky tests — 0 защиты (нет rerun/quarantine). Release — муляж (dry-run, нет PyPI publish; semantic-release настроен на `main`, а не `master`). ZAP/api-fuzz/perf-gate сканируют `localhost:8000` без backend. AI PR Review — фикция (`print('PASS')`). 10/38 pre-prod warn-only, 6 skipped. pytest-xdist не задействован в CI. Нет pre-commit CI workflow. Bandit/safety/gitleaks/trivy — warn-only.

## 5.3 Мёртвый код и дублирование — 6/10
**Плюсы:** Ruff чист (F401/F811/F841 — all passed). Vulture — только 8 срабатываний.
**Минусы:** Unreachable code в `sms.py`. ~142 строки закомментированных блоков. `ai_processors.py` (1164 строки) — god-object, ADR-0102 разбил, но исходный файл жив. `_LegacyMultimodalRAGService` — dummy. AI Gateway steps 1-2 scaffold. Banking RPA stubs. Два PluginLoader (legacy + V11). Два SagaLRAProcessor (in-memory vs persistent). Два HTTP-клиента (HttpClient legacy + HttpxClient). Feature-flags с просроченными sunset: `api/v1` (sunset 2026-01-01), `httpx_unified_transport`, `route_loader_hot_reload`. Закомментированные extras: `ai-voice`, `embeddings-fastembed-legacy`.

## 5.4 Зависимости — 6/10
**Плюсы:** Lazy-import паттерн отличный (296 файлов), ADR-документирован. Единый HTTP (httpx), retry (tenacity), DI (svcs). uv lock, pinned versions, 25 extras для opt-in.
**Минусы:** Core раздут — 92 зависимости, включая `polars`, `duckdb`, `dask`, `motor`, `elasticsearch`, `qdrant-client`, `pypdf`, `markitdown`, `presidio-analyzer` (должны быть в extras). Дубли в манифесте: `pendulum` ×2, `presidio-analyzer` ×3. Три cache-библиотеки в core (`cachetools`, `diskcache` с CVE, `aiocache` POC). Два rate-limiter'а (`pyrate-limiter` + `RedisRateLimiter`). Редундантный `pybreaker` extra. `uv.lock` устарел на 2 дня. Core deps без импортов: `grpc-interceptor`, `cloudevents`, возможно `uvloop`.

## 5.5 Интеграции — 7/10
**Плюсы:** СКБ-Техно, DaData, LDAP/AD, Express BotX, Telegram skeleton, AI-провайдеры, FastStream (Kafka/RabbitMQ/Redis), NATS JetStream, S3 multipart, webhook HMAC, adaptive timeout, WAF-routing.
**Минусы:** Webhook outbound — нет retry/idempotency без опционального RPACallPolicy. Нет generated clients из OpenAPI (только spec-импорт). S3 — нет unified LocalFS fallback. NATS — нет CB/retry/pool. Message replay — in-memory dict. BaseExternalAPIClient — retry делегирует в HttpClient, CB не оборачивает явно.

## 5.6 Тесты — 6/10
**Плюсы:** Все уровни кроме e2e. Testkit с HAR recorder, chaos-фикстурами, mTLS/SAML helpers. Property-based (hypothesis), perf (locust/k6), chaos (toxiproxy). Авто-регистрация фикстур через pytest entry-points.
**Минусы:** Покрытие 51% при gate 75%. E2E пустые (2 файла, 0 тестов). pytest-xdist не задействован в CI. 10 pre-existing flaky failures. 25+ модулей без единого теста. Нет factory-boy/faker. Нет pytest-mock (454 raw unittest.mock).

## Библиотеки из web search
- `vulture` — dead code detection (уже используется, но можно усилить)
- `deptry` — проверка unused/missing dependencies (уже используется)
- `uv lock` strategies — keep lock fresh, reduce core dependencies
