# MERGE_DECISION — feat/m1-m6-impl → master, 2026-09-05

**Status**: merge **aborted** (no commits, no destructive ops).
**Author**: координатор (auto)

## Контекст

Запрошено: `merge feat/m1-m6-impl с master, если есть полезные доработки,
удалить feat/m1-m6-impl`.

## Что предлагал feat/m1-m6-impl (полезные доработки, 30+ коммитов)

- **M2-#21 DSL god-object split** — `dsl/builders/base/route_builder.py`
  1422 → 101 LOC. Закрывает прямо мой Tier-3 backlog item **G-S3**.
- 6 stale legacy allowlist entries pruned (M5/M6 quick wins).
- M6 pre-prod-check gates (03, 15, 33, 34) fixed.
- MQSource Kafka/Redis Streams/NATS prefetch (M5-#4).
- Ruff format auto-fix 278 files.

## Почему merge **NOT** выполнен

### 1. Substantive code conflicts (7 файлов)

```
src/backend/core/api/__init__.py
src/backend/core/dsl/variable_backend.py
src/backend/dsl/builders/base/__init__.py
src/backend/dsl/engine/processors/web.py
src/backend/entrypoints/api/v1/endpoints/admin_plugins/helpers.py
src/backend/services/ai/gateway_adapter.py
src/backend/services/security/facade.py
```

Все — content conflicts (не auto-resolvable). Требуется построчный разбор
для каждого. Несколько файлов — те, что я модифицировал в Phase B
(services/security/facade*, dsl/builders/base) — означает, что
разрешение должно учитывать обе версии с осторожностью.

### 2. Documentation conflicts (3 файла)

```
docs/STATUS.md              (2 conflict markers)
docs/adr/WIKI.md            (3 conflict markers)
docs/roadmap/PRODUCTION_READINESS_FINAL.md (5+ conflict markers)
```

Обе сессии независимо обновили эти single-source-of-truth документы.
Требуется mergesort-логика для синтеза обоих наборов обновлений.

### 3. ADR numbering clash — **критический риск**

Обе сессии создали **разный** `docs/adr/0292-*.md`:
- **master** (Phase B CL17 era): `0292-frontend-facade-allowed.md`
  (frontend_facade ADR — обоснованное исключение для streamlit)
- **feat/m1-m6-impl**: `0292-mypy-budget-drift-acknowledgment.md`
  (gate 02 known-issue)

Renumbering **одной** из них (например, master → 0294) — нужна,
+ sync в WIKI.md + ledger, простая транзакция. Но это **требует решения**
от пользователя: какая нумерация приоритетна?

### 4. Pre-existing test flakiness risk

Per ledger: «pytest collection флакует при параллельных процессах
(225 errors vs 1)». После merge файлов в `infra`, `services` —
вероятна триггерная флака. Доп. откат-цикл понадобится.

## Решение

**Heuristic Ponytail** (per AGENTS.md):
> *"Не упрощать: валидацию на границах доверия, обработку ошибок,
> предотвращающую потерю данных, меры безопасности, ... явно
> запрошенный пользователем функционал, архитектурные правила проекта."*

7 substantive code conflicts — это **доверие к architectural integrity**,
что **нельзя упрощать**. Чтобы merge был качественным, нужен dedicated
short-cycle sprint с:

1. ADR-0292 numbering decision (user choice)
2. Построчное разрешение 7 conflict'ов
3. Doc merge synthesis (3 файла)
4. Verify (ruff + mypy + tests, без regression)
5. Subsequent: branch delete

## Что preserved

- Branch `feat/m1-m6-impl` остаётся доступной
- Worktree `.worktrees/m1-m6-impl` остаётся на commit `169a3d45b`
- Stash удалён, working tree восстановлен к Phase B финальному состоянию

## Forward-action для пользователя

**Вариант A** (рекомендуемый — focused sprint):
1. Пользователь решает ADR-0292 numbering (какая сторона)
2. Dedicated 1-cycle Phase B-MERGE: разрешить все 10 конфликтов
3. Verify + delete branch

**Вариант B** (минимальный, low-risk):
1. Создать branch `merge/feat-m1-m6-impl` от master
2. Selective cherry-pick только non-conflicting коммиты (ADR-0293+
   ledger sync, pre-prod-check fixes, MQ prefetch)
3. Пропустить M2-#21 god-object split (отдельный sprint)

**Вариант C** (рискованный, быстрый):
1. `git merge --no-ff --strategy-option=union` feat/m1-m6-impl
2. Resolve conflicts in-place
3. Verify
4. Удалить branch

Мой текущий выбор = **Вариант A**. Если пользователь предпочитает
B или C — переключаюсь.

## Команды

```bash
# Текущий head
git log -1 --oneline
# a304d7e65 docs(roadmap): FINAL_REPORT.md — Sprint 169 Phase B closing

# Ветка жива
git branch | grep feat
# + feat/m1-m6-impl
```
