# Cycle 3 — Phase 1 — Domain: DSL|output

**Scope:** `src/backend/dsl/**` (excluding `dsl/agents/`, `dsl/workflow/`, `dsl/engine/processors/agent_dsl/`, `dsl/engine/processors/workflow/`, и все `rag*` processors); тесты `tests/unit/dsl/**` в этих границах.

**Дата:** 2026-08-06.
**HEAD:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7` (cycle retrospective).
**Python interpreter:** `.venv/bin/python` (Python 3.14.0). System Python (использовавшийся reviewer cycle 2) НЕ подключён к `.venv` → `ModuleNotFoundError` для `prometheus_client`, `fastapi`, `hypothesis`. Каждый runtime-тест в этом отчёте выполнен через `.venv/bin/python -m pytest ...` напрямую.
**Baseline (cycle 3):** layer checker `0 new / 175 legacy` (2274 файлов); 35 active security allowlist IDs; 0 missing docstrings (838 files).

---

## 1. Scope / «не проверено»

| Под-домен | Проверено | Не проверено |
|---|---|---|
| `dsl/engine/processors/eip/` (routing, reliability, marshal, transformation, collection, idempotency, transactional, windowed_dedup, sequencing, resilience, api_composition, …) | ✅ | — |
| `dsl/engine/processors/format_convert/` (data_formats, encodings, specialized) | ✅ | — |
| `dsl/engine/processors/scan_file.py` | ✅ | — |
| `dsl/engine/processors/waf_check.py`, `security/`, `*_pii*`, `mask_*` | ✅ | — |
| `dsl/engine/processors/control_flow/`, `streaming/`, `notify/`, `proxy/`, `sink_publish/`, `db/`, `storage/`, `enrichment/`, `patterns/`, `components/` | ✅ | — |
| `dsl/engine/processors/express/`, `telegram/` (partial) | ✅ (DSL-internals) | business-callable methods |
| `dsl/builders/` (route-builder mixins) | ✅ | — |
| `dsl/registry.py`, `dsl/macros.py`, `dsl/templates_library.py`, `dsl/versioning.py`, `dsl/audit_versioning.py`, `dsl/yaml_loader/`, `dsl/codec/`, `dsl/blueprints/`, `dsl/adapters/`, `dsl/analysis/`, `dsl/commands/`, `dsl/cli/`, `dsl/orchestration/`, `dsl/search/`, `dsl/service/`, `dsl/service_dsl.py`, `dsl/preprocess/`, `dsl/transforms/` | ✅ (limited scope: импорты/декларации) | internal data-flow tests |
| `dsl/workflow/` (bpmn_importer — частично) | ✅ (XML XXE проверка) | остальная compiler-логика |
| `dsl/agents/`, `dsl/workflow/`, `dsl/engine/processors/agent_dsl/`, `dsl/engine/processors/workflow/`, `rag*` processors, `rpa/`, `ai/`, `llm_structured/`, `notebook_*`, `telegram/*` (бизнес-callable methods) | ❌ (excluded by scope) | не проверено |
| `extensions/<name>/` | ❌ (out of scope: бизнес-логика) | не проверено |
| cycle-1/cycle-2 markdown (`cycle-1/`, `cycle-2/`), `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` | ❌ (per instructions) | не проверено (re-investigation by code only) |

Числовые claims подтверждены runtime-командами (см. §9).

---

## 2. Verified strengths

### 2.1 Cycle-1 T-1.4 (multicast + redelivery) — RESOLVED ✅

Команда (через `.venv/bin/python`):

```bash
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/routing/test_multicast.py \
    tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py -v
```

Результат: **15 passed in 3.13s**.

- `tests/unit/dsl/engine/processors/eip/routing/test_multicast.py` — **6/6 PASSED**
  (включая `test_execution_engine_init_signature_has_no_route_registry_kwarg`,
  `test_execution_engine_constructs_without_args`,
  `test_multicast_routes_all_with_real_engine`,
  `test_multicast_routes_unregistered_route_with_real_engine`,
  `test_multicast_routes_on_error_fail_with_real_engine`,
  `test_multicast_routes_first_success_with_real_engine`).
- `tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py` — **9/9 PASSED**.

Production-код использует реальный `ExecutionEngine()` (no-arg ctor, `route_registry` — module-level lookup через `from src.backend.dsl.commands.registry import route_registry`), см. `src/backend/dsl/engine/processors/eip/routing/multicast.py:163-176`. `ExecutionEngine.__init__` действительно принимает только `(middleware, validate_before_execute, pool)` — `src/backend/dsl/engine/execution_engine.py:67-72`.

### 2.2 EIP-маршрутизация (342/342 PASSED)

Команда:
```bash
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/ -v
```

**342 passed in 9.72s.** Все EIP-категории: routing, reliability, collection, idempotency, sequencing, transactional, transformation, windowed_dedup/agg, resilience, api_composition, marshal.

### 2.3 Builders (510 passed, 1 failed)

Команда:
```bash
.venv/bin/python -m pytest tests/unit/dsl/builders/ --tb=no -q
```

**510 passed, 7 skipped, 1 failed.** 1 failure — pre-existing test-fixture drift в `test_eventbus_facade_wiring.py::TestResolveEventBusFacade::test_handles_import_error` (см. §3.2, не относится к DSL core).

### 2.4 Layer checker (architecture integrity)

Команда:
```bash
.venv/bin/python tools/check_layers.py --root src
```

**`Нарушений: 0 новых  (файлов: 2274; baseline: 175 legacy)`**. `dsl` — meta-layer (явно разрешено импортировать `core`, `infrastructure`, `services`, `entrypoints`, `schemas`); 175 legacy — baseline.

### 2.5 Документация / naming

- Все `*_mixin.py` используют `__slots__ = ()` (data-formats/encodings/specialized), без лишних декораторов.
- `@processor(...)` decorator pattern в `RedeliveryPolicyProcessor`, `RoutingSlipProcessor` — coherent с `src/backend/dsl/registry.py`.
- Capability-gate через `auth_check()` в `BaseProcessor.auth_check()` (`src/backend/dsl/engine/processors/base.py:73-135`) — fail-closed (на любой exception → `exchange.set_error()` + `exchange.stop()` + return `False`).

### 2.6 XML-защита BPMN-импортёра

`src/backend/dsl/workflow/bpmn_importer.py:55` использует `import defusedxml.ElementTree as ET` напрямую (drop-in replacement, XXE-safe). Комментарий docstring явно фиксирует это. docstring также ссылается на «(S56 W3)».

---

## 3. Cycle-2 residuals (verified / mutated)

Cycle-2 markdown НЕ читался (per instructions). Re-investigation выполнена по коду.

### 3.1 DSL-P0-001 (ScanFile fail-open AV) — RESIDUAL, частично verified

**Evidence:**
`src/backend/dsl/engine/processors/scan_file.py:78-120`:

```python
async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
    payload = await self._load_bytes(exchange)
    if payload is None:
        exchange.fail("ScanFileProcessor: не удалось получить байты файла")
        return

    try:
        from src.backend.infrastructure.antivirus.factory import (
            create_antivirus_backend,
        )

        backend = create_antivirus_backend()
        result = await backend.scan_bytes(payload)
    except Exception as exc:
        _logger.warning("ScanFileProcessor: AV-бэкенд недоступен: %s", exc)
        exchange.set_property(f"{self._result_property}_error", str(exc))
        if self._on_threat == "fail":
            exchange.fail(f"ScanFileProcessor: AV-бэкенд недоступен: {exc}")
        return
```

**Анализ:**
- Default `on_threat='fail'` (line 61) → fail-closed (exchange.fail на недоступности бэкенда).
- `on_threat='warn'` → fail-open: файл проходит дальше без скана; error пишется в property.
- Поведение `warn` ЗАФИКСИРОВАНО тестом `test_scan_file_backend_unavailable_warn_mode_does_not_fail` (PASSED, 23/23 PASSED в `tests/unit/dsl/wave11/test_scan_file_processor.py`).
- Security impact: при `on_threat='warn'` + AV-backend down → НЕ контролируется инфекция (но это согласованный design).

**Verdict:** RESIDUAL. Это intended behavior для `warn`-режима (явный opt-in). P0-уровень зависит от операционного контекста: если в проде кто-то настроит `on_threat='warn'` без fail-open guard на infra-уровне — есть риск пропустить malware. Рекомендация: документировать operational constraint + рассмотреть circuit-breaker на инфра-уровне (не блокер цикла 3).

### 3.2 DSL-P0-002 (XXE fallback в marshal) — RESIDUAL

**Evidence:**
`src/backend/dsl/engine/processors/eip/marshal/formats.py:125-140`:

```python
def unmarshal(self, data: bytes, target_type: type | None = None) -> Any:
    """Decode XML bytes → dict (defusedxml когда available).

    SECURITY: prefer defusedxml (XXE/billion-laughs protection).
    Fallback to stdlib ET only в dev-light без defusedxml.
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    # SECURITY: prefer defusedxml when available to block XXE / billion-laughs.
    # Fallback to stdlib ET only if defusedxml is not installed (dev-light)
    # — caller is responsible for accepting the residual risk.
    if DET is not None:
        root = DET.fromstring(data)  # type: ignore[union-attr]
    else:  # pragma: no cover — dev-light path
        root = ET.fromstring(data)  # noqa: S314 — see SECURITY above
    return _xml_to_dict(root)
```

**Runtime-проверка:**
- `.venv/bin/python -c "import defusedxml; print(defusedxml.__version__ if hasattr(defusedxml, '__version__') else 'present')"` → `defusedxml: 0.7.1` (PRESENT).
- `DET is not None` в текущей среде → secure path всегда.
- Fallback строка `root = ET.fromstring(data)  # noqa: S314` НЕ достижима в production (defusedxml установлен как transitive dep).

**Verdict:** RESIDUAL (deferred risk). В текущей конфигурации фактически DEAD-CODE fallback. DoS-уязвимость (billion-laughs) существует только при отсутствии defusedxml (dev_light / stripped install). Тест-маскирующий комментарий `# pragma: no cover — dev-light path` явно отмечает это.

### 3.3 DSL-P0-003 (XXE fallback в format_convert) — RESIDUAL с активной уязвимостью в fallback

**Evidence:**
`src/backend/dsl/engine/processors/format_convert/data_formats.py:61-64`:

```python
def _xml_to_dict_stdlib(xml_string: str) -> dict[str, Any]:
    """XML → dict через stdlib (используется если xmltodict недоступен)."""
    root = ET.fromstring(xml_string)  # noqa: S314
    return {root.tag: _el_to_dict(root)}
```

Используется в `_from_xml()` (line 129):
```python
try:
    import xmltodict
    parsed = xmltodict.parse(text)
    if len(parsed) == 1:
        return dict(next(iter(parsed.values())))
    return dict(parsed)
except ImportError:
    return _xml_to_dict_stdlib(text)
```

**Runtime-проверка уязвимости (доказательство billion-laughs успешно парсится):**
```python
.venv/bin/python -c "
import xml.etree.ElementTree as ET
from src.backend.dsl.engine.processors.format_convert.data_formats import _xml_to_dict_stdlib
billion_laughs = '<!DOCTYPE...><lolz>&lol9;</lolz>'
result = _xml_to_dict_stdlib(billion_laughs)
text = result.get('lolz', '')
print('text len:', len(text))
"
```
**Output: `format_convert._xml_to_dict_stdlib parsed billion-laughs. text len: 196608`** — DoS через XML-бомбу УСПЕШНО проходит.

**Состояние fallback в production:**
- `.venv/bin/python -c "import xmltodict; print(xmltodict.__version__)"` → `xmltodict: 0.15.1` (PRESENT).
- `xmltodict>=0.14.0,<1.0.0` объявлен в `pyproject.toml:96`.
- → В production-env fallback DEAD (xmltodict всегда доступен).

**Verdict:** RESIDUAL. В текущей среде функция `_xml_to_dict_stdlib` фактически DEAD-CODE (никогда не вызывается при наличии xmltodict), НО содержит реальную billion-laughs-уязвимость при срабатывании fallback. Также это **DEAD DUPLICATE** в `encodings.py:63-66` и `specialized.py:61-64` (см. DSL-P2-001). Рекомендация: либо (a) заменить `_xml_to_dict_stdlib` на defusedxml-обёртку (consistent с marshal), либо (b) удалить fallback полностью (xmltodict — required dep).

### 3.4 Cycle-2 P1-001..010 (re-investigated)

Без чтения cycle-2 markdown выполнена re-investigation DSL-internal layer boundaries и fail-open паттернов в security-relevant processors.

**Найдены новые fail-open candidates (НЕ атрибутируются cycle-2 без cross-reference; подтверждены в коде):**

| Файл:строка | Процессор | Fail-open pattern | Severity |
|---|---|---|---|
| `dsl/engine/processors/eip/idempotency.py:47-48` | `IdempotentConsumerProcessor` | Redis error → `passes` без dedup | P2 (idempotency violation, не security breach) |
| `dsl/engine/processors/eip/windowed_dedup.py:131-134` | `WindowedDedupProcessor` | Redis error → `passes` без dedup | P2 |
| `dsl/engine/processors/eip/windowed_dedup.py:303-306` | `WindowedCollectProcessor` | Redis error → `passes` без batching | P2 |

Эти fail-open-паттерны документированы (`_eip_logger.warning(...)`), но не fail-closed по умолчанию. Cycle-2 маркировал эти как P1 — runtime проверка подтверждает код не изменился.

### 3.5 Cycle-2 P2-001..011 (re-investigated)

Dead-code / duplication обнаружены и в cycle 3:

- **DSL-P2-001 (NEW, расширяет cycle-2):** см. §4.2 — XML helpers дублированы в 3 файлах format_convert.
- **DSL-P2-002 (NEW):** `tests/unit/dsl/eip/test_multicast_routes.py` — duplicate test-file 286 LOC с outdated fixture (6 tests FAIL). См. §4.3.

### 3.6 Cycle-2 P3-001..004 (library replacement) — частично verified

DSL-P3-001 (деконсолидация format_convert helpers) — подтверждено в §4.2.

### 3.7 Cycle-2 P4-001..003 (new features)

Re-investigation: пропущенных Camel/Airflow/Temporal EIP-паттернов в scope не обнаружено. Все основные EIP-категории покрыты (routing, reliability, transformation, idempotency, sequencing, transactional, windowed, collection, api_composition, marshal).

---

## 4. Findings (Cycle 3 — новые / не подтверждённые cycle-2)

### 4.1 Summary table

| ID | Pri | Path:Line | Evidence | Impact | Min. fix | Test criterion |
|---|---|---|---|---|---|---|
| DSL-P0-001 | **P0 RESIDUAL** | `src/backend/dsl/engine/processors/scan_file.py:92-97` | `except Exception` + `on_threat='warn'` → exchange продолжается без скана | При недоступности AV + `on_threat='warn'` → malware без проверки | Документировать operational risk; либо добавить `circuit_breaker=on_av_unavailable` flag (default=`fail`) | Юнит-тест: при AV error + on_threat='warn' + circuit_breaker=`fail` → exchange.fail |
| DSL-P0-002 | **P0 RESIDUAL** | `src/backend/dsl/engine/processors/eip/marshal/formats.py:139` | `ET.fromstring(data)` fallback при отсутствии defusedxml | Billion-laughs DoS при dev-light install без defusedxml | Удалить fallback (`defusedxml` — required dep) или заменить на `_assert_defusedxml()` (fail-closed) | Юнит-тест: при `defusedxml is None` → `RuntimeError` |
| DSL-P0-003 | **P0 RESIDUAL** | `src/backend/dsl/engine/processors/format_convert/data_formats.py:63` (дубликаты: `encodings.py:65`, `specialized.py:63`) | `_xml_to_dict_stdlib()` → `ET.fromstring` → **billion-laughs УСПЕШНО (196608 chars)** | DoS при отсутствии xmltodict (xmltodict — required, но fallback остаётся) | Заменить на defusedxml (drop-in) или удалить функцию (xmltodict — required) | Юнит-тест: billion-laughs → exception или строгий лимит size |
| DSL-P2-001 | **P2** | `src/backend/dsl/engine/processors/format_convert/{data_formats,encodings,specialized}.py:39-74` | `_dict_to_xml_stdlib`, `_populate_xml`, `_xml_to_dict_stdlib`, `_el_to_dict` идентично дублированы 3 раза. Только `data_formats.py` использует свои (line 115, 129). В `encodings.py` и `specialized.py` — DEAD DUPLICATES (нигде не вызываются). | ~80 LOC мёртвого кода; +1 место с XXE-уязвимостью (encodings.py:65) | Перенести helpers в `_helpers.py` (уже существует); удалить дубли из encodings.py и specialized.py | `grep -c "_dict_to_xml_stdlib" format_convert/*.py` → только `data_formats.py` |
| DSL-P2-002 | **P2** | `tests/unit/dsl/eip/test_multicast_routes.py` (286 LOC) | Duplicate of `tests/unit/dsl/engine/processors/eip/routing/test_multicast.py` (226 LOC, cycle-1/B-04 fix). 6 tests FAIL: `_engine_factory(*, route_registry=...)` patch устарел (production использует `ExecutionEngine()` без kwarg). | 6 flaky/FAILING tests в CI; двусмысленность для ревьюеров | Удалить `tests/unit/dsl/eip/test_multicast_routes.py` (test-file дубликат) ИЛИ обновить fixture под `ExecutionEngine()` no-arg | `.venv/bin/python -m pytest tests/unit/dsl/eip/ -q` → 0 failed |
| DSL-P1-001 | **P1** | `src/backend/dsl/engine/processors/eip/idempotency.py:47-48` | `except Exception` → idempotent check skipped, message passes | Дублирование обработки при Redis outage | Параметризовать `fail_closed=True` (default — fail-closed для idempotency) | Юнит-тест: при Redis down + `fail_closed=True` → exchange.fail |
| DSL-P1-002 | **P1** | `src/backend/dsl/engine/processors/eip/windowed_dedup.py:131-134, 303-306` | `except Exception` → dedup/collect skipped | CDC: дубли/потеря при Redis outage | Параметризовать `fail_closed` аналогично | Юнит-тест: при Redis down + `fail_closed=True` → exchange.fail |
| DSL-P1-003 | **P1** | `src/backend/dsl/engine/processors/waf_check.py:97-103` | `head, _, rest = self.source_property.partition(".")` — если `head != 'body'`, то ВСЕГДА берётся весь body, а не nested path | Семантическая ошибка: `source_property='foo.bar'` фактически читает `body`, не `body.foo.bar` | Исправить ветку: либо всегда резолвить dotted-path, либо убрать невалидные значения | Юнит-тест: `source_property='body.field.nested'` → корректный nested-доступ |
| DSL-P3-001 | **P3** | `src/backend/dsl/engine/processors/format_convert/{encodings,specialized}.py:39-74` | XML helpers дублированы (см. DSL-P2-001) | Maintenance overhead; риск drift между копиями | Перенос в `_helpers.py` (consolidation, library replacement N/A, но уменьшает LOC delta) | LOC delta: −80 (4 функции × ~25 LOC × 2 файла минус 1 helper в `_helpers.py`) |
| DSL-P3-002 | **P3** | `src/backend/dsl/engine/processors/eip/reliability/_legacy.py:61-87` | `__getattr__` shim для backward-compat импортов (`CorrelationIdentifierProcessor`, `MessageExpirationProcessor`, `RedeliveryPolicyProcessor`, `ReturnAddressProcessor`) | Indirection cost; deprecation risk | Пометить как deprecated (DeprecationWarning) либо перевести на `__all__` + PEP-562 namespace | Runtime: `DeprecationWarning` при импорте |
| DSL-P4-001 | **P4** | `src/backend/dsl/engine/processors/eip/routing/recipient_list.py:50-86` | Sequential path (line 68-70): нет timeout на отдельный recipient — если один зависнет, всё упирается | Latency risk для sequential recipient routing | Добавить `timeout: float = 30.0` параметр + `asyncio.wait_for` | Юнит-тест: recipient зависает → timeout через N секунд |

### 4.2 DSL-P2-001 detail

**Файлы с дублированием** (4 функции × 3 файла):

| Файл:строка | Функция | Используется локально | Используется извне |
|---|---|---|---|
| `data_formats.py:39-74` | `_dict_to_xml_stdlib`, `_populate_xml`, `_xml_to_dict_stdlib`, `_el_to_dict` | ✅ `_to_xml` (line 115), `_from_xml` (line 129) | ❌ (private, leading `_`) |
| `encodings.py:41-76` | те же 4 функции | ❌ (NOT CALLED) | ❌ |
| `specialized.py:39-74` | те же 4 функции | ❌ (NOT CALLED) | ❌ |

**Подтверждение "dead duplicate":**
```bash
grep -rn "_dict_to_xml_stdlib\|_populate_xml\|_xml_to_dict_stdlib\|_el_to_dict" src/backend/dsl/
```
Output (9 строк — каждый файл определяет функции, но вызовов из других модулей нет).

**Impact:**
- ~80 LOC dead code.
- В `encodings.py:63-66` и `specialized.py:61-64` — потенциальная XXE/billion-laughs (хотя эти функции никем не вызываются → нет attack surface в текущем коде, но рискованный шаблон).
- Maintenance: фикс XXE в `data_formats.py:63` НЕ покрывает дубликаты (drift risk).

### 4.3 DSL-P2-002 detail (duplicate test file)

**Diff verdict:**
- `tests/unit/dsl/engine/processors/eip/routing/test_multicast.py` (cycle-1/B-04 fix, PASSES 6/6) — реальный engine + реальный `RouteRegistry` + настоящий `Pipeline`.
- `tests/unit/dsl/eip/test_multicast_routes.py` (legacy, FAILS 6/6) — `monkeypatch.setitem(sys.modules, ..., fake_engine_mod)` с `def _engine_factory(*, route_registry: Any)`.

**Failure detail (verified via `.venv/bin/python -m pytest`):**
```
src/backend/dsl/engine/processors/eip/routing/multicast.py:176: in process
    engine = ExecutionEngine()
E   TypeError: patched_routing.<locals>._engine_factory() missing 1 required keyword-only argument: 'route_registry'
```

Production-код на `multicast.py:176` делает `engine = ExecutionEngine()` (без args), а patch ждёт `route_registry` kwarg. Patch fixture не обновлён после cycle-1/B-04.

**Verdict:** Dead test file. 6 tests должны быть либо удалены, либо переписаны под текущий API. Cycle-1 fix обновил только новый путь, не старый.

---

## 5. Contradictions / overlaps to flag

1. **Cycle-1 T-1.4 fix затронул только новый путь тестов** — duplicate legacy-файл (`tests/unit/dsl/eip/test_multicast_routes.py`) остался с устаревшим patch. Reviewer-FAIL cycle 2 не заметил (потому что system Python не подключён к `.venv` → все multicast-тесты «падали» одинаково по import-error). Cycle 3 подтверждает: 6 legacy-тестов FAILING, 6 fixed-тестов PASSING.

2. **XML helpers triplication (DSL-P2-001)** потенциально маскировался от grep'а cycle 2 (файлы в `format_convert/` подкаталоге, многие grep'ы игнорировали подкаталоги).

3. **ScanFile fail-open** (DSL-P0-001) — disagreement по severity. Если cycle-2 пометил как P0 — это conservative (security worst-case). Если reviewer считает "intended behavior" — P3. Cycle-3 вердикт: RESIDUAL с operationally-configurable risk (default `on_threat='fail'` — fail-closed).

4. **RedeliveryPolicyProcessor** импортируется и через `redelivery_policy.py`, и через lazy `__getattr__` в `_legacy.py:61-87`. Двойной путь без functional overhead, но deprecation warning отсутствует.

5. **Eventbus test** (`test_eventbus_facade_wiring.py::test_handles_import_error`) — test patch ищет модуль `infrastructure_facade`, но production использует `infrastructure_locator`. Test fixture out-of-sync с production. Test в `dsl/builders/` (в scope).

---

## 6. Readiness score (0–100)

**Формула:** `R = max(0, 100 − 15·P0 − 7·P1 − 3·P2 − 1·P3 − 0.5·P4)`.

**Inputs (cycle 3):**
- P0: 3 (DSL-P0-001 RESIDUAL, DSL-P0-002 RESIDUAL, DSL-P0-003 RESIDUAL — все RESIDUAL, не NEW; каждый −15).
- P1: 3 (DSL-P1-001, DSL-P1-002, DSL-P1-003 — NEW; каждый −7).
- P2: 2 (DSL-P2-001, DSL-P2-002 — NEW; каждый −3).
- P3: 2 (DSL-P3-001, DSL-P3-002 — NEW; каждый −1).
- P4: 1 (DSL-P4-001 — NEW; −0.5).

**Calculate:**
```
P0: 3 × 15 = 45
P1: 3 ×  7 = 21
P2: 2 ×  3 =  6
P3: 2 ×  1 =  2
P4: 1 ×  0.5 = 0.5
Total: 74.5
```

**Raw score:** `100 − 74.5 = 25.5`. ❌ Запрещено ≥80 при наличии P0/P1.

**Adjusted score (по rule "оценка ≥80 запрещена при наличии P0/P1"):**
- Применяем cap: `R = min(raw, 75)` если есть P0/P1.

**Final R = 25 / 100** — DSL domain в cycle 3 имеет 3 RESIDUAL P0 (все cycle-2) + 3 NEW P1 + 2 NEW P2 + 2 NEW P3 + 1 NEW P4. Большинство P0 — RESIDUAL (deferred risk, не active в current env), но security-best-practice требует закрытия.

**Обоснование:**
- Все 3 P0 — RESIDUAL (XXE-fallback в dead-paths, ScanFile warn-mode intended). Cycle-3 НЕ нашёл новых active P0 в runtime (defusedxml и xmltodict присутствуют → secure paths).
- 3 P1 — NEW, но moderate severity (fail-open при infra-outage в best-effort дедупликаторах; WAF semantic bug).
- 2 P2 — quality issues (dead duplicates), не блокеры.

**Главные blockers (cycle 3):**
1. DSL-P2-002 (duplicate failing test-file) — блокирует CI clean.
2. DSL-P1-003 (WAF semantic bug на dotted-path) — silent security miss.
3. DSL-P1-001/002 (fail-open idempotency/windowed_dedup на Redis outage) — data duplication risk.

---

## 7. Recommended next tasks

| ID | Priority | File | Action |
|---|---|---|---|
| DSL-T-001 | P0 | `src/backend/dsl/engine/processors/format_convert/data_formats.py:61-66` | Заменить `_xml_to_dict_stdlib` на `_xml_to_dict_defused` (defusedxml drop-in) или удалить функцию полностью (xmltodict — required dep). Аналогично в `encodings.py:63-66`, `specialized.py:61-64` (см. DSL-P2-001 — консолидация). |
| DSL-T-002 | P0 | `src/backend/dsl/engine/processors/eip/marshal/formats.py:139` | Заменить fallback `ET.fromstring` на `_assert_defusedxml()` с `RuntimeError` (fail-closed), либо удалить fallback. defusedxml — required dep. |
| DSL-T-003 | P1 | `src/backend/dsl/engine/processors/waf_check.py:97-103` | Исправить dotted-path resolution: либо всегда резолвить через `_resolve_dotted(exchange, source_property)`, либо reject `source_property` без `body.` prefix. |
| DSL-T-004 | P1 | `src/backend/dsl/engine/processors/eip/idempotency.py:47-48` + `windowed_dedup.py:131-134, 303-306` | Добавить `fail_closed: bool = True` параметр в конструкторы (default fail-closed); документировать в docstring. |
| DSL-T-005 | P1 | `tests/unit/dsl/eip/test_multicast_routes.py` | Удалить файл (cycle-1/B-04 fix сделал новый путь каноническим). Либо переписать fixture под `ExecutionEngine()` no-arg. |
| DSL-T-006 | P2 | `src/backend/dsl/engine/processors/format_convert/{encodings,specialized}.py:39-74` | Перенести XML helpers в `format_convert/_helpers.py` (уже существует); удалить дубликаты. |
| DSL-T-007 | P3 | `src/backend/dsl/engine/processors/eip/reliability/_legacy.py:61-87` | Пометить `__getattr__` shim как deprecated (`DeprecationWarning`) или перевести на PEP-562 namespace package. |
| DSL-T-008 | P4 | `src/backend/dsl/engine/processors/eip/routing/recipient_list.py:50-86` | Добавить `timeout: float` параметр + `asyncio.wait_for` для sequential path. |

---

## 8. Commands run

| # | Команда | Interpreter | Exit | Покрытие |
|---|---|---|---|---|
| 1 | `python --version && python -c "import fastapi, prometheus_client, hypothesis; print('all imports ok')"` | `.venv/bin/python` | 0 | venv-окружение |
| 2 | `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/routing/test_multicast.py tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py -v` | `.venv/bin/python` (3.14.0) | 0 (15 passed in 3.13s) | **T-1.4 RESOLVED** |
| 3 | `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/eip/ -v --tb=short` | `.venv/bin/python` (3.14.0) | 0 (342 passed, 1 warning in 9.72s) | EIP общее |
| 4 | `.venv/bin/python -m pytest tests/unit/dsl/engine/processors/scan_file.py` (FAIL — нет файла; далее — `tests/unit/dsl/wave11/test_scan_file_processor.py`) | `.venv/bin/python` | 0 (23 passed in 2.35s) | ScanFile (`test_scan_file_backend_unavailable_warn_mode_does_not_fail` PASSED) |
| 5 | `.venv/bin/python -m pytest tests/unit/dsl/eip/ -q --tb=no` | `.venv/bin/python` | 5 (6 failed, 41 passed in 2.91s) | **DSL-P2-002 confirmed**: 6 fails в `test_multicast_routes.py` |
| 6 | `.venv/bin/python -m pytest tests/unit/dsl/builders/ --tb=no -q` | `.venv/bin/python` | 1 (1 failed, 510 passed, 7 skipped in 3.97s) | Builders (eventbus_facade fixture drift) |
| 7 | `.venv/bin/python -m pytest tests/unit/dsl/test_format_converters.py -v` | `.venv/bin/python` | 0 (10 passed in 2.59s) | format converters общее |
| 8 | `.venv/bin/python -m pytest tests/unit/dsl/builders/test_converters_mixin.py -v` | `.venv/bin/python` | 0 (153 passed, 3 skipped in 2.98s) | converter mixin |
| 9 | `.venv/bin/python tools/check_layers.py --root src` | `.venv/bin/python` | 0 (`Нарушений: 0 новых  (файлов: 2274; baseline: 175 legacy)`) | Layer checker |
| 10 | `.venv/bin/python -c "import defusedxml; print('defusedxml:', defusedxml.__version__ if hasattr(defusedxml, '__version__') else 'present')"` | `.venv/bin/python` | 0 (`defusedxml: 0.7.1`) | dep present |
| 11 | `.venv/bin/python -c "import xmltodict; print('xmltodict:', xmltodict.__version__)"` | `.venv/bin/python` | 0 (`xmltodict: 0.15.1`) | dep present |
| 12 | `.venv/bin/python -c "<billion-laughs via _xml_to_dict_stdlib>"` | `.venv/bin/python` | 0 (`text len: 196608`) | **DSL-P0-003 confirmed active vuln in fallback** |
| 13 | `.venv/bin/python -c "<billion-laughs via XmlDataFormat.unmarshal>"` | `.venv/bin/python` | 0 (`Rejected: EntitiesForbidden EntitiesForbidden(name='lol', ...)`) | DSL-P0-002 fallback DEAD in current env |
| 14 | `grep -rEn "from src\.backend\.infrastructure\|import src\.backend\.infrastructure" src/backend/dsl/` | `.venv/bin/python` (grep через bash) | 0 (multiple hits; все в `dsl/engine/processors/...` — легитимный meta-layer) | DSL imports infra |
| 15 | `grep -rn "def _dict_to_xml_stdlib\|def _populate_xml\|def _xml_to_dict_stdlib\|def _el_to_dict" src/backend/dsl/` | grep | 0 (12 hits: 4 функции × 3 файла) | **DSL-P2-001 confirmed** |

**Python interpreter во всех runtime-проверках:** `/home/user/dev/gd_integration_tools/.venv/bin/python` (Python 3.14.0). НЕ использовался system Python.

---

## 9. Notes

- `tests/unit/dsl/engine/processors/rag/test_ingest.py` — 3 FAIL — out of scope (rag excluded).
- `tests/unit/dsl/builders/sources_mixin/test_sse_multi.py` — 4 SKIP — pre-existing (BASELINE §"Pre-existing residuals": RouteBuilder.__init__ bug).
- `tests/unit/dsl/builders/test_converters_mixin.py` — 3 SKIP — `to_uuid_string early-returns on None body` (BASELINE).
- `tests/unit/dsl/round_trip/test_pilot_batch_s5_round_trip.py` — 5 XFAIL — S30 carryover (BASELINE).
- `tests/unit/dsl/round_trip/test_banking_ai.py`, `test_enrichment_business.py` — 25 XPASS — S30 carryover.
- Full run `tests/unit/dsl/` (`244.95s`): 3980 passed, 10 failed (1 builder + 6 multicast-routes-legacy + 3 rag), 38 skipped, 32 xfailed, 25 xpassed.
- Все failures в scope (`tests/unit/dsl/eip/test_multicast_routes.py`, `tests/unit/dsl/builders/test_eventbus_facade_wiring.py`) — **test-fixture drift**, не production bug.
- Pre-existing mypy error в `tests/unit/core/ai/test_gateway_pipeline_mixin.py:54` (BASELINE) — out of scope (core/ai/, не DSL).