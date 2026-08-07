# Phase 4 diff-plan — Group-C-A7 (A7-DSL-Engine-Processors)

> **Дата:** 2026-08-06
> **Агент:** Group-C-A7 (cycle 1)
> **Домен:** A7 DSL Engine + Processors
> **Phase:** 4 — diff-plan (подготовка), НЕ реальные изменения
> **Источник:** `docs/audit/cycle-1/phase3-plan.md` § Group C
> **Domain report:** `docs/audit/cycle-1/domain-A7-DSL-Engine-Processors.md`
> **Эталон:** `docs/audit/cycle-1/phase2-summary.md`

**Скоуп группы (3 задачи):**
- C-1: `security.py:52` — заменить DEPRECATED import path на canonical
- C-2: `external.py` — удалить shadow `MCPToolProcessor`/`AgentGraphProcessor`, добавить canonical import `CDCProcessor`
- C-3: `eip/reliability.py` — удалить 442 LOC dead legacy file

**Суммарный ожидаемый diff:** +25 / −474 LOC (нетто −449 LOC)

---

## C-1. `security.py:52` — fix deprecated `_VERIFIERS_MODULE` import path

### Контекст
Phase 2 (`domain-A7-DSL-Engine-Processors.md:46`, **D-A7-01 P0**) обнаружил:
- `src/backend/dsl/engine/processors/security.py:52` импортирует из
  `src.backend.entrypoints.api.dependencies.auth_selector` (DEPRECATED shim),
  но `_VERIFIERS` **удалён** из этого shim'а в S162 W5
  (см. `entrypoints/api/dependencies/auth_selector.py:31` — комментарий
  "removed _VERIFIERS from re-exports — private symbol").
- **Канонический путь:** `core/auth/auth_selector.py:214-222` содержит
  `_VERIFIERS: dict[AuthMethod, Callable[..., Any]]` с 7 verifier'ами
  (API_KEY, JWT, BASIC, MTLS, SAML, EXPRESS, EXPRESS_JWT).
- Текущий runtime: `_load_verifiers()` **всегда** поднимает
  `AuthenticationProviderUnavailableError("verifier registry attribute missing in ...")`
  → **все** DSL pipelines с `AuthValidateProcessor` fail-closed ВСЕГДА.
- Это regression: production breaker, блокер релиза.

### Точный diff-план

#### File 1: `src/backend/dsl/engine/processors/security.py`

**Локация:** модуль-уровневая константа `_VERIFIERS_MODULE` (строка 52)
**Объём:** −1 / +1 LOC (одна строка)

Старый код (lines 49-52):
```python
# Путь модуля с verifier-реестром. Импортируется через importlib, чтобы
# не нарушать архитектурную границу dsl→entrypoints (verifier'ы держат
# FastAPI/Request, поэтому живут в entrypoints).
_VERIFIERS_MODULE = "src.backend.entrypoints.api.dependencies.auth_selector"
```

Новый код (lines 49-53):
```python
# Путь модуля с verifier-реестром. Импортируется через importlib, чтобы
# не нарушать архитектурную границу dsl→core/auth (canonical после S96 W1
# relocate + S162 W5 _VERIFIERS из shim'а). Шим DEPRECATED — НЕ резолвит
# приватный символ. Цикл 1: D-AUDIT-03 fix (cycle 1) — обход fail-closed-bug.
_VERIFIERS_MODULE = "src.backend.core.auth.auth_selector"
```

Также обновить **module docstring** (lines 7-12):

Старый (lines 7-11):
```
Использует уже существующие верификаторы из
``entrypoints.api.dependencies.auth_selector`` — это не нарушает
архитектурные границы, т.к. DSL-движок исполняется в рантайме
поверх HTTP-запроса (request доступен через ``exchange.headers`` /
``exchange.properties['request']``).
```

Новый:
```
Использует уже существующие верификаторы из
``core.auth.auth_selector._VERIFIERS`` (S96 W1 relocation, S162 W5
shim-cleanup). Runtime canonical path через importlib import —
DSL-движок исполняется в рантайме поверх HTTP-запроса (request через
``exchange.properties['request']``).
```

Также обновить **module-level security marker** (line 13):

Старый (line 13):
```python
Security audit marker: ``D-AUDIT-03`` (cycle-2, fail-closed fix).
```

Новый:
```python
Security audit marker: ``D-AUDIT-03`` (cycle-2) +
``D-AUDIT-C1 fix (cycle 1)`` (canonical import path).
```

Также обновить `_load_verifiers()` docstring в части fail-closed (lines 56-62):

Старый (lines 56-62):
```python
def _load_verifiers() -> dict[AuthMethod, Any]:
    """Lazy-loads verifier-реестр из entrypoints (runtime-only, fail-closed).

    Raises:
        AuthenticationProviderUnavailableError: если модуль не имеет атрибута
            ``_VERIFIERS`` или реестр пуст. Раньше возвращал ``{}`` — это
            fail-open (anonymous bypass). D-AUDIT-03.
    """
```

Новый:
```python
def _load_verifiers() -> dict[AuthMethod, Any]:
    """Lazy-loads verifier-реестр из ``core.auth.auth_selector`` (canonical).

    Returns: dict[AuthMethod, Callable] — 7 verifier'ов (API_KEY, JWT, BASIC,
        MTLS, SAML, EXPRESS, EXPRESS_JWT). До C-1 fix: import через
        entrypoints shim → AttributeError на ``_VERIFIERS`` (S162 W5 cleanup).
    Цикл 1 D-AUDIT-C1 fix (cycle 1): import path restored.

    Raises:
        AuthenticationProviderUnavailableError: если модуль повреждён
            (отсутствует атрибут ``_VERIFIERS``). D-AUDIT-03 (cycle 2 fail-closed).
    """
```

**Docstring marker:** первая строка `_load_verifiers` docstring должна содержать
тег `"D-AUDIT-C1 fix (cycle 1)"` (см. ниже в § Docstring markers).

#### File 2: `tests/unit/dsl/engine/processors/test_security.py`

**Локация:** строки 55-79 (две tests, mockирующие fail-closed как expected)
**Объём:** ~−12 / +25 LOC (rewrite двух tests на позитивный сценарий)

Старый код (lines 55-79):
```python
async def test_required_fails(self) -> None:
    """D-AUDIT-03: при empty verifiers registry → fail-closed (runtime)."""
    proc = AuthValidateProcessor(["jwt"], required=True)
    exchange = _ex({})
    exchange.set_property("request", MagicMock())
    # Runtime assertion: НЕ мокаем _load_verifiers — пусть реальный
    # код отработает на отсутствующем _VERIFIERS в production-shim.
    # Если verifier registry missing/empty — process() обязан записать
    # error в exchange и остановить pipeline (fail-closed).
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.stopped
    assert exchange.error is not None
    assert "provider unavailable" in exchange.error

@ pytest.mark.asyncio
async def test_provider_unavailable_raises(self) -> None:
    """D-AUDIT-03: _load_verifiers raise при missing _VERIFIERS."""
    from src.backend.dsl.engine.processors.security import (
        AuthenticationProviderUnavailableError,
        _load_verifiers,
    )

    with pytest.raises(AuthenticationProviderUnavailableError):
        _load_verifiers()
```

Новый код (заменяет lines 55-79, добавляет 5 новых tests):
```python
@pytest.mark.asyncio
async def test_required_fails_when_no_verifier_matches(self) -> None:
    """D-AUDIT-03 (cycle 2) + D-AUDIT-C1 fix (cycle 1): required=True
    и ни один verifier не подтвердил request → fail-closed через
    exchange.set_error + exchange.stop(). _load_verifiers возвращает
    РЕАЛЬНЫЙ dict из canonical core.auth.auth_selector."""
    proc = AuthValidateProcessor(["jwt"], required=True)
    exchange = _ex({})
    exchange.set_property("request", MagicMock())
    # Мокаем _load_verifiers чтобы вернуть пустой dict — все verifier'ы
    # для JWT отсутствуют → fail-closed на уровне process(), НЕ на уровне
    # _load_verifiers().
    with patch(
        "src.backend.dsl.engine.processors.security._load_verifiers"
    ) as mock_load:
        mock_load.return_value = {}  # no verifiers registered
        await proc.process(exchange, None)  # type: ignore[arg-type]
    # Все циклы try/except НЕ поднимают AuthenticationProviderUnavailableError
    # (registry существует, просто пустой). Но exchange.stopped должен быть
    # вызван через "ни один из методов ... не подтвердил запрос".
    assert exchange.stopped
    assert exchange.error is not None
    assert "не подтвердил" in exchange.error


@pytest.mark.asyncio
async def test_load_verifiers_returns_real_registry(self) -> None:
    """D-AUDIT-C1 fix (cycle 1): _load_verifiers() импортирует canonical
    core.auth.auth_selector и возвращает dict с 7 verifier'ами."""
    from src.backend.dsl.engine.processors.security import _load_verifiers

    verifiers = _load_verifiers()
    # 7 verifier'ов: API_KEY, JWT, BASIC, MTLS, SAML, EXPRESS, EXPRESS_JWT.
    # Из них `_VERIFIERS` в core.auth.auth_selector:214-222 — гарантия.
    assert len(verifiers) == 7
    assert AuthMethod.API_KEY in verifiers
    assert AuthMethod.JWT in verifiers
    assert AuthMethod.BASIC in verifiers
    # Все callable.
    for method, verifier in verifiers.items():
        assert callable(verifier), f"{method}: verifier должна быть callable"


@pytest.mark.asyncio
async def test_canonical_import_path(self) -> None:
    """D-AUDIT-C1 fix (cycle 1): import path указывает на canonical
    core.auth.auth_selector (НЕ DEPRECATED entrypoints shim)."""
    from src.backend.dsl.engine.processors.security import _VERIFIERS_MODULE

    assert _VERIFIERS_MODULE == "src.backend.core.auth.auth_selector"
    # Sanity: модуль должен иметь _VERIFIERS атрибут.
    import importlib

    module = importlib.import_module(_VERIFIERS_MODULE)
    assert hasattr(module, "_VERIFIERS")
    assert isinstance(getattr(module, "_VERIFIERS"), dict)
```

**Также обновить module docstring** (lines 1-6):

Старый:
```python
"""Unit tests for AuthValidateProcessor (D-AUDIT-03 cycle-2)."""
```

Новый:
```python
"""Unit tests for AuthValidateProcessor (D-AUDIT-03 cycle-2 + D-AUDIT-C1 cycle-1 fix).

После C-1 фикса (cycle 1): _VERIFIERS_MODULE указывает на canonical
src.backend.core.auth.auth_selector, и _load_verifiers() возвращает
real registry (7 verifier'ов). Раньше test_provider_unavailable_raises
фиксировал fail-closed-bug (masking) — переписан на позитивный сценарий.
"""
```

### Regression tests (3):

**Имена:**
1. `tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_required_fails_when_no_verifier_matches`
2. `tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_load_verifiers_returns_real_registry`
3. `tests/unit/dsl/engine/processors/test_security.py::TestAuthValidateProcessor::test_canonical_import_path`

**Что покрывает:**
- (1) — что process() правильно fail-closed когда реестр существует, но verifier'ы не совпадают (НЕ fail-open masking).
- (2) — что `_load_verifiers()` действительно возвращает registry из 7 AuthMethod.
- (3) — что `_VERIFIERS_MODULE` указывает на canonical путь и модуль имеет `_VERIFIERS` dict.

**Минимальный test body (test_canonical_import_path):**
```python
from src.backend.dsl.engine.processors.security import _VERIFIERS_MODULE
import importlib

assert _VERIFIERS_MODULE == "src.backend.core.auth.auth_selector"
module = importlib.import_module(_VERIFIERS_MODULE)
assert isinstance(getattr(module, "_VERIFIERS"), dict)
assert len(getattr(module, "_VERIFIERS")) >= 7  # 7 verifier'ов (API_KEY..EXPRESS_JWT)
```

### Done criteria

1. `from src.backend.dsl.engine.processors.security import _load_verifiers`
   → возвращает dict с **ровно 7 ключами** (API_KEY, JWT, BASIC, MTLS,
   SAML, EXPRESS, EXPRESS_JWT).
2. `tests/unit/dsl/engine/processors/test_security.py -v` → все tests зелёные
   (включая test_successful_auth, теперь проверяющий РЕАЛЬНЫЙ реестр).
3. `make format && make lint && make type-check` → exit 0.
4. `make check-docstrings MAX_ALLOWED=0` → exit 0 (новые docstrings в модуле
   добавлены с маркером `"D-AUDIT-C1 fix (cycle 1)"`).
5. `python tools/check_layers.py` → не появится новых violation
   (C-1 НЕ меняет layer-зависимости — только import path).
6. **Security metric:** `grep "AuthenticationProviderUnavailableError" src/backend/dsl/engine/processors/security.py`
   → остаётся в коде как fail-closed safety-net, но больше не raised
   автоматически для production DSL pipelines.
7. **Pre-existing dirty test file:** `test_security.py` (значится в git context
   как `M tests/unit/dsl/engine/processors/test_security.py`) — после C-1
   фикс tests из masking → позитивные, dirty bit должен измениться на "M" с
   другим содержимым.

### Docstring markers

- **`src/backend/dsl/engine/processors/security.py:13`** (module-level, 1-я строка
  после `"""`):
  Старый: `Security audit marker: ``D-AUDIT-03`` (cycle-2, fail-closed fix).`
  Новый: `Security audit marker: ``D-AUDIT-03`` (cycle-2, fail-closed fix) +`` ``D-AUDIT-C1 fix (cycle 1)`` (canonical import path restore).`

- **`src/backend/dsl/engine/processors/security.py:61`**
  (внутри `_load_verifiers` docstring, 1-я строка):
  Добавить строку `D-AUDIT-C1 fix (cycle 1): canonical import path restored.`

- **`tests/unit/dsl/engine/processors/test_security.py:1`**
  Добавить `+ D-AUDIT-C1 cycle-1 fix` к docstring.

### Риски

- **Risk 1 (Medium):** сторонние тесты/extensions могут полагаться на
  fail-closed behaviour security.py для mocking. Проверено: только
  сам test_security.py использует fail-closed как expected (lines 55-79),
  все extension imports через `from src.backend.dsl.engine.processors.security import ...`
  → работают (публичный API не изменился).
- **Risk 2 (Low):** если core.auth.auth_selector.py в будущем переедет снова
  (другой relocate) → C-1 fix стареет. Mitigation: cycle 1 docstring указывает
  на commit/issue S96 W1 + S162 W5.
- **Risk 3 (Low):** `_load_verifiers()` теперь возвращает dict с **callable**
  verifier'ами, но **не async guaranteed**. Старая семантика предполагала
  async — `verifier(request)` await. См. AuthValidateProcessor:165
  `ctx = await verifier(request)`. Не изменилось — продолжает работать.
- **Cross-group sync:** нет. Группа D (A2-Security) фиксирует WAF coverage;
  C-1 не трогает WAF. Cross-domain: A4-Entrypoints может удалить
  `entrypoints/api/dependencies/auth_selector.py` shim после C-1, но это
  вне scope Group-C-A7.

---

## C-2. `external.py` — удалить shadow `MCPToolProcessor`/`AgentGraphProcessor`, добавить canonical `CDCProcessor` import

### Контекст

Phase 2 (`domain-A7-DSL-Engine-Processors.md:48`, **D-A7-02 P0**) обнаружил:
- `src/backend/dsl/engine/processors/external.py` (139 LOC) содержит
  дубль-классы `MCPToolProcessor` (line 10) и `AgentGraphProcessor` (line 47),
  оба BaseProcessor-based, simple-versions.
- `__init__.py:7-8` импортирует ТОЛЬКО `agent_dsl/agent_graph.py` и
  `agent_dsl/mcp_tool.py` — secure BaseAIProcessor-based versions.
- `external.py`'s shadow-versions никогда не используются (прямой
  `grep "from src.backend.dsl.engine.processors.external import" src/` → 0 hits).
- **Безопасность:** `external.MCPToolProcessor` (line 10) **НЕ имеет**
  `file://` transport deny (contrast: `agent_dsl.mcp_tool.py:86-90` rejects).
  **Shadowed attack surface** — менее secure версия существует в кодовой базе.

Дополнительная находка (`docs/audit/swarm-2026-08-06/cycle-1/phase-1/06-dsl.md:65`,
DSL-P1-001): `"CDCProcessor"` объявлен в `__init__.py:258` `__all__`, но
**НЕ импортирован** на top-level. `from src.backend.dsl.engine.processors import CDCProcessor`
→ ImportError. C-2 фиксит дополнительно.

### Точный diff-план

#### File 1: `src/backend/dsl/engine/processors/external.py`

**Локация:** Module-level — удалить classes `MCPToolProcessor` (lines 10-44)
и `AgentGraphProcessor` (lines 47-70). Оставить `CDCProcessor` (lines 73-138).
**Объём:** −63 LOC

Старый код (lines 1-71):
```python
from typing import Any, ClassVar

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("AgentGraphProcessor", "CDCProcessor", "MCPToolProcessor")


class MCPToolProcessor(BaseProcessor):
    """Вызывает внешний MCP tool из DSL pipeline."""
    [35 строк кода]


class AgentGraphProcessor(BaseProcessor):
    """Запускает LangGraph-агента внутри DSL pipeline."""
    [24 строки кода]


class CDCProcessor(BaseProcessor):
    """Реагирует на CDC-события и маршрутизирует через DSL.
    [66 строк кода, остаётся как есть]
```

Новый код:
```python
"""External CDC processor (cycle-1 C-2 fix: shadow classes MCPToolProcessor + AgentGraphProcessor removed).

Canonical versions live in ``agent_dsl/mcp_tool.py`` (file:// transport denied)
и ``agent_dsl/agent_graph.py`` (BaseAIProcessor-based secure). Shadowed
классы были attack surface (D-AUDIT-04 cycle 1) — less-secure duplicates
доступные через прямой import path, но не через ``__init__.py``.

После C-2: только ``CDCProcessor`` остаётся. Это легитимный external processor
(диспатчит CDC events через DSL). DSL-P1-001 fix: добавлен в __init__.py
re-export для consistency с ``__all__``.

External processors linkage: см. ``extensions/credit_pipeline/agents/`` и
другие domain-specific extensions для канонических processor registrations.
"""

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("CDCProcessor",)


class CDCProcessor(BaseProcessor):
    """Реагирует на CDC-события и маршрутизирует через DSL.

    [тело без изменений: lines 73-138 из старой версии]
    """
    [... остаётся без изменений, 66 строк ...]
```

**Docstring marker:** Добавить в module-level docstring (строка после `"""`)
`Security audit marker: ``D-AUDIT-04 fix (cycle 1)`` (MCPToolProcessor /
AgentGraphProcessor shadowed duplicates removal).`

#### File 2: `src/backend/dsl/engine/processors/__init__.py`

**Локация:** Добавить canonical `CDCProcessor` import в список lines 60-70
(рядом с `cdp_capture.CDCCaptureProcessor`).
**Объём:** +1 LOC (один import)

Старый код (lines 60):
```python
from src.backend.dsl.engine.processors.cdc_capture import CDCCaptureProcessor
```

Новый код (lines 60-61):
```python
from src.backend.dsl.engine.processors.cdc_capture import CDCCaptureProcessor
from src.backend.dsl.engine.processors.external import CDCProcessor
```

**Также обновить module docstring** (lines 1-5), добавив один sentence:
```diff
 """DSL Processors — re-export для обратной совместимости.

 Все процессоры доступны через:
     from src.backend.dsl.engine.processors import BaseProcessor, DispatchActionProcessor, ...
+
+Canonical CDCProcessor импортирован через external (cycle 1 C-2 fix).
 """
```

### Regression tests (2):

**Имена:**
1. `tests/unit/dsl/engine/processors/test_external.py::test_canonical_cdc_processor_importable`
2. `tests/unit/dsl/engine/processors/test_external.py::test_shadow_classes_removed`

**Что покрывает:**
- (1) — что canonical `from src.backend.dsl.engine.processors import CDCProcessor` работает
  (DSL-P1-001 fix).
- (2) — что shadow `MCPToolProcessor` / `AgentGraphProcessor` больше не доступны
  через `external.py` (security: блокировка attack surface).

**Минимальный test body:**
```python
# test 1: canonical import works
def test_canonical_cdc_processor_importable() -> None:
    from src.backend.dsl.engine.processors import CDCProcessor
    assert CDCProcessor.__module__ == "src.backend.dsl.engine.processors.external"

# test 2: shadow classes removed
def test_shadow_classes_removed() -> None:
    import pytest
    from src.backend.dsl.engine.processors import external

    # Canonical: CDCProcessor остался
    assert hasattr(external, "CDCProcessor")

    # Shadows удалены
    assert not hasattr(external, "MCPToolProcessor")
    assert not hasattr(external, "AgentGraphProcessor")

    # __all__ = только CDCProcessor
    assert external.__all__ == ("CDCProcessor",)
```

(Опционально — новый test file `test_external.py` в
`tests/unit/dsl/engine/processors/`. Если нежелательно — минимум 2 tests
можно добавить в существующий `test_security.py` или
`tests/unit/dsl/test_external_shadow_removal_cycle1.py`.)

### Done criteria

1. `from src.backend.dsl.engine.processors import CDCProcessor` → **works**
   (раньше ImportError). Проверка:
   `python -c "from src.backend.dsl.engine.processors import CDCProcessor; print(CDCProcessor)"`.
2. `from src.backend.dsl.engine.processors.external import MCPToolProcessor`
   → ImportError (security attack surface closed).
3. `from src.backend.dsl.engine.processors.external import AgentGraphProcessor`
   → ImportError.
4. `from src.backend.dsl.engine.processors import MCPToolProcessor` → продолжает
   работать через canonical `agent_dsl/mcp_tool.py` (path unchanged).
5. `from src.backend.dsl.engine.processors.external import CDCProcessor` → works.
6. `grep -rn "from src.backend.dsl.engine.processors.external import" src/`
   → ≤1 hit (только legitimate use в __init__.py).
7. `make format && make lint && make type-check` → exit 0.
8. **Security metric:** `_pycache_metrics.shadow_surface_count` = 0
   (вручную: количество shadowed имён в `external.py` = 0).

### Docstring markers

- **`src/backend/dsl/engine/processors/external.py:1`** (module docstring):
  Старый: (пустой/короткий)
  Новый: добавить строку `Security audit marker: ``D-AUDIT-04 fix (cycle 1)``
  (MCPToolProcessor/AgentGraphProcessor shadowed duplicates removal).`

- **`src/backend/dsl/engine/processors/__init__.py:1`**:
  Добавить sentence `Canonical CDCProcessor импортирован через external (cycle 1 C-2 fix).`
  в module docstring.

### Риски

- **Risk 1 (Low):** любые undocumented imports `from src.backend.dsl.engine.processors.external`
  через глобальный grep → 0 hits, безопасно.
- **Risk 2 (Low):** shadow classes удалены, но их бывшие пользователи (если есть)
  → ImportError. Mitigation: `_get_module_path` middleware-facade паттерн
  не использует shadow classes (verified). Search showed 0 hits.
- **Risk 3 (Low):** extensions могут импортировать `external.CDCProcessor`
  для подсказки типов. После C-2 — продолжает работать (class не удалена).
- **Cross-group sync:** нет. C-2 НЕ меняет `agent_dsl/*` файлы (canonical
  остаётся без изменений).

---

## C-3. Удалить dead legacy `eip/reliability.py` (442 LOC)

### Контекст

Phase 2 (`domain-A7-DSL-Engine-Processors.md:50`, **D-A7-04 P1**):
- `src/backend/dsl/engine/processors/eip/reliability.py` (442 LOC) содержит
  4 класса: `CorrelationIdentifierProcessor`, `MessageExpirationProcessor`,
  `RedeliveryPolicyProcessor`, `ReturnAddressProcessor`.
- **S175 split** создал package directory `eip/reliability/` с теми же
  4-мя процессорами (в отдельных файлах) + `_legacy.py` (constants/aliases).
- **Python resolution rule:** когда в одной parent directory существуют
  `reliability.py` (file) и `reliability/` (package), Python **raises**:
  ```
  TypeError: ... both generate conflicting file/directory names
  ```
  при попытке импортировать что-либо из `eip/`. Однако фактически `__init__.py`
  `eip/__init__.py:64` импортирует через `eip.reliability` (без conflict —
  Python pre-existing выбор зависит от sys.path приоритета).
- Domain report (line 50) указывает: «runtime `.venv/bin/python` подтверждает:
  импорт резолвится в `reliability/__init__.py` (package), НЕ legacy».
- **Сценарий:** если тесты/импорты РАБОТАЮТ (через package shadow), legacy file
  остаётся **никогда не загружаемым dead code**, но compile/ruff всё равно
  его lintят → 442 LOC dead лишнего веса.

### Точный diff-план

#### File 1: Удалить `src/backend/dsl/engine/processors/eip/reliability.py`

**Локация:** весь файл (442 LOC)
**Объём:** −442 LOC

Старый код (whole file):
```python
[442 строк устаревшего кода]
```

Новый код: **файл полностью удалён** (`rm` или `git rm`).

Pre-removal verification commands:
```bash
grep -rn "from src.backend.dsl.engine.processors.eip.reliability import" src/ tests/ extensions/ 2>/dev/null
# Ожидаемый результат: только test_s56_w3_eip_reliability.py:19 (test file)
# Все остальные imports резолвятся в package `reliability/__init__.py`.

python -c "from src.backend.dsl.engine.processors.eip.reliability import CorrelationIdentifierProcessor; print(CorrelationIdentifierProcessor.__module__)"
# Ожидаемый результат: src.backend.dsl.engine.processors.eip.reliability.correlation_identifier
# (НЕ .reliability [legacy file path])
```

**Если verification pass** → файл удаляется одной командой `git rm` (или
`rm` для нового файла, не в git).

**Если verification fail** (e.g. legacy._VERIFIERS=None при попытке
importing MCPTool через эту цепочку) → fallback: вместо удаления переименовать
legacy в `_legacy_godfile_deprecated.py` для архива (поиск сохранения → Sprint 175
git history достаточно).

### Regression tests (2):

**Имена:**
1. `tests/unit/dsl/engine/processors/eip/test_s56_w3_eip_reliability.py::test_legacy_processor_exports_resolve_lazily`
   (existing test, проверяет backward-compat через `from eip.reliability import _legacy`)
2. `tests/unit/dsl/engine/processors/eip/reliability/test_no_legacy_module_imports.py::test_no_legacy_file_imports`

**Что покрывает:**
- (1) — existing тест-проверка что `__getattr__` в `_legacy.py` корректно
  резолвит 4 класса.
- (2) — новая test-проверка что legacy `reliability.py` НЕ существует и
  никакой импорт не пытается его резолвить.

**Минимальный test body:**
```python
# test 2: verify legacy file removed
def test_no_legacy_file_imports() -> None:
    import importlib
    from pathlib import Path

    legacy_file = (
        Path(__file__).parent.parent.parent.parent.parent
        / "src" / "backend" / "dsl" / "engine" / "processors"
        / "eip" / "reliability.py"
    )
    assert not legacy_file.exists(), f"Legacy reliability.py still exists: {legacy_file}"

    # Verify package shadow works
    from src.backend.dsl.engine.processors.eip.reliability import (
        CorrelationIdentifierProcessor,
        MessageExpirationProcessor,
        RedeliveryPolicyProcessor,
        ReturnAddressProcessor,
    )
    # Все 4 класса резолвятся в canonical package files (НЕ legacy)
    assert CorrelationIdentifierProcessor.__module__.endswith(
        ".eip.reliability.correlation_identifier"
    )
    assert RedeliveryPolicyProcessor.__module__.endswith(
        ".eip.reliability.redelivery_policy"
    )
```

### Done criteria

1. `ls src/backend/dsl/engine/processors/eip/reliability.py` → **No such file**
   (или при fallback: `reliability_legacy_deprecated.py`).
2. `python -c "from src.backend.dsl.engine.processors.eip.reliability import CorrelationIdentifierProcessor; print(CorrelationIdentifierProcessor.__module__)"`
   → выводит путь, заканчивающийся на `correlation_identifier`.
3. `tests/unit/dsl/engine/processors/eip/test_s56_w3_eip_reliability.py -v`
   → все 12 tests зелёные (существующие tests без изменений).
4. `tests/unit/dsl/engine/processors/eip/reliability/test_redelivery_policy.py -v`
   → 5 tests зелёные.
5. `make format && make lint && make type-check` → exit 0.
6. `make check-docstrings MAX_ALLOWED=0` → exit 0 (legacy file не имел
   docstring gate violations, но после удаления baseline сдвигается; если
   новый baseline выше предыдущего — compensate через `tools/check_docstrings.py`).
7. **LOC delta:** −442 в core/dsl.
8. **Coverage:** не падает (legacy file не был covered — тесты все смотрят
   на package, не на legacy).
9. **git history:** legacy file доступен через git log (S175 Phase 2 commit).

### Docstring markers

Не применимо (файл удаляется целиком — нет docstring для маркировки).
Однако рекомендуется:

- **`docs/audit/cycle-1/phase4-diff-plan-Group-C-A7.md`** (этот файл, уже
  имеет marker context для cross-reference).
- **`CHANGELOG.md`** если существует — запись `feat(cleanup): eip/reliability.py
  442 LOC legacy removed (D-AUDIT-05 fix (cycle 1))`.

### Риски

- **Risk 1 (Medium):** Python может **не** резолвить preference при
  одновременном наличии `reliability.py` + `reliability/` directory.
  Это известный edge-case: PEP 328 namespace packages vs regular packages.
  Mitigation: проверить `python -c "import src.backend.dsl.engine.processors.eip.reliability; print(reliability.__file__)"`
  ПЕРЕД удалением. Если conflict → fallback rename, не delete.
- **Risk 2 (Low):** legacy file может иметь side-effects (module-level code,
  регистрации). Проверка: `grep "^[a-zA-Z_].*=" reliability.py | head -20`
  → если только class/constant definitions → безопасно.
- **Risk 3 (Low):** `tools/check_docstrings_allowlist.txt:312` ссылается на
  `src/backend/dsl/engine/processors/external.py:101:4 CDCProcessor.process`
  (НЕ на legacy reliability — не проблема).
- **Cross-group sync:** нет. C-3 НЕ меняет workflows, services, или core
  (только удаление file).

---

## Сводный command list (для cycle 1 dev agent)

### Pre-flight (до изменений)
```bash
# Baseline layer violations
python tools/check_layers.py > /tmp/c1-group-c-pre.txt 2>&1

# Backup target files
cp src/backend/dsl/engine/processors/security.py /tmp/security.py.bak
cp src/backend/dsl/engine/processors/external.py /tmp/external.py.bak
ls -la src/backend/dsl/engine/processors/eip/reliability.py  # 442 lines
```

### C-1: Apply diff
```bash
# Edit _VERIFIERS_MODULE (line 52):
#   "src.backend.entrypoints.api.dependencies.auth_selector"
# → "src.backend.core.auth.auth_selector"
#
# Update docstrings (D-AUDIT-C1 fix (cycle 1) marker)

# Verify with venv:
.venv/bin/python -c "
from src.backend.dsl.engine.processors.security import _load_verifiers
verifiers = _load_verifiers()
assert len(verifiers) == 7, f'Expected 7 verifiers, got {len(verifiers)}'
print('OK:', sorted(m.value for m in verifiers))
"
```

### C-2: Apply diff
```bash
# Edit external.py: remove MCPToolProcessor (lines 10-44), AgentGraphProcessor (lines 47-70)
#   Update __all__ = ('CDCProcessor',)
#   Update module docstring with D-AUDIT-04 fix (cycle 1) marker

# Edit __init__.py:60: add CDCProcessor import
#   from src.backend.dsl.engine.processors.external import CDCProcessor

# Verify:
.venv/bin/python -c "
from src.backend.dsl.engine.processors import CDCProcessor
print('OK CDCProcessor:', CDCProcessor)
try:
    from src.backend.dsl.engine.processors.external import MCPToolProcessor
    print('FAIL: MCPToolProcessor still importable')
except ImportError:
    print('OK: MCPToolProcessor not importable from external (shadow removed)')
"
```

### C-3: Apply diff
```bash
# Verify Python preference (package over module):
.venv/bin/python -c "
import sys
sys.path.insert(0, '.')
from src.backend.dsl.engine.processors.eip.reliability import CorrelationIdentifierProcessor
module_path = CorrelationIdentifierProcessor.__module__
print('Resolved to:', module_path)
assert module_path.endswith('.correlation_identifier'), f'Expected package file, got {module_path}'
print('OK package wins over legacy .py')
"

# Remove legacy file:
git rm src/backend/dsl/engine/processors/eip/reliability.py

# Verify deletion:
ls src/backend/dsl/engine/processors/eip/reliability.py 2>&1
# Expected: No such file or directory
```

### Post-flight (после всех 3 задач)
```bash
# Run regression tests
uv run pytest tests/unit/dsl/engine/processors/test_security.py -v
uv run pytest tests/unit/dsl/engine/processors/test_external.py -v
uv run pytest tests/unit/dsl/engine/processors/eip/test_s56_w3_eip_reliability.py -v
uv run pytest tests/unit/dsl/engine/processors/eip/reliability/ -v

# Run all DSL tests
uv run pytest tests/unit/dsl/ -m 'not e2e' -v

# Coverage check: ensure no drop
uv run pytest tests/unit/dsl/engine/processors/ --cov=src/backend/dsl/engine/processors --cov-report=term-missing

# Type check + lint + docstrings
make format && make lint && make type-check
make check-docstrings MAX_ALLOWED=0

# Layer check (no regressions)
python tools/check_layers.py > /tmp/c1-group-c-post.txt 2>&1
diff /tmp/c1-group-c-pre.txt /tmp/c1-group-c-post.txt
# Expected: 0 new violations

# Security audit markers verify
grep -rn "D-AUDIT-C1 fix (cycle 1)\|D-AUDIT-04 fix (cycle 1)\|D-AUDIT-05 fix (cycle 1)" src/ tests/
```

### Commit messages (5 commits, atomic)

```bash
git add src/backend/dsl/engine/processors/security.py \
        tests/unit/dsl/engine/processors/test_security.py
git commit -m "fix(dsl): security.py — canonical _VERIFIERS_MODULE import path (D-AUDIT-C1 fix (cycle 1))"

git add src/backend/dsl/engine/processors/external.py \
        src/backend/dsl/engine/processors/__init__.py
git commit -m "fix(dsl): external.py — удалить shadow MCPToolProcessor/AgentGraphProcessor + add CDCProcessor import (D-AUDIT-04 fix (cycle 1))"

git add tests/unit/dsl/engine/processors/eip/reliability/test_no_legacy_module_imports.py  # if new test file added
git rm src/backend/dsl/engine/processors/eip/reliability.py
git commit -m "chore(cleanup): eip/reliability.py — удалить 442 LOC dead legacy (D-AUDIT-05 fix (cycle 1))"
```

(Возможно дополнительные commits для новых test files.)

---

## Метрики качества (cycle 1 close-out)

| Метрика | До | После | Δ |
|---|---|---|---|
| A7 готовность (Phase 2 baseline) | 65% | 75% (estimated) | **+10pp** |
| `external.py` shadow surface | 2 shadow classes | 0 | **−2** |
| `eip/reliability.py` LOC | 442 | 0 | **−442** |
| `_load_verifiers` returns | exception (fail-closed) | dict (7 verifiers) | **fix** |
| `__init__.py` re-export consistency | 1 broken (CDCProcessor) | 0 | **−1** |
| Regression tests added | 0 | 7 (3 + 2 + 2) | **+7** |
| Layer-check violations (new) | 0 | 0 | **0** |

---

## Cross-references

- **Domain report:** `docs/audit/cycle-1/domain-A7-DSL-Engine-Processors.md`
- **Phase 2 summary:** `docs/audit/cycle-1/phase2-summary.md`
- **Phase 3 plan:** `docs/audit/cycle-1/phase3-plan.md` § Group C (line 112-136)
- **Related finding (DSL-P1-001):** `docs/audit/swarm-2026-08-06/cycle-1/phase-1/06-dsl.md:65`
- **Related finding (D-A7-04 runtime verification):** `domain-A7-DSL-Engine-Processors.md:50`

---

## Phase 5 reviewer checklist

- [ ] **Critic review:** не появились ли TODO/моки в новых tests?
- [ ] **Architect review:** layer violations = 0 (verified `tools/check_layers.py`)
- [ ] **Reviewer review:** `make format && make lint && make type-check && make test -m 'not e2e'` зелёный
- [ ] **Docstring gate:** `make check-docstrings MAX_ALLOWED=0` зелёный
- [ ] **Security markers:** grep для трёх ID'ов присутствует в коде + tests
- [ ] **Atomic commits:** 3-5 commits, нет merge commits, conventional prefix, Russian-first

---

**Diff-plan завершён. Cycle 1 Group-C-A7 готов к execution отдельным dev agent'ом.**
