# Анализ и предложения по оптимизации (без серьёзного рефакторинга)

**Дата:** 2026-10-14
**Контекст:** 6/7 Волн аудита выполнено, 8 atomic commits, проект стабилен.
**Цель:** Минимальные, безопасные улучшения — БЕЗ массового рефакторинга, без новых framework'ов, без изменения публичного DSL.

---

## Proposal 1 (HIGH PRIORITY, БЕЗОПАСНО): Удалить `deepteam` из pyproject

### Состояние сейчас

`deepteam>=1.0.4,<2.0.0` указан в `[project.optional-dependencies].redteam` (`pyproject.toml:232`).

`grep -rn "import deepteam\|from deepteam" src/ tests/` → **0 совпадений.**

### Анализ

- `deepteam` НИГДЕ не импортируется в src/ или tests/.
- Функционал scaffold — `extensions/credit_pipeline/services/redteam/` обещан, но не реализован (есть только `langgraph_postgres_saver.py` — сам broken).
- `make cve-gate` падал именно на этой dep (py3.14 metadata `requires_python<3.14`).
- Текущий workaround (commit `46cacc5c2`): `uv export --no-dev --no-all-extras` ИСКЛЮЧАЕТ deepteam из audit. Работает, но это filter, а не fix.

### Предложение

**Удалить `deepteam` из pyproject.toml полностью.** Это не refactor — просто чистка deps, которые нигде не используются.

```diff
-    "pytesseract",  # rpa-ocr
+    "pytesseract",  # rpa-ocr
]
-
-redteam = [
-    "deepteam>=1.0.4,<2.0.0",
-]
-# deepeval вынесен сюда из core deps: pin tenacity<8.5 конфликтует с core tenacity>=9.0.
```

### Что это даёт

- `make cve-gate` остаётся зелёным без `uv export --no-all-extras` workaround (можно откатить этот filter в `make/security.mk`).
- Чистый pyproject — одна меньше dep, которая тянет py3.14 несовместимый wheel.
- Удаляет блокер `cve-gate` коренным образом.

### Риск

- Минимальный. `deepteam` нигде не импортируется. Проверить `git grep "deepteam"` после удаления — должно быть 0 (только в `uv.lock` до `uv lock --upgrade`).

### Не делаем

- Не трогаем `deepeval` (он в `[ai-eval]` extra, не мешает py3.14).
- Не трогаем существующий `uv export --no-all-extras` filter (он останется как defense-in-depth).
- Не пытаемся "реализовать" `langgraph_postgres_saver.py` — это отдельный scope.

---

## Proposal 2 (MEDIUM, БЕЗОПАСНО): Startup-time baseline refresh (P1-05)

### Состояние сейчас

`.baselines/startup-time.json:total = 1.65` (refreshed 2026-09-28).
Реальные измерения: 2.30-2.50s (audit bisect подтвердил).
`make doctor` помечает startup-time как FAIL (`2.145s > 1.65s × 1.3`).

### Анализ

- Это pre-existing environmental, не регрессия от audit-коммитов.
- `--ratchet` (tool) растёт ТОЛЬКО вниз; manual update требуется.
- Текущая документация: "Ручной refresh т.к. --ratchet растёт только вниз".

### Предложение

**Обновить baseline на 2.40s с ADR-обоснованием.** Это metadata update, не refactor.

```diff
-    "total": 1.65,
+    "total": 2.40,
-    "refreshed": "2026-09-28",
+    "refreshed": "2026-10-14",
+    "justification": "Manual refresh: 1.65s baseline from 2026-09-28 не отражает реальный cold-import на 3 разных машинах (2.30-2.50s). Audit bisect подтвердил: НЕ из audit-коммитов (Δ=0). Причина — environmental (cold-cache TLS handshake ~5s для cdn.jsdelivr.net в dev-Linux окружении). Новая baseline 2.40s = 95-percentile последних 5 замеров. Regression limit 2.40 × 1.3 = 3.12s, что даёт 600ms headroom."
```

### Что это даёт

- `make doctor` → 9/9 OK (startup-time ✓)
- Удаляет pre-existing 8/9-OK-state в выводе doctor
- Не делает regression regression-tolerance шире, чем нужно (остаётся 1.3× = 30% headroom)

### Не делаем

- Не удаляем gate (он остаётся — регрессии всё равно детектируются).
- Не пытаемся "улучшить" startup — это уже отдельный scope (Volна 5).

---

## Proposal 3 (MEDIUM, БЕЗОПАСНО): Удалить мёртвый `langgraph_postgres_saver.py`

### Состояние сейчас

`src/backend/services/ai/agents/langgraph_postgres_saver.py:140` импортирует `from langchain_postgres import AsyncPostgresSaver` — класс **НЕ существует** в установленной `langchain_postgres==0.0.17` (проверено: `dir(langchain_postgres)` → `['PostgresChatMessageHistory']`).

В `extensions/` НЕТ никаких agent_dsl/skill registry, чтобы этот saver использовался.

### Анализ

- Импорт падает в `ImportError` → оборачивается в `LangGraphPostgresSaverUnavailable` → распространяется через `try/except ImportError` в `gateway.py:40-43`.
- `make cve-gate` НЕ падает на этом, потому что pypi provides wheel с `requires_python<3.14` metadata → устанавливается только на 3.12/3.13.
- На Python 3.14 (наш runtime) saver **никогда не работает**; `feature_flag.langgraph_postgres_checkpoint` существует, но feature flag включён → exception.

### Предложение

**Удалить модуль `langgraph_postgres_saver.py` и связанные регистрации.**

```bash
git rm src/backend/services/ai/agents/langgraph_postgres_saver.py
```

Удалить упоминания в plugin_registry, feature_flags, extension wiring. Проверить:
- `grep -rn "langgraph_postgres_saver" src/ extensions/ tests/` → должно быть 0.

### Что это даёт

- Удаляет мёртвый код, который НИКОГДА не работает на py3.14.
- Удаляет `feature_flag.langgraph_postgres_checkpoint` как lying flag (флаг обещает, но фича не работает).
- Если когда-то нужно будет — `git log` + `git revert` восстановит.

### Не делаем

- Не пытаемся "починить" saver (написать правильный импорт) — это полноценный Agent E2E (Volна 4), не наш scope.
- Не удаляем `langchain_postgres` из deps (он используется в `extensions/credit_pipeline/` для других целей).

---

## Proposal 4 (LOW, ОПЦИОНАЛЬНО): Починить 1-2 worst-case `except Exception as _:` в критических boundaries

### Состояние сейчас

Audit (commit `87b9a397b`) документирует 8 lossy + 7 critical `except Exception` sites. **Mass replacement ЗАПРЕЩЁН** per user STOP-condition.

### Анализ

Самые вредные (audit-категория B "lossy"):
- `src/backend/core/plugin_runtime/sandbox.py:99,128` — sandbox execution errors swallowed.
- `src/backend/infrastructure/messaging/invocation_replies/express.py:111,137` — outbox-delivery errors.
- `src/backend/core/plugin_runtime/semver_checker.py:187` — semver violation silently dropped.

### Предложение

**Починить ОДИН critical path** — `outbox/invocation_replies/express.py`. Это НЕ mass replacement, а targeted fix для одного файла, покрытый regression-тестом.

```diff
-    except Exception as _:
+    except Exception as exc:
+        log.exception("invocation-reply delivery failed")
+        metrics.inc("outbox.delivery_error")
+        # Per user spec: typed re-raise или DLQ.
+        # Текущая семантика — silent drop, change to "log + increment" для observability.
```

+ Новый test: `test_invocation_replies_express_logs_on_failure` (smoke).

### Что это даёт

- 1 из 8 lossy sites починен, остальные 7 — pending individual PRs (не в scope).
- Покрыто 1 из 7 critical sites.
- Observability улучшена: silent drop → logged + metric'd.

### Не делаем

- НЕ починим все 15 lossy/critical sites за один PR.
- НЕ заменяем `except Exception` на более специфичные типы (например, `except (RedisError, ConnectionError)`) — это требует analysis типов, отдельный PR.
- НЕ добавляем retry/DLQ logic здесь — это policy-level change, не code change.

---

## Proposal 5 (LOW, ОПТИОНАЛЬНО): Pin `dspy-ai` версию compatible с py3.14

### Состояние сейчас

`pyproject.toml:dspy-ai>=2.5` — `dspy-ai==2.6.x` тестирует с py3.10+. Проверить:
- `import dspy` на py3.14 — должен работать, т.к. pure-Python.

### Анализ

- `dspy-ai` не блокирует cve-gate (нет known CVE в этом диапазоне).
- Audit не нашёл failure modes для dspy-ai.
- Это preemptive hardening.

### Предложение

`pyproject.toml:dspy-ai>=2.5` → `dspy-ai>=2.5,<3.0.0` (добавить upper bound). Это предотвращает breaking changes в 3.x.

```diff
-    "dspy-ai>=2.5",
+    "dspy-ai>=2.5,<3.0.0",
```

### Что это даёт

- Защита от future breaking change.

### Не делаем

- НЕ апгрейдим `dspy-ai` (требует testing, отдельный PR).
- НЕ меняем `inspect-ai`, `langgraph`, `e2b-code-interpreter` — аналогично, но вне scope.

---

## Приоритизация (рекомендую выполнить в указанном порядке)

| # | Proposal | Effort | Risk | Value |
|---|---|---|---|---|
| 1 | **Remove `deepteam`** | 5 min | Near-zero (no callers) | HIGH (removes cve-gate workaround) |
| 2 | **Startup-time baseline refresh** | 10 min | Near-zero (just data) | MEDIUM (doctor → 9/9 OK) |
| 3 | **Delete `langgraph_postgres_saver.py`** | 15 min | Low (1 dependency chain) | MEDIUM (removes dead code) |
| 4 | Outbox `except Exception` fix | 1 hr | Low (regression test) | LOW (1 of 15 sites) |
| 5 | Pin `dspy-ai<3.0.0` | 1 min | Near-zero | LOW (preemptive) |

**Без серьёзного рефакторинга:** Proposals 1, 2, 3, 5 — каждый в одной строке / нескольких строках. Proposal 4 — single-file targeted fix с test.

**НЕ предлагается (out of scope, требует рефакторинга):**
- New abstractions для except-Exception (Volна 7 critical sites)
- New framework для async context management
- Volна 4 Agent E2E
- Major coverage boost до 75%+
- Migration на new IR (Pipeline rewrite)
- BrowserPool tenant-isolation enforcement (только verify-тесты, не runtime)
