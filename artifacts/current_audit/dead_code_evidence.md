# dead_code_evidence.md — доказательная база dead code

**HEAD:** `3b509542e96d89d79df45200d31904cd4fa97947`
**Интерпретатор:** `/home/user/dev/gd_reaudit/.venv/bin/python` (Python 3.14.0)
**Дата замера:** 2026-10-01
**Правило применения:** «grep count ≠ dead code». Для каждого кандидата
проверены семь каналов: static imports, строковые ссылки (registry/decorator/
YAML/TOML), регистрации, entry points, public re-exports, документационные
контракты, динамический DI-резолвинг.

---

## 0. Главный результат: предыдущий отчёт содержал ложные утверждения

Перепроверка на текущем HEAD **опровергла 2 из 6 гипотез** предварительного
отчёта. Это зафиксировано, потому что без этого «dead code ~1110 LOC» выглядело
бы как доказанный результат.

| Утверждение предыдущего отчёта | Факт на HEAD | Вердикт |
|---|---|---|
| `core/services/base_external_api.py` = exact-copy канона (md5 15930cd9) | **Файла не существует.** `ls` → `No such file or directory`; сравнивать sha256 нечего | **FALSE** |
| `dsl/processors/saga_lra_processor/` — legacy-пакет ~811–864 LOC | Единственный файл `__init__.py` = **3 LOC** (шим); 6 mixin-ов уже мигрированы в `engine/processors/` | **FALSE** |
| `InfraLogWriteProcessor` и `FeatureFlagCheckProcessor` — оба «test-only» | Неоднородны: у первого есть живая `@processor("infra_log_write")` регистрация (`infra_log.py:22`), у второго декоратора нет вовсе | **PARTIAL** |

Следствие: заявленные «~1110 LOC безопасного удаления» **не подтверждаются**.
Подтверждённый безопасный объём — **4 LOC** (см. §D).

**Расхождение в документации** (отдельная находка):
- `docs/roadmap/PROD_READINESS_GAPS.md:143` утверждает «`core/services/base_external_api.py` (0 импортёров)» — файл отсутствует.
- `docs/audit/cycle-1/domain-A3-Services.md:527` фиксирует проверку `md5sum` двух путей как «identical» — относится к уже удалённой паре.

---

## A. `core/services/base_external_api.py` — REFUTED, удалять нечего

| Поле | Значение |
|---|---|
| **Severity** | — (гипотеза опровергнута) |
| **file:line** | `src/backend/core/services/base_external_api.py` — **отсутствует** |
| **Reproduction** | `ls -la src/backend/core/services/base_external_api.py` |
| **Expected** (по отчёту) | exact-copy канона, 275 LOC |
| **Actual** | `ls: невозможно получить доступ к '...': Нет такого файла или каталога` |
| **Impact** | «дубликат на 275 LOC» не существует; чистка не даёт экономии LOC |
| **Fix** | не требуется; исправить два документа с ложным утверждением |
| **Regression test** | — |
| **Commit SHA** | не закоммичено |

**Фактический вывод:**
```
$ md5sum src/backend/services/core/base_external_api.py src/backend/core/services/base_external_api.py
15930cd95736002962575b2b70590f45  src/backend/services/core/base_external_api.py
md5sum: src/backend/core/services/base_external_api.py: Нет такого файла или каталога

$ wc -l src/backend/services/core/base_external_api.py
275 src/backend/services/core/base_external_api.py
```

**Что реально есть** — три lazy-proxy, а не копия кода:
- `core/services/base.py:14` — `__all__ = ("BaseExternalAPIClient",)` + `__getattr__`
- `core/services/__init__.py:18` — тот же lazy `__getattr__`
- `core/api/__init__.py:163-172` — третий прокси

Реальные подклассы: `services/integrations/skb.py:21`, `services/integrations/dadata.py:9`.

**Blocker для удаления прокси:** публичный API — `check_layers.py:103`
(`EXTENSIONS_FRAMEWORK_EXCEPTIONS`), ADR-0207:32, ADR-0053:64/76, плюс два
теста, проверяющих identity через прокси
(`tests/unit/core/test_services_proxy.py`, `tests/unit/core/test_tier1_facade_proxies.py`).

## B. `dsl/processors/saga_lra_processor/` — PARTIAL, 3 LOC

| Поле | Значение |
|---|---|
| **Severity** | LOW (оценка завышена в ~280 раз) |
| **file:line** | `src/backend/dsl/processors/saga_lra_processor/__init__.py` |
| **Reproduction** | `find src/backend/dsl/processors/saga_lra_processor -type f` + `grep -rn "processors\.saga_lra_processor" --include=*.py src extensions routes` |
| **Expected** | legacy-пакет ~811 LOC |
| **Actual** | 1 файл, 3 LOC; production-импортёров **0**; используют 3 тест-модуля |
| **Impact** | минимальный; миграция уже завершена (ADR-0313 Phase 2) |
| **Fix** | ADR-ревизия перед удалением |
| **Regression test** | — |
| **Commit SHA** | не закоммичено |

```python
# src/backend/dsl/processors/saga_lra_processor/__init__.py — весь файл
"""Compatibility shim для legacy migration tests (W2 P0-3)."""
from src.backend.dsl.engine.processors.saga_lra_processor import *  # noqa: F401,F403
```

**Blocker:** ADR-0341:36 и ADR-0344:20,51 прямо помечают путь как
`SEMANTIC_KEEP` / `DEPRECATED SHIM` — «saga_lra_processor path → SEMANTIC_KEEP
всегда». Удаление противоречит принятому ADR и требует правки ADR первым.

## C. Четыре кандидата DSL — ни один не exact-copy

| Кандидат | LOC | Вердикт | Confidence | Blocker |
|---|---:|---|---|---|
| C1 `engine/processors/infra_log.py` | 79 | PARTIAL | Средняя | Живая `@processor("infra_log_write", namespace="infra")` на `:22`; 0 YAML-использований; 1 тест-файл |
| C2 `engine/processors/feature_flag_check.py` | 124 | **DEAD** | Высокая | Собственный тест; семантический конфликт с YAML-шагом `feature_flag:` в 3 роутах |
| C3 `dsl/builders/collection_mixin.py` | 274 | PARTIAL | Средняя | Коллизия класса `CollectionMixin` с живым `collection.py` (238 LOC); `builders/protocols.py:203` |
| C4 `dsl/builders/request_reply_mixin.py` | 256 | PARTIAL | Средняя | Коллизия с живым `request_reply.py` (72 LOC); `builders/protocols.py:197` |

**Ключевой риск, общий для C3/C4.** Оба файла содержат класс/набор имён с тем же
именем, что и **боевые** модули, подключённые через `builders/base/__init__.py:49,73`.
`builders/protocols.py` резолвит миксины **по строковому имени**:

```python
# src/backend/dsl/builders/protocols.py:197,203
"RequestReplyMixin": EIPProtocol
"CollectionMixin":   DataStoreProtocol
```

Удаление `collection_mixin.py` / `request_reply_mixin.py` без разбора этого
словаря сломает **runtime-резолвинг миксинов по имени** — то есть самый
незаметный из возможных видов поломки. Это ровно тот случай, где «0 импортов»
не означает «можно удалять».

**C2 — самый чистый кандидат на удаление:** декоратора `@processor` нет вовсе,
builder-метода `.feature_flag()` нет (в `builders/base/feature_mixin.py:46` —
другой, manifest-уровневый механизм), YAML-шаг `feature_flag:` в
`routes/hello_route/main.dsl.yaml:9`, `routes/composition_demo/main.dsl.yaml:15`,
`routes/health_proxy_demo/health.dsl.yaml:8` обрабатывается **не этим классом**
(см. `dsl/engine/pipeline.py:117`). Требуется решение владельца DSL: должен ли
YAML-шаг `feature_flag:` идти через этот класс (тогда класс ALIVE) или это
разные механизмы (тогда DEAD).

## D. `_now_utc` — единственный кандидат DEAD без blocker'а

| Поле | Значение |
|---|---|
| **Severity** | P3 |
| **file:line** | `src/backend/core/feature_flags/redis_broadcaster.py:319` |
| **Reproduction** | `grep -rn "_now_utc" . \| grep -v __pycache__ \| grep -v "\.git/"` |
| **Expected** | хотя бы один вызов, либо экспорт |
| **Actual** | **1 совпадение в коде = только определение** |
| **Impact** | 4 LOC мёртвого кода; docstring обещает несуществующий test-hook |
| **Fix** | удалить функцию |
| **Regression test** | не требуется (0 вызовов) |
| **Commit SHA** | не закоммичено |

```python
# redis_broadcaster.py:319-321
def _now_utc() -> datetime:
    """Wrapper для тестов (timestamp override)."""
    return datetime.now(UTC)
```

Не входит в `__all__` модуля. Ни один тест его не monkeypatch'it — в отличие от
соседнего `_set_replica_id_for_tests`, который хотя бы документирован как
реальный test-hook. Docstring «wrapper для тестов» не подтверждается ничем.

## E. `middlewares/admin_audit.py` — DEAD в production

| Поле | Значение |
|---|---|
| **Severity** | P2 |
| **file:line** | `src/backend/entrypoints/middlewares/admin_audit.py` (153 LOC, класс на `:45`) |
| **Reproduction** | `grep -rn "admin_audit" --include=*.py src/backend/entrypoints src/backend/core` + проверка `setup_middlewares.build_default_registry()` + `pyproject.toml:727` |
| **Expected** | зарегистрирован в стеке либо импортируется |
| **Actual** | 0 production-импортов; **в `build_default_registry()` отсутствует**; группа entry points `gd_integration_tools.middleware_hooks` (`pyproject.toml:727`) **пуста** |
| **Impact** | 153 LOC неиспользуемого middleware; 4-й источник дублирования `payload_hash` числится в `docs/middleware/MIDDLEWARE.md:71` как «известная проблема» |
| **Fix** | удалить модуль + 2 тест-файла, либо перенести в регистр (нужен продуктовый выбор) |
| **Regression test** | существующие `test_admin_audit_middleware.py`, `test_admin_audit_pure_asgi.py` удаляются вместе с модулем |
| **Commit SHA** | не закоммичено |

Проверен и **динамический** путь регистрации (`registry.py:224-236
register_from_entry_points()`) — секция entry points пуста, `admin_audit` не
зарегистрирован ни одним dist-метадантом.

Упоминание `src/frontend/streamlit_app/pages/78_Плавная_деградация.py:76` —
текст UI-строки, а не импорт; ложное срабатывание.

## F. `dsl/processors/` (14 файлов, 296 LOC) — ALIVE как test-only поверхность

| Поле | Значение |
|---|---|
| **Severity** | — (удаление заблокировано) |
| **file:line** | `src/backend/dsl/processors/` (14 `.py`, 296 LOC) |
| **Reproduction** | `find src/backend/dsl/processors -name '*.py' \| xargs wc -l` + AST-gate |
| **Expected** | совместимая прокси-обёртка, которую можно удалить |
| **Actual** | production-импортёров legacy-путей **0**, но `__init__.py` (124 LOC) — **живой re-export хаб** на 36 имён |
| **Impact** | удаление сломает `dsl.processors.*` публичный путь и AST-gate |
| **Fix** | не трогать без ADR-ревизии |
| **Regression test** | `tools/checks/check_dsl_processors_imports.py` (сам гейт) |
| **Commit SHA** | не закоммичено |

**Фактический вывод:**
```
$ .venv/bin/python tools/checks/check_dsl_processors_imports.py
✅ AST-gate: no new imports of legacy src.backend.dsl.processors outside allowlist.
```

Проверен и DI-путь: единственный alias `dsl.processors.*` в
`core/di/module_registry.py:166` указывает на **engine**, а не на legacy-пакет
(`"dsl.processors.express_common": "src.backend.dsl.engine.processors.express._common"`),
поэтому `resolve_module()` в `core/di/providers/http.py:134` до legacy-кода
не достаёт. Динамического воскрешения нет — но и удалять нельзя, пока гейт,
три ADR (0313/0341/0344) и 6+ тест-модулей на него опираются.

---

## Итоговая таблица

| ID | Кандидат | LOC | Confidence | Blocker для удаления |
|---|---|---:|---|---|
| A | `core/services/base_external_api.py` | **файл отсутствует** | Высокая | Удалять нечего; гипотеза опровергнута |
| B | `dsl/processors/saga_lra_processor/` | **3** | Высокая | 3 тест-файла; ADR-0341/0344 `SEMANTIC_KEEP` |
| C1 | `engine/processors/infra_log.py` | 79 | Средняя | Живая `@processor`-регистрация DSL-контракта |
| C2 | `engine/processors/feature_flag_check.py` | 124 | Высокая | 1 тест; конфликт семантики YAML-шага `feature_flag:` |
| C3 | `dsl/builders/collection_mixin.py` | 274 | Средняя | Коллизия имени с живым `collection.py`; `protocols.py:203` |
| C4 | `dsl/builders/request_reply_mixin.py` | 256 | Средняя | Коллизия имени с живым `request_reply.py`; `protocols.py:197` |
| D | `_now_utc` (`redis_broadcaster.py:319`) | **4** | Высокая | **Нет** — безопасно к удалению |
| E | `middlewares/admin_audit.py` | 153 | Высокая | 2 тест-файла; `KNOWN_ISSUES.md:2102`; `docs/middleware/MIDDLEWARE.md:71` |
| F | `dsl/processors/` (весь пакет) | 296 | Высокая | `__init__.py` ALIVE; AST-gate; ADR-0313/0341/0344 |

**Безопасно к удалению прямо сейчас: 4 LOC (D).** Всё остальное требует
либо решения владельца архитектуры (ADR-ревизия), либо снятия зависимости от
тестов, либо продуктового выбора по семантике DSL.

**Два ложных утверждения в документации** (A) требуют исправления независимо
от dead code: `docs/roadmap/PROD_READINESS_GAPS.md:143` и
`docs/audit/cycle-1/domain-A3-Services.md:527`.
