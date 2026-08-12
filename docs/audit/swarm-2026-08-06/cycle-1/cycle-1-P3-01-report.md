# T-3.1 · cycle-1/P3-01 — replace custom TTL+LRU with `cachetools.TTLCache`

**Date:** 2026-08-06
**Task:** T-3.1 (cycle 1, Phase 3, Wave 3)
**Plan ref:** `docs/audit/swarm-2026-08-06/cycle-1/PHASE-3-PLAN.md` §4
**Finding:** `infra:DOMAIN-P3-001` (`src/backend/infrastructure/cache/rag/embedding_cache.py:17-64`)
**Status:** COMPLETE

## 1. Что изменилось

### 1.1. `src/backend/infrastructure/cache/rag/embedding_cache.py` (rewrite)

- **Было:** 64 LOC, custom `dict[str, tuple[list[float], float]]` + ручной LRU через
  `next(iter(self._store))` + `time.monotonic()` TTL.
- **Стало:** ~50 LOC, `cachetools.TTLCache(maxsize=..., ttl=...)` + `asyncio.Lock`.
- `TTLCache` сам делает TTL-eviction (через `__getitem__` raises `KeyError` на
  expired + auto-remove) и LRU-eviction (через `popitem(last=False)` при `set`).
- Async API сохранён: `get(query)` / `set(query, vector)`, оба корутины.
- `asyncio.Lock` обязателен, т.к. `cachetools.TTLCache` НЕ thread-safe и НЕ
  async-safe (per `cachetools` design, см. §"Caveats" в cachetools docs).
- sha256 key сохранён (`_key()` staticmethod).
- Параметры `ttl_seconds`, `maxsize` сохранены (default 300.0 / 1024).
- `__all__` сохранён.

### 1.2. `tests/unit/infrastructure/cache/rag/test_embedding_cache.py` (new, 10 tests)

- `test_get_missing_returns_none`
- `test_set_and_get_roundtrip`
- `test_get_returns_copy_not_reference`
- `test_ttl_expiration_evicts_entry` — TTL=0.05s + `asyncio.sleep(0.1)`
- `test_lru_eviction_when_maxsize_exceeded` — maxsize=2, insert 3
- `test_maxsize_overflow_does_not_grow_unbounded` — maxsize=3, insert 13
- `test_lru_access_promotes_to_most_recent` — get() обновляет recency
- `test_concurrent_set_get_does_not_corrupt` — 4 параллельных writer+reader
- `test_key_is_sha256_hex` — verify 64-char hex
- `test_defaults_match_baseline` — 300s/1024 сохранены

### 1.3. `tests/unit/infrastructure/cache/rag/__init__.py` (new, empty)

— требуется pytest discovery + match sibling test dir pattern.

## 2. Verification

| Check | Команда | Результат |
|---|---|---|
| `cachetools` import | `grep -nE "from cachetools import" src/backend/infrastructure/cache/rag/embedding_cache.py` | **1 hit** (line 14) |
| uv.lock churn | `git diff --numstat uv.lock` | `0	15	uv.lock` (unchanged from baseline) |
| uv.lock wc -l | `git diff uv.lock | wc -l` | 40 (pre-existing context+headers, 0 new lines) |
| Security allowlist | `grep -cE "^CVE-\|^GHSA-\|^PYSEC-" .security/pip-audit-allowlist.txt` | **35** (no growth) |
| Docstring gate | `make check-docstrings MAX_ALLOWED=0` | **0 missing** (838 files) |
| Layer checker | `python tools/check_layers.py --root src` | **0 new / 175 legacy** (no growth) |
| s3.py untouched | `git status --short src/backend/infrastructure/storage/s3.py` | empty (untouched) |
| Ruff | `ruff check <files>` | All checks passed |
| Mypy | `mypy <file>` | Success: no issues found |
| Tests | `pytest tests/unit/infrastructure/cache/rag/test_embedding_cache.py -v` | **10 passed in 0.88s** |
| Regression | `pytest tests/unit/infrastructure/cache/ -v` | **60 passed** (no regression) |

## 3. Preflight status

```
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 35
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 13 entries (разобраться)
  [FAIL] uv.lock churn — 40 lines (проверить не растёт ли)
  [OK]   s3.py untouched — не modified
```

- **working tree 13 entries:** содержит pre-existing modifications от параллельных
  cycle-1 задач (T-1.4: `redelivery_policy.py`, `multicast.py`; T-1.5:
  `policy_mixin.py`, `gateway_adapter.py`, `test_gateway_pipeline_mixin.py`;
  preflight script `tools/cycle-1-preflight.sh`; cycle-1 docs; `pip-audit.json`).
  Моя задача добавила 1 modification (`embedding_cache.py`) + 2 новых файла
  (`__init__.py`, `test_embedding_cache.py`). **Не моя responsibility** —
  фиксируется в `PREFLIGHT-REPORT.md`.
- **uv.lock 40 lines:** пре-existing 15 deletions (`svcs` пакет удалён).
  `git diff --numstat uv.lock` показывает `0 added, 15 removed` — точно
  совпадает с baseline (T-0.1 PREFLIGHT-REPORT §1). **Не растёт от моих
  изменений** — cachetools уже в core deps (`pyproject.toml:104`).
- **s3.py не тронут:** OK.

## 4. Compliance

| Правило | Статус |
|---|---|
| Не править `uv.lock` | PASS (не тронут) |
| Не править `.security/pip-audit-allowlist.txt` | PASS (35 = 35) |
| Не удалять `except Exception` без handling | N/A (нет `except` в кэше) |
| Не переводить русские docstrings | PASS (все мои docstrings на русском, оригинал сохранён) |
| Docstring marker `cycle-1/P3-01` | PASS (в `embedding_cache.py` module docstring + test file docstring) |
| Не трогать `s3.py` | PASS |
| Не делать broad `# type: ignore` | PASS (нет type: ignore) |
| Layer baseline ≤ 175 / 0 new | PASS (175/0) |
| `git diff uv.lock` не растёт | PASS (15 deletions, как baseline) |

## 5. Diff stat

```
 .../infrastructure/cache/rag/embedding_cache.py    | 50 +++++++++-------------
 1 file changed, 20 insertions(+), 30 deletions(-)
```

Plus new files:
- `tests/unit/infrastructure/cache/rag/__init__.py` (0 bytes)
- `tests/unit/infrastructure/cache/rag/test_embedding_cache.py` (4951 bytes, 10 tests)

**Net source delta:** -30 +20 = **-10 LOC** на `embedding_cache.py` (cachetools.TTLCache
заменил custom dict + monotonic LRU).

## 6. Совместимость (compatibility risk)

**Low.** Async API (`get`/`set` корутины) сохранён 1-в-1. Поведение для
callers идентично (None = miss/expired; LRU по maxsize; TTL по `time.monotonic`).
Внутренняя механика заменена на battle-tested `cachetools.TTLCache` (MIT,
активно поддерживается, уже в `pyproject.toml` core deps).

**Thread-safety нюанс:** `cachetools.TTLCache` НЕ thread-safe. Async-callers
защищены `asyncio.Lock` (соответствует оригинальной архитектуре: `L2SemanticRagCache._embed`
async → нужен `asyncio.Lock`, не `threading.Lock`). ponytail-комментарий в
module docstring объясняет.

## 7. Out of scope (не сделано)

- `pyproject.toml` НЕ тронут (cachetools уже в core deps).
- `uv.lock` НЕ тронут (15 deletions — pre-existing).
- `.security/pip-audit-allowlist.txt` НЕ тронут.
- `src/backend/infrastructure/storage/s3.py` НЕ тронут.
- `src/backend/infrastructure/cache/rag/__init__.py` НЕ тронут (`EmbeddingVectorCache`
  не был в `__all__` 3-tier RAG пакета до моего фикса; остаётся не-exported,
  callers импортируют напрямую через full path).
- `extensions/*` НЕ тронуты.

## 8. Rollback

Revert коммита → custom TTL+LRU восстановлен, все тесты вернутся к старому
поведению (manual dict + monotonic LRU). Без data-loss, без breaking changes.

---

*Dev-агент cycle 1 / T-3.1. Не читал source files за пределами scope
(`embedding_cache.py` + новый test file + pre-existing test в `test_lru_cache.py`/`
test_factory.py` для style match). Не правил uv.lock, allowlist, s3.py, layer baseline.
Docstring marker `cycle-1/P3-01` присутствует. Все русские docstrings оставлены
на русском.*
