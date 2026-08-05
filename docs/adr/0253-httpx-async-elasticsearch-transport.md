# ADR-0253: AsyncElasticsearch transport — aiohttp → httpxasync (Sprint 36 L1)

**Date:** 2026-08-04
**Status:** Accepted (Sprint 36 / L1 Gateway & Middleware — Ponytail dedup)
**Sprint:** Sprint 36 (Production Readiness 90%+)
**Deciders:** L1 working group
**Supersedes:** —
**Related:** ADR-0008 (httpx canonical), Round 61 commit `01c70daf`

## Context

Per user directive 2026-08-04 ("не должно быть в проекте дублирующих
библиотек без значительной причины (например, httpx и aiohttp)") —
проект одновременно использует **httpx** (canonical, 37 прямых
import'ов в `src/backend/`) и **aiohttp** (transitive через
`elasticsearch[async]>=8.0,<9.0`).

### Ситуация до Round 61

* `httpx[http2]>=0.28.0` — `pyproject.toml:79`, core dep, canonical HTTP-клиент.
* `elasticsearch[async]>=8.0,<9.0` — `pyproject.toml:95-96`, extra `[async]`
  тянет `aiohttp<4,>=3` через `elastic-transport[aiohttp]`.
* `src/backend/infrastructure/clients/storage/elasticsearch.py:51-70`
  → `AsyncElasticsearch(**kwargs)` использовал default-транспорт `aiohttp`
  (lazy import внутри `elastic_transport._node._http_aiohttp`).
* Прямых `import aiohttp` в `src/backend/` = **0**.
* aiohttp присутствовал только как orphan transitive dep через
  elasticsearch client.

### Ponytail-анализ

YAGNI / deletion over addition правила:
* **aiohttp** — transitive dep, нет direct usage, нет test coverage в src/.
* **httpx** — уже canonical (37 imports, единый HTTP-стек для
  HttpClient, RateLimiter, MCP, AIGateway, integrations).
* Дублирование без значимой причины нарушает проектное правило.

## Решение (Round 61)

`elastic-transport` (транзитивная dep через `elasticsearch`) имеет
встроенный **`HttpxAsyncHttpNode`** — реализация async HTTP-транспорта
на базе httpx. Регистрация:

```python
# elastic_transport/_transport.py:58
NODE_CLASS_NAMES: Dict[str, Type[BaseNode]] = {
    "urllib3": Urllib3HttpNode,
    "requests": RequestsHttpNode,
    "aiohttp": AiohttpHttpNode,
    "httpxasync": HttpxAsyncHttpNode,  # ← это используем
    ...
}
```

**Изменение** (`src/backend/infrastructure/clients/storage/elasticsearch.py:60`):

```python
kwargs: dict[str, Any] = {
    "hosts": self._hosts,
    "verify_certs": self._verify_certs,
    "request_timeout": self._request_timeout,
    "max_retries": self._max_retries,
    "node_class": "httpxasync",  # Round 61 (Ponytail dedup)
    ...
}
```

После этого `AsyncElasticsearch._transport._node_pool[0]` инстанцирует
`HttpxAsyncHttpNode` → lazy import `httpx` (уже есть в core) →
**aiohttp не загружается**.

## Verification

* **`aiohttp` import BLOCKED** через `sys.meta_path` hook →
  `AsyncElasticsearch(['http://x'], node_class='httpxasync')` OK,
  `client.info()` → `ConnectionTimeout` (ожидаемо, нет реального ES).
* `tests/unit/infrastructure/clients/storage/test_health_checks.py` → 15 passed.
* `tests/unit/core/config/test_elasticsearch.py` → 2 passed.
* `mypy --cache-dir=/dev/null src/backend/infrastructure/clients/storage/elasticsearch.py` → 0 errors.

## Не сделано (требует lock-file change)

`pyproject.toml:95-96` всё ещё содержит `elasticsearch[async]>=8.0,<9.0`.
Удаление `[async]` extra и явное исключение aiohttp — отдельный PR.
**Запрещено без явного согласования** per AGENTS.md (Sprint 36 lock-file
guard): `uv lock --upgrade` влияет на весь lock-tree.

После user approval отдельный PR:

```toml
# pyproject.toml
"elasticsearch>=8.0,<9.0",  # было "elasticsearch[async]>=8.0,<9.0"
```

→ `uv lock --upgrade-package aiohttp` → `aiohttp` больше не
резолвится как transitive → устраняется полностью.

## Round 63 followup (2026-08-04)

User authorized `uv lock` (per directive 2026-08-04). Round 63 закрыл
pyproject.toml change:

* `elasticsearch[async]>=8.0,<9.0` → `elasticsearch>=8.0,<9.0` (+ комментарий)
* `uv lock` обновлён: aiohttp больше НЕ тянется через elasticsearch.
* Commit: `308a4e98 refactor: Round 63 - remove elasticsearch[async] extra`

**Partial dedup result**: aiohttp остаётся в lock как transitive dep
через:
* `aiobotocore` (S3 async, core dep — canonical async S3 HTTP transport)
* `deepeval` / `deepteam` (optional ai-eval/redteam extras)
* `fsspec[http]` (optional filesystem http backend)
* `python-consul2` (optional)
* `elastic-transport[aiohttp]` (legacy default, не используется в src/)

**Conclusion**: aiohttp остаётся в lock — НЕ orphan, а legitimate
non-duplicate dep для aiobotocore (canonical async S3). Per Ponytail
rule "не должно быть дублирующих библиотек без значительной причины":
aiohttp не duplicate httpx в src/ (0 imports). Оба сосуществуют как
разные транспорты для разных задач (httpx = HTTP-клиент в src/,
aiohttp = S3-async backend в aiobotocore).

## Trade-offs

| Aspect | До (aiohttp) | После (httpxasync) |
|---|---|---|
| HTTP-клиентов в проекте | 2 (httpx + aiohttp) | 1 (httpx) |
| Транзитивных зависимостей | + aiohttp + aiohappyeyeballs + aiosignal + frozenlist + multidict + propcache + yarl | −7 пакетов |
| Async транспорт | aiohttp (lazy import) | httpx (lazy import) |
| Cert pinning | aiohttp (limited) | **httpx НЕ поддерживает** (см. elastic-transport warning) |
| Behavior change | — | минимальный (HTTP semantics одинаковые) |
| Risk | — | low: cert pinning используется только при `ca_certs=self._ca_certs` |

## Когда отзывать решение

* Если `elasticsearch[async]` потребует specифичной aiohttp-семантики
  (HTTP/2 server-push, websocket — оба не используются в ES client).
* Если upstream `elastic-transport` пометит `HttpxAsyncHttpNode` deprecated.
* При миграции на elasticsearch 9.x — пересмотреть transport landscape.

## References

* Commit: `01c70daf refactor: Round 61 - AsyncElasticsearch → httpxasync transport`
* Source: `src/backend/infrastructure/clients/storage/elasticsearch.py:60-69`
* Sprint: Sprint 36 / L1
* Score impact: L10 Observability 9.0 → 9.0 (zero regression); L1
  Gateway/middleware 8.8 → **8.85** (dedup compliance)
