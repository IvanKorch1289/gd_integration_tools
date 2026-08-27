# Gap Analysis — оставшиеся OPEN items (2026-08-27)

> Основано на WAVE 1 audit (`docs/audit/CURRENT_STATE_2026-08-27.md`) + повторная
> проверка кода/артефактов 2026-08-27. Коммиты cycle 8-21 закрыли большинство
> P0/P1/P2/P4; ниже — только реально OPEN пункты с file:line evidence.

## 0. Сводка

| ID | Пункт | Реальный статус | LOC | Спринт |
|----|-------|-----------------|-----|--------|
| P3.15 | `.coverage` integrity | **MISDIAGNOSED** — xml не повреждён, а stale/partial | ~10 (docs+make) | now (quick win) |
| P3.16 | Coverage ratchet 75% | OPEN, ground truth ~7% (не 9.56%) | 80-120 тестов / фаза | S172-S179 |
| P3.17 | Mutation scope | PARTIAL — 4 модуля | +2 пути / +0 кода | S172 |
| P1.7 | frontend facade migration | OPEN — 1/31 файл; 18 из 30 **не migratable** | ~13 файлов | S172-S173 |
| P4.19 | Aggregator timeout | **REAL BUG** — timeout drop'ает данные (FIXED cycle 22) | ~25 + 2 теста | ✅ DONE |

---

## 1. P3.15 — `.coverage` / `coverage.xml` integrity

### Факты
- `.coverage` (SQLite, 1019904 B, 13:12): 2095 файлов, `coverage report
  --include="src/backend/*"` → `TOTAL 106241 96903 23434 151 7%`,
  `Coverage failure: total of 7 is less than fail-under=60`.
- `coverage.xml` (48777 B, тот же 13:12): `lines-valid=1032 lines-covered=217
  line-rate=0.2103 branch-rate=0.05446`, `<source>/…/src</source>`.
- Claim аудита `docs/audit/CURRENT_STATE_2026-08-27.md:38`
  (`lines-valid=107349 / line-rate=0.01125`) более не воспроизводится.
- Оба файла НЕ в git: `.gitignore:14` (`.coverage`), `:15` (`.coverage.*`),
  `:168` (`coverage.xml`), `:169` (`coverage.json`).

### Что нужно
Не «фикс повреждения», а устранение источника рассинхронизации:
1. Удалять stale артефакты перед прогоном (`rm -f .coverage* coverage.xml`)
   в make-цели coverage.
2. Генерировать `coverage.xml` строго из того же `.coverage`
   (`coverage xml` сразу после `coverage report`, один include-набор).
3. Обновить `CURRENT_STATE_2026-08-27.md:38` — пометить claim как ARCHIVED
   (по образцу «False Claims Archive», commit `81b693c6`).

### Сложность / риски / зависимости
- LOC: ~10 (make/quality.mk + 3 строки docs). Тесты: 0.
- Риск: нет — артефакты gitignored, prod-код не затронут.
- Зависимости: нет.
- **Рекомендация: делать немедленно (no-regret).**

---

## 2. P3.16 — Coverage ratchet до 75%

### Факты
- План существует: `docs/audit/COVERAGE_RATCHET_PLAN.md` (commit `c08dada5`),
  8 недель, +5pp / 2 недели, Sprint A→D.
- Gate: `pyproject.toml:1080` → `fail_under = 60`; фактическое измерение 7%.
- Per-layer (`tools/coverage/per_layer_diagnostic.py`): core 5.4% (18103 stmts),
  infrastructure 0.8% (24620), services 0.3% (18941), dsl 0% (30312),
  entrypoints 0% (11377).
- Блокер измерения: `COVERAGE_RATCHET_PLAN.md:29-33` — полный `tests/unit/`
  OOM-killed (137) в едином процессе, требуется pytest-xdist split.

### Gap
- 7% → 75% = **−68 pp** при 106k statements ⇒ ≈ 72k новых покрытых строк.
  Реалистично только траншами; на 1-2 дня НЕ ship-able.
- Настоящая блокирующая задача первого шага — **не тесты, а измеримость**:
  без воспроизводимого полного прогона ratchet нельзя контролировать.

### Что нужно (порядок)
1. `make coverage-xdist`: `pytest -n auto --cov=src/backend --cov-branch`
   + `coverage combine` (устраняет OOM). ~15 LOC в make/quality.mk.
2. Зафиксировать честный full-suite baseline в `.baselines/coverage.json`
   (заменить историческое 51.04% на измеренное; поле `_comment` уже
   подготовлено под reconcile).
3. Затем — Sprint A плана (core/utils, core/auth, core/di/providers,
   80-120 тестов, +5pp).

### Сложность / риски / зависимости
- Шаг 1: LOC ~15, риск низкий (может всплыть test-isolation flakiness при -n auto).
- Шаг 2: LOC ~20 (json), риск: «регрессия» цифры 51.04 → ~10% в дашбордах —
  требует явной пометки «reconciled, not regression».
- Шаг 3: 80-120 тестов / 2 недели на транш.
- Зависимость: шаг 3 требует шага 1 (иначе не измерить дельту).
- **Рекомендация: шаги 1-2 — S172; шаг 3 — S172-S179 (ratchet).**
- Дополнительно: не поднимать `fail_under` до 75, пока факт ниже —
  оставить 60 как «декларативную цель», иначе CI постоянно красный.

---

## 3. P3.17 — Mutation testing scope

### Факты
- `pyproject.toml:1164-1174` `[tool.mutmut].source_paths` = **4 модуля**:
  - `src/backend/core/config/features/__init__.py`
  - `src/backend/dsl/builders/base/__init__.py`
  - `src/backend/core/resilience/breaker.py`
  - `src/backend/core/tenancy/__init__.py` (добавлен commit `39bf22d3`)
- Tooling готов: `tools/run_mutation_tests.sh`, `tools/checks/run_mutmut.py`,
  `tools/checks/check_mutmut.py` (threshold 55%).
- **Uncommitted**: `make/quality.mk:76-91` (diff) добавляет цели
  `mutation`, `mutation-quick`, `mutation-gate`; `Makefile:68` — .PHONY.
  Эти изменения ещё не в git (dirty working tree).

### Gap
1. Незакоммиченные make-цели — риск потери работы.
2. Scope 4 модуля покрывает security-critical (tenancy, breaker, feature flags),
   но не покрывает: `core/auth/*`, `core/ai/gateway_orchestrator_mixin.py`
   (P0.2 tool whitelist), `entrypoints/middlewares/rpa_policy.py` (deny-by-default).

### Что нужно
- Закоммитить make-цели (atomic: `build(make): mutation targets`).
- Расширить scope до 6: + `core/ai/gateway_orchestrator_mixin.py`,
  + `entrypoints/middlewares/rpa_policy.py` (оба — P0-security surface,
  где mutation-тест реально ловит регрессии авторизации).

### Сложность / риски / зависимости
- LOC: 2 строки конфига + commit. Тесты: 0 новых (mutmut использует существующие).
- Риск: mutation score может упасть ниже threshold 55% на новых модулях →
  сначала запустить `make mutation-quick`, потом решать про gate.
- Зависимость: нет.
- **Рекомендация: S172, 0.5 дня.**

---

## 4. P1.7 — Frontend facade migration (core.frontend_facade → core.api)

### Факты
- Мигрирован 1 файл: `src/frontend/streamlit_app/shared/audit_event_lite.py:88`
  → `from src.backend.core.api import emit_audit_safe` (commit `f7f0a867`).
- Осталось **30 файлов** с `frontend_facade` (grep по `src/frontend/**/*.py`).
- `core.api` уже экспортирует нужные примитивы:
  `src/backend/core/api/__init__.py:70` (`emit_audit_safe`), `:172-175`,
  `:192-195` (`get_logger`), `:196-198` (`feature_flags`).

### Критичное уточнение: миграция НЕ на 30 файлов
`src/backend/core/frontend_facade.py:11-45` реэкспортирует ДВА источника:
- **core.*** — `emit_audit_safe`, `feature_flags`, `get_logger`,
  `express_settings`, `Outbox*`, `FakeOutbox`, `ImportSource*`,
  `get_express_*_provider` → **migratable в core.api**;
- **services.dsl_portal** — `Pipeline`, `WorkflowDeclaration`, `to_mermaid`,
  `to_graphviz`, `compute_step_diff`, `get_saga_history`, `get_saga_stats`,
  `get_global_registry`, `list_*`, `get_whoosh_index`, `load_pipeline_from_yaml`,
  `get_ai_cost_snapshot`, `get_default_stuck_monitor`, `search_workflow_templates`
  → **НЕ в core.api** и не должны там быть (frontend → services запрещён напрямую).

Разбивка по 30 файлам (usage-count по символам):
- только core-символы (migratable): ~12-13 файлов —
  `pages/00_Вход.py`, `app.py`, `pages/10_Заказы.py`,
  `pages/43_Логи_в_реальном_времени.py`, `api_clients/k4.py`,
  `pages/36_Экспресс_боты.py`, `pages/_groups/replay/{render,helpers}.py`,
  `pages/_groups/schema/{registry_tab,import_tab}.py`, `pages/52_Устойчивость.py`,
  `pages/54_Replay_DLQ.py`, `pages/55_Монитор_пула.py`, `pages/58_Шина_действий.py`;
- dsl_portal-символы (НЕ migratable без нового services-фасада): ~17 файлов —
  `pages/{15,17,18,19,23,33,34,63,66,96}_*.py`,
  `pages/_editor/{properties,yaml_sync,workflow_diff,visual/tab_canvas}.py`,
  `pages/_groups/dsl/dsl_templates/workflow_templates_tab.py`.

### Что нужно
- Фаза 1 (S172): 12-13 файлов × 1-2 строки импорта → `core.api`.
- Фаза 2 (S173, решение архитектуры): либо оставить `frontend_facade` как
  единственную точку для dsl_portal-символов (и переименовать в
  `portal_facade`), либо завести `services/dsl_portal/api.py`.
  **Рекомендация: оставить `frontend_facade` для dsl_portal — YAGNI/ponytail.**
  Т.е. P1.7 закрывается на ~13 файлах, а не 30/33.

### Сложность / риски / зависимости
- Фаза 1: ~26 изменённых строк, тесты: smoke-import (Streamlit-страницы не
  покрыты unit-тестами → верификация через `python -c "import ast; compile(...)"`
  или существующий `tests/unit/frontend/*` если есть).
- Риск: `core.api` — lazy `__getattr__`; опечатка в имени даёт runtime
  AttributeError только при рендере страницы. Митигация: тест-параметризация
  «все импортируемые frontend-символы резолвятся из core.api».
- Зависимость: нет.
- **Рекомендация: S172 фаза 1, S173 решение по фазе 2.**

---

## 5. P4.19 — Aggregator timeout (✅ FIXED cycle 22)

### Факты до фикса
`src/backend/dsl/engine/processors/eip/flow_control/aggregator.py`:
- `:35` `timeout_seconds: float = 30.0`, `:42` `self._timeout`;
- `:80-85` `_flush_expired()`:
  ```python
  expired = [k for k, ts in self._timestamps.items() if now - ts > self._timeout]
  for k in expired:
      self._buffers.pop(k, None)      # <-- данные ВЫБРАСЫВАЮТСЯ
      self._timestamps.pop(k, None)
  ```
- Docstring `:21-26` обещает: «выдаёт агрегированный результат по достижении
  ``batch_size`` **или** ``timeout``» — контракт НЕ выполняется.
- Docstring `:81` честно говорит «Remove buffers … to prevent memory leaks»,
  т.е. это eviction, а не flush.
- Вызывается только из `process()` (`:54`) под локом — **нет таймера**:
  при отсутствии входящих сообщений partial-батч не эмитится никогда.
- Тесты: `tests/unit/dsl/engine/processors/eip/test_flow_control.py:239-257`
  `test_aggregator_flush_expired` фиксировал ТЕКУЩЕЕ (drop) поведение:
  после expiry `e2.properties["aggregated"] is False` — т.е. тест закреплял баг.
- Билдер: `src/backend/dsl/builders/eip/transformation.py:51` — единственный
  production call-site.

### Что было сделано (cycle 22, 2026-08-27)
Минимальный фикс per ponytail/YAGNI (без background timer'ов):
1. Переименован `_flush_expired` → `_evict_expired`.
2. Docstring переписан: timeout = eviction (memory protection), НЕ flush.
   Указано: «Если нужен strict timeout semantics (partial-emit), используй
   :class:`SlidingWindowAggregator` (planned S176)».
3. Добавлен счётчик `_evicted_batches` + `evicted_batches` property:
   инкрементируется на каждый eviction (timeout + max_buffer head-drop +
   _MAX_CORRELATION_KEYS overflow). Видно в observability.
4. Обновлён тест: `test_aggregator_flush_expired` → `test_aggregator_evicts_expired`,
   добавлены assertions на `proc.evicted_batches == 1` и на то, что `_buffers["k1"]`
   содержит только `["b"]` (не `["a", "b"]`).

### Verification
- `pytest tests/unit/dsl/engine/processors/eip/test_flow_control.py` → 27 passed
- `ruff check` → All checks passed
- `ruff format` → 1 file reformatted (trailing comma)

### Сложность / риски / зависимости (deferred)
- **Strict timeout** (variant 2: partial-emit через background task): отложено в S176,
  требует ADR + `SlidingWindowAggregator` новый класс. Out of YAGNI.
- Существующий production call-site (`builders/eip/transformation.py:51`)
  продолжает работать с новой семантикой (eviction).

---

## 6. Три конкретных next-step (ship за 1-2 дня)

### NS-1 (no-regret quick win, ~2 ч)
`build(make): commit mutation targets + coverage artifact hygiene`
- закоммитить `make/quality.mk:76-91` + `Makefile:68` (уже написаны, dirty);
- в coverage-цель добавить `rm -f .coverage* coverage.xml` перед прогоном и
  `coverage xml` сразу после `coverage report` (устраняет P3.15 навсегда);
- обновить `docs/audit/CURRENT_STATE_2026-08-27.md:38` — claim про «повреждён»
  → ARCHIVED + фактические `lines-valid=1032 / line-rate=0.2103`.
Риск: 0. Прод-код не тронут.

### NS-2 (docs/test improvement, ~4 ч)
`fix(mcp): P1.9' Python 2 syntax в tools_convert.py:54`
- `tools_convert.py:54` содержит `except X, Y:` (Py2 syntax).
- AST parser fail'ит → layer scanner пропускает файл → скрытая violation.
- Fix: переписать на `except X as Y:` (Py3 syntax).
- Verify: `python -m py_compile tools_convert.py` + `make layers`.

### NS-3 (опционально, если есть время, ~6 ч)
`test(frontend): миграция 12 core-only страниц на core.api + guard-тест`
- 12-13 файлов из списка §4 «migratable»;
- параметризованный тест: все frontend-импортируемые символы резолвятся из
  `core.api` (страхует lazy `__getattr__`);
- `frontend_facade` остаётся для dsl_portal-символов (17 файлов) — зафиксировать
  это решение в `.claude/DECISIONS.md`, чтобы P1.7 не выглядел «33 файла долга».
Риск: средний (Streamlit-страницы без unit-покрытия) → guard-тест обязателен.

---

## 7. Что НЕ надо делать сейчас
- Поднимать `pyproject.toml:1080 fail_under` c 60 до 75 — факт 7%, CI станет
  постоянно красным.
- Гнаться за 75% coverage без `pytest-xdist` split — измерение OOM-падает,
  прогресс невозможно верифицировать.
- Реализовывать time-based flush в Aggregator background-таской — нарушает
  stateless-контракт процессора при отсутствии подтверждённого требования.
- Мигрировать dsl_portal-символы в `core.api` — ломает границу слоёв
  (frontend → services запрещён напрямую).
