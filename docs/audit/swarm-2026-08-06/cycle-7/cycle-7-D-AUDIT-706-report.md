# Cycle-7 / D-AUDIT-706 — RagCachePrewarmer residual cleanup

**Date:** 2026-08-07
**HEAD:** `e3d9c93b` (cycle-7 / D-AUDIT-706 commit)
**Цикл:** 7 (focused) — задача T-C7-06-RAG-PREWARMR-FINAL
**DOCSTRING MARKER:** `cycle-7/D-AUDIT-706`

---

## 1. Задача

**Plan ref:** cycle-4 phase-1/09-rag.md (RAG dead-code) + cycle-5
D-AUDIT-506 fix (закрыл финальный caller).

**Real evidence:**
- `0497be90 refactor(rag): remove dead RagCachePrewarmer (D-A9-02, 197 LOC)`
  удалил `src/backend/services/ai/rag_cache_prewarmer.py`;
- `0fab89d6 fix(cycle-5)` закрыл `T-W1-06` (финальный caller)
  через D-AUDIT-506;
- Оставался **dangling reference** в docstring'е
  `src/backend/services/ai/rag_query_stats.py:5` —
  историческая пометка о dead-code, но всё ещё содержащая имя
  удалённого класса ``RagCachePrewarmer``.

**Fix:**
- (a) найти dangling references → 1 найден (docstring);
- (b) удалить imports в callers (если есть) → **0 imports, 0 call-sites**
  (реальных caller'ов не было после cycle-5);
- (c) удалить class-name mention из docstring + добавить
  cycle-7/D-AUDIT-706 marker как финальный cleanup.

---

## 2. Что сделано

### 2.1 Файл изменён

`src/backend/services/ai/rag_query_stats.py` (1 file, +5/-3 LOC) —
единственное изменение.

```text
$ git diff src/backend/services/ai/rag_query_stats.py
-D-A9-02 fix (cycle 1): ``RagCachePrewarmer`` (ранее ссылался здесь)
-удалён как dead code — никогда не инстанцировался в production lifespan.
+D-A9-02 fix (cycle 1): prewarm-подсистема (ранее ссылавшаяся здесь)
+удалена как dead code — никогда не инстанцировалась в production lifespan.
+D-AUDIT-506 (cycle 5) закрыл финальный caller.
 Модуль продолжает собирать статистику для observability/admin endpoints,
-но prewarm (cycle-5/D-AUDIT-506) больше не используется.
+но prewarm больше не используется. cycle-7/D-AUDIT-706 — финальный cleanup
+dangling references (0 imports, 0 call-sites подтверждено grep'ом).
```

Изменения только в module docstring (строки 1-11). Класс/логика/imports
не тронуты. Русский текст docstring'а сохранён, только rephrase'нут.

### 2.2 Docstring marker

```python
"""Сбор top-N RAG-запросов per-tenant для аналитики и observability.
...
D-A9-02 fix (cycle 1): prewarm-подсистема (ранее ссылавшаяся здесь)
удалена как dead code — никогда не инстанцировалась в production lifespan.
D-AUDIT-506 (cycle 5) закрыл финальный caller.
Модуль продолжает собирать статистику для observability/admin endpoints,
но prewarm больше не используется. cycle-7/D-AUDIT-706 — финальный cleanup
dangling references (0 imports, 0 call-sites подтверждено grep'ом).
"""
```

Docstring на верхнем уровне модуля + docstring marker
`cycle-7/D-AUDIT-706` для traceability.

### 2.3 Аудит references / imports

```bash
$ grep -rE "RagCachePrewarmer" src/ tests/   # class name
No matches found.

$ grep -rE "rag_cache_prewarmer" src/ tests/  # module filename
No matches found.
```

**Verify:**
- 0 references к `RagCachePrewarmer` (class name) в src/ и tests/
- 0 references к `rag_cache_prewarmer` (module filename) в src/ и tests/
- 0 imports
- 0 call-sites

Все остальные `RagCachePrewarmer` / `rag_cache_prewarmer` упоминания —
в `docs/audit/**` (cycle 1-5 historical reports, **НЕ** трогаем — это
архивная документация pre-existing commits).

---

## 3. Runtime verification

### 3.1 Удалённый import (должен fail)

```bash
$ .venv/bin/python -c "from src.backend.services.ai.rag_cache_prewarmer import RagCachePrewarmer"
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    from src.backend.services.ai.rag_cache_prewarmer import RagCachePrewarmer
ModuleNotFoundError: No module named 'src.backend.services.ai.rag_cache_prewarmer'
---EXIT: 1---
```

**Verify:** import fails with `ModuleNotFoundError` (expected, file
deleted in `0497be90`).

### 3.2 Связанный модуль (должен import OK)

```bash
$ .venv/bin/python -c "from src.backend.services.ai.rag_query_stats import RagQueryStatsCollector; print('OK:', RagQueryStatsCollector)"
OK: <class 'src.backend.services.ai.rag_query_stats.RagQueryStatsCollector'>
```

**Verify:** `RagQueryStatsCollector` импортируется чисто (docstring-Only
change не ломает модуль).

---

## 4. Tests

### 4.1 RAG-related regression

```bash
$ .venv/bin/python -m pytest tests/unit/entrypoints/api/v1/endpoints/test_rag_pii_fail_closed.py tests/unit/dsl/engine/processors/ai/ -q --no-header
.....xxxxxxx............................................................  [ 78%]
....................                                                     [100%]
============================= 85 passed, 7 xfailed in 4.98s ==============================
```

**Verify:** 85/85 PASS + 7 xfailed (xfailed — pre-existing DEFER scope,
не связано с D-AUDIT-706).

### 4.2 Module smoke

```bash
$ .venv/bin/python -c "from src.backend.services.ai.rag_query_stats import RagQueryStatsCollector; print('OK:', RagQueryStatsCollector)"
OK: <class 'src.backend.services.ai.rag_query_stats.RagQueryStatsCollector'>
```

---

## 5. Gates (cycle-1 preflight re-run)

| Gate | Baseline | After T-C7-06 | Статус |
|---|---|---|---|
| Layer checker | 175/0 | 175/0 (2278 files) | **PASS** |
| Security allowlist | 27 | 27 | **PASS** |
| Docstring gate | 0 missing | 0 missing (840 files) | **PASS** |
| `s3.py` modified | no | no | **PASS** |
| `uv.lock` churn | 0 lines | 0 lines | **PASS** |
| `gateway_adapter.py:128-129` | present | present (UNTOUCHED) | **PER PLAN** |
| Cycle-6 21+ commits | present | present (HEAD `6ebb482c`) | **PASS** |
| Working tree entries | 47 pre-existing | 37 pre-existing (residual) | **pre-existing residual** |

```text
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 27
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 37 entries (разобраться)   ← pre-existing residual
  [OK]   uv.lock churn — 0 diff lines (pre-existing, не растёт)
  [OK]   s3.py untouched — не modified
```

**Working tree fail** — pre-existing residual от cycle-6 (audit reports
+ untracked new test files вне scope cycle-7), **НЕ** относится к
D-AUDIT-706 (наш diff — 1 файл, +5/-3 LOC, docstring-only).

### 5.1 Docstring gate (post-change)

```bash
$ make check-docstrings MAX_ALLOWED=0
uv virtual environment detected
Running docstring policy check...
Total: 0 missing docstrings in 0 files
Files scanned: 840
docstring policy OK
```

---

## 6. Diff stat

```text
$ git show --stat e3d9c93b
commit e3d9c93b
fix(cycle-7/rag): remove dangling RagCachePrewarmer reference from rag_query_stats docstring (D-AUDIT-706)

 src/backend/services/ai/rag_query_stats.py | 5 ++++-
 1 file changed, 5 insertions(+), 3 deletions(-)
```

**Минимальные изменения:** 1 файл, +5/-3 LOC, docstring-only.

---

## 7. Quality checklist

| Проверка | Результат |
|---|---|
| 0 imports к `RagCachePrewarmer` | ✅ (ModuleNotFoundError) |
| 0 call-sites | ✅ (grep подтвердил) |
| 0 references в src/ и tests/ | ✅ (grep `RagCachePrewarmer\|rag_cache_prewarmer` пустой) |
| Docstring marker `cycle-7/D-AUDIT-706` | ✅ (in module docstring) |
| Русские docstrings не переведены | ✅ (только rephrase, перевод не выполнялся) |
| `except Exception` без concrete handling не тронут | ✅ (не в scope) |
| Layer 175/0 (no growth) | ✅ |
| Allowlist 27 (no growth) | ✅ |
| uv.lock 0 lines (no churn) | ✅ |
| s3.py / blue_green.sh / gateway_adapter.py:128-129 UNTOUCHED | ✅ |
| Cycle-1+2+3+4+5+6 21+ commits не переписаны | ✅ (HEAD `6ebb482c` сохранён, +`e3d9c93b` поверх) |
| `make check-docstrings MAX_ALLOWED=0` PASS | ✅ |
| `.venv/bin/python` для runtime | ✅ |
| git push НЕ выполнен | ✅ |
| `RagQueryStatsCollector` импортируется | ✅ |
| `RagCachePrewarmer` import fails | ✅ |

---

## 8. Выводы

**RagCachePrewarmer final cleanup (D-AUDIT-706) — закрыт:**

1. **0 imports, 0 call-sites, 0 references** в src/ и tests/ — verified
   grep'ом;
2. Docstring в `rag_query_stats.py` обновлён: имя класса удалено,
   добавлен marker `cycle-7/D-AUDIT-706` для traceability;
3. Runtime verification: `.venv/bin/python` import команды подтверждают
   expected fail / pass;
4. RAG-related regression: 85/85 PASS + 7 xfailed (pre-existing DEFER);
5. Все baseline gates зелёные (layer 175/0, allowlist 27, docstrings
   0, uv.lock 0 lines);
6. **Минимальные изменения:** 1 файл, +5/-3 LOC, docstring-only.

Финальная картина cleanup цепочки:

```
0497be90 (cycle 1/D-A9-02)    → удалил RagCachePrewarmer модуль (197 LOC)
0fab89d6 (cycle 5/D-AUDIT-506) → закрыл финальный caller (T-W1-06)
e3d9c93b (cycle 7/D-AUDIT-706) → удалил последний docstring reference + marker
```

---

*Cycle-7 / D-AUDIT-706. 1 file modified (+5/-3 LOC, docstring-only).
0 imports, 0 call-sites verified. ModuleNotFoundError on deleted import
confirmed. 5/6 preflight OK (1 pre-existing residual). No regressions.*
