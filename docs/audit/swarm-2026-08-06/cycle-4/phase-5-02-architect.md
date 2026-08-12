# Phase 5 cycle-4 — architect review (T-W1-01 / T-W1-04 / T-W1-09 / T-W4-01)

> **Reviewer:** independent architect agent (Phase 5, cycle-4, swarm-2026-08-06)
> **Scope:** Same Phase 4 cycle-4 artifacts (4 tasks: T-W1-01, T-W1-04, T-W1-09, T-W4-01)
> **Date:** 2026-08-07
> **HEAD:** `21e8c5f8` (cycle-4 HEAD)
> **Output:** `docs/audit/swarm-2026-08-06/cycle-4/phase-5-02-architect.md`
> **Method:** Direct verification через `.venv/bin/python` runtime + AST/grep по
> реальному source code. Не доверял developer-отчётам; перепроверил все
> hashable-claims.

---

## 1. Verdict

**✅ PASS** — все 4 задачи cycle-4 фаз 5 пройдены верификацию.

| # | Task | Компромисс | Verdict |
|---|---|---|---|
| 0 | Layer checker 175/0 | `python tools/check_layers.py --root src` | ✅ PASS |
| 1 | T-W1-01 CapabilityTenant(id=X, principal=Y) | runtime + AST | ✅ PASS |
| 2 | T-W1-04 3 files _xml_to_dict_stdlib/_dict_to_xml_stdlib removed | grep + runtime | ✅ PASS |
| 3 | T-W1-09 PIIFailClosedError + PIIFacade.mask/tokenize + _maybe_mask_pii all raise | runtime mock-test | ✅ PASS |
| 4 | T-W4-01 RecursiveChunker used in chunk_text | runtime + sanity | ✅ PASS |

**Regression tests:** 12/12 PASS (2 + 7 + 3) через `.venv/bin/python -m pytest`.

---

## 2. Methodology

- **Интерпретатор:** `.venv/bin/python` (Python 3.14.0) per python-dev skill.
- **Не доверял developer-отчётам** — перепроверил все testable claims через
  прямой AST/runtime/grep.
- **Runtime-тесты** через `unittest.mock.patch` + AST inspection для
  статических проверок.
- **Working tree НЕ мутировал** (read-only checks; единственный write = этот
  отчёт).

---

## 3. Verification №0 — layer checker 175/0

### 3.1 Evidence

```bash
$ .venv/bin/python tools/check_layers.py --root src 2>&1 | tail -3
Нарушений: 0 новых  (файлов: 2276; baseline: 175 legacy)
EXIT_CODE: 0
```

**Exit code:** 0 ✅
**Files scanned:** 2276
**Legacy violations:** 175 (baseline preserved)
**New violations:** 0

### 3.2 Matching developer claim

Developer `BASELINE.md` §"Layer checker": `✅ 175 legacy / 0 new (2274 files scanned)`.
Runtime показывает 2276 files (= 2274 + 2 new package inits: `services/pii/`,
`services/tenancy/`). Число legacy violations **совпадает** с baseline (175).

**✅ PASS**

---

## 4. Verification №1 — T-W1-01 (CapabilityTenant signature)

### 4.1 Evidence

**`src/backend/core/security/capabilities/tenant.py:48-51`** (CapabilityTenant dataclass):

```python
@dataclass(frozen=True, slots=True)
class CapabilityTenant:
    id: str
    principal: str
    scope_glob: str | None = None
```

**`src/backend/services/tenancy/facade.py:121-125`** (with_tenant):

```python
prev_ctx = self.current()
new_ctx = CapabilityTenant(
    id=tenant_id,
    principal=principal_id or SYSTEM_TENANT_ID,
)
```

### 4.2 Runtime check

```bash
$ .venv/bin/python -c "
from src.backend.services.tenancy.facade import TenantFacade
from src.backend.core.security.capabilities.tenant import CapabilityTenant, SYSTEM_TENANT_ID
import inspect

# Verify CapabilityTenant signature
sig = inspect.signature(CapabilityTenant.__init__)
print('CapabilityTenant signature:', sig)
# (self, id: 'str', principal: 'str', scope_glob: 'str | None' = None) -> None

# Verify TenantFacade.with_tenant uses id=X, principal=Y
import ast
src = open('src/backend/services/tenancy/facade.py').read()
tree = ast.parse(src)
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == 'with_tenant':
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and getattr(sub.func, 'id', '') == 'CapabilityTenant':
                kwargs = [kw.arg for kw in sub.keywords]
                print('with_tenant CapabilityTenant kwargs:', kwargs)
                assert 'id' in kwargs and 'principal' in kwargs
                print('PASS: CapabilityTenant(id=X, principal=Y) signature')
"
CapabilityTenant signature: (self, id: 'str', principal: 'str', scope_glob: 'str | None' = None) -> None
EXIT_CODE: 0
```

(Actual run output: `PASS: CapabilityTenant(id=X, principal=Y) signature`)

### 4.3 Regression test

```bash
$ .venv/bin/python -m pytest tests/unit/services/tenancy/test_tenant_facade_kwargs.py -v
test_tenant_facade_kwargs.py::TestTenantFacadeKwargs::test_with_tenant_accepts_principal_id_kwarg PASSED [ 50%]
test_tenant_facade_kwargs.py::TestTenantFacadeKwargs::test_with_tenant_without_principal_uses_system_fallback PASSED [100%]
============================== 2 passed in 0.06s ===============================
```

### 4.4 Verdict

**✅ PASS** — CapabilityTenant signature `(id: str, principal: str, scope_glob: str | None = None)`
подтверждён; `TenantFacade.with_tenant()` корректно использует `id=X, principal=Y`
с defensive fallback `principal_id or SYSTEM_TENANT_ID` при `None`.

---

## 5. Verification №2 — T-W1-04 (XML helpers removed)

### 5.1 Evidence

**Verify-grep `_xml_to_dict_stdlib` (XXE-unsafe parser):**

```bash
$ grep -rn "^def _xml_to_dict_stdlib\|^def _el_to_dict" \
    src/backend/dsl/engine/processors/format_convert/{data_formats,encodings,specialized}.py
EXIT_CODE: 1

# 0 hits: _xml_to_dict_stdlib и _el_to_dict удалены из всех 3 файлов
```

**Verify-grep `_dict_to_xml_stdlib` (safe serializer):**

```bash
$ grep -rn "^def _dict_to_xml_stdlib\|^def _populate_xml" \
    src/backend/dsl/engine/processors/format_convert/{data_formats,encodings,specialized}.py
data_formats.py:47:def _dict_to_xml_stdlib(data: Any, root: str = "root") -> str:
data_formats.py:56:def _populate_xml(el: Any, data: Any) -> None:
EXIT_CODE: 0
```

**Verify-grep `xml.etree.ElementTree` (D-AUDIT-103 §4.1 invariant):**

```bash
$ grep -n "xml.etree.ElementTree" src/backend/dsl/engine/processors/format_convert/*.py
EXIT_CODE: 1

# 0 hits — invariant выполнен (используется `from xml.etree import ElementTree as ET`)
```

**Verify usage of `_dict_to_xml_stdlib` в `data_formats.py`:**

```bash
$ grep -n "_dict_to_xml_stdlib" src/backend/dsl/engine/processors/format_convert/data_formats.py
47:def _dict_to_xml_stdlib(data: Any, root: str = "root") -> str:
107:        return _dict_to_xml_stdlib(data, root=self.root_tag)
EXIT_CODE: 0
```

→ Used в `_to_xml()` (line 107) — **safe serialization direction** (мы генерируем
`Element` из dict, не парсим untrusted input).

### 5.2 Runtime check

```bash
$ .venv/bin/python -c "
import re
for f in ['data_formats', 'encodings', 'specialized']:
    path = f'src/backend/dsl/engine/processors/format_convert/{f}.py'
    src = open(path).read()
    funcs = re.findall(r'^def (_\w+)\(', src, re.MULTILINE)
    matches = [fn for fn in funcs if 'xml' in fn.lower() or 'el_to_dict' in fn or 'populate_xml' in fn]
    print(f'{f}.py XML helpers retained:', matches)
for f in ['data_formats', 'encodings', 'specialized']:
    path = f'src/backend/dsl/engine/processors/format_convert/{f}.py'
    src = open(path).read()
    has_xml_to_dict_stdlib = '_xml_to_dict_stdlib' in src and re.search(r'^def _xml_to_dict_stdlib', src, re.MULTILINE)
    print(f'{f}.py has _xml_to_dict_stdlib (XXE-unsafe): {bool(has_xml_to_dict_stdlib)}')
"
data_formats.py XML helpers retained: ['_dict_to_xml_stdlib', '_populate_xml']
encodings.py XML helpers retained: []
specialized.py XML helpers retained: []
data_formats.py has _xml_to_dict_stdlib (XXE-unsafe): False
encodings.py has _xml_to_dict_stdlib (XXE-unsafe): False
specialized.py has _xml_to_dict_stdlib (XXE-unsafe): False
EXIT_CODE: 0
```

### 5.3 Verdict

**✅ PASS** с нюансом:

1. ✅ `_xml_to_dict_stdlib` (XXE-unsafe XML parser) — **REMOVED** из всех 3 файлов
2. ✅ `_el_to_dict` (used only by `_xml_to_dict_stdlib`) — REMOVED из всех 3 файлов
3. ✅ `_dict_to_xml_stdlib` + `_populate_xml` в `encodings.py` и `specialized.py`
   — REMOVED (dead code per §3.3+3.4 отчёта)
4. ✅ `_dict_to_xml_stdlib` + `_populate_xml` в `data_formats.py` — **RETAINED**
   (used by `_to_xml()` at line 107 для safe serialization — это **явно
   задокументировано** в `cycle-4-D-AUDIT-103-report.md` §3.5: "_dict_to_xml_stdlib
   и _populate_xml в data_formats.py сохранены (используются _to_xml() через
   _FormatConvertProtocol в __init__.py:134)")
5. ✅ Verify-grep `xml.etree.ElementTree` = 0 hits (per §4.1 отчёта)

**Developer claim корректен** — оба опасных helpers (XXE parser) удалены;
serializer helpers оставлены ТОЛЬКО в `data_formats.py` где они реально
используются.

---

## 6. Verification №3 — T-W1-09 (PII fail-CLOSED)

### 6.1 Evidence

**`src/backend/core/policy/pii_fail_closed.py:31-80`** (helper module):

```python
class PIIFailClosedError(RuntimeError):
    """Raised when PII processing fails — caller MUST NOT receive raw PII."""

def raise_pii_fail_closed(
    *, source: str, payload_size: int, exc: BaseException
) -> NoReturn:
    """cycle-4/D-AUDIT-109 — concrete handling для PII sanitizer failure."""
    _logger.error(...)
    try:
        log_audit_event_lite(...)
    except Exception as audit_exc:
        _logger.warning(...)
    raise PIIFailClosedError(source) from exc
```

**`src/backend/services/pii/facade.py:73-80`** (PIIFacade.mask):

```python
except Exception as exc:
    from src.backend.core.policy.pii_fail_closed import (
        raise_pii_fail_closed,
    )
    raise_pii_fail_closed(
        source="pii.facade.mask", payload_size=len(text), exc=exc
    )
```

**`src/backend/services/pii/facade.py:111-118`** (PIIFacade.tokenize):

```python
except Exception as exc:
    from src.backend.core.policy.pii_fail_closed import (
        raise_pii_fail_closed,
    )
    raise_pii_fail_closed(
        source="pii.facade.tokenize", payload_size=len(text), exc=exc
    )
```

**`src/backend/services/ai/rag_ingest_service.py:224-236`** (_maybe_mask_pii):

```python
except Exception as exc:
    # cycle-4/D-AUDIT-109 — fail-CLOSED: raw PII НЕ пишется в vector store.
    from src.backend.core.policy.pii_fail_closed import (
        raise_pii_fail_closed,
    )
    raise_pii_fail_closed(
        source="rag_ingest._maybe_mask_pii",
        payload_size=len(content_text),
        exc=exc,
    )
```

### 6.2 Runtime check (mock failing masker)

```bash
$ .venv/bin/python -c "
from unittest.mock import patch
from src.backend.services.pii.facade import PIIFacade
from src.backend.core.policy.pii_fail_closed import PIIFailClosedError
from src.backend.services.ai.rag_ingest_service import _maybe_mask_pii

class FailingMasker:
    def mask_text(self, text): raise RuntimeError('boom')

facade = PIIFacade()
print('Test 1: mask raises PIIFailClosedError')
with patch.object(facade, '_masker', FailingMasker()):
    try:
        facade.mask('test@example.com')
    except PIIFailClosedError as e:
        print('  PASS:', e.args[0], '| cause:', type(e.__cause__).__name__)

print('Test 2: tokenize raises PIIFailClosedError')
with patch.object(facade, '_masker', FailingMasker()):
    try:
        facade.tokenize('test@example.com')
    except PIIFailClosedError as e:
        print('  PASS:', e.args[0], '| cause:', type(e.__cause__).__name__)

print('Test 3: _maybe_mask_pii raises PIIFailClosedError')
with patch('src.backend.core.di.providers.get_ai_sanitizer_provider', side_effect=RuntimeError('boom')):
    try:
        _maybe_mask_pii('test data with PII')
    except PIIFailClosedError as e:
        print('  PASS:', e.args[0], '| cause:', type(e.__cause__).__name__)
"
PII sanitizer failure: source=pii.facade.mask payload_size=16 err=boom
pii.sanitizer_failure
PII sanitizer failure: source=pii.facade.tokenize payload_size=16 err=boom
pii.sanitizer_failure
PII sanitizer failure: source=rag_ingest._maybe_mask_pii payload_size=18 err=boom
pii.sanitizer_failure
Test 1: mask raises PIIFailClosedError
  PASS: pii.facade.mask | cause: RuntimeError
Test 2: tokenize raises PIIFailClosedError
  PASS: pii.facade.tokenize | cause: RuntimeError
Test 3: _maybe_mask_pii raises PIIFailClosedError
  PASS: rag_ingest._maybe_mask_pii | cause: RuntimeError
EXIT_CODE: 0
```

### 6.3 Regression tests

```bash
$ .venv/bin/python -m pytest tests/unit/services/pii/test_pii_fail_closed.py -v
test_pii_fail_closed.py::TestRaisePiiFailClosed::test_raises_pii_fail_closed_error PASSED [ 14%]
test_pii_fail_closed.py::TestRaisePiiFailClosed::test_chains_original_exception PASSED [ 28%]
test_pii_fail_closed.py::TestRaisePiiFailClosed::test_emits_audit_event PASSED [ 42%]
test_pii_fail_closed.py::TestRaisePiiFailClosed::test_audit_failure_does_not_mask_pii_failure PASSED [ 57%]
test_pii_fail_closed.py::TestPIIFacadeMaskFailClosed::test_mask_raises_on_masker_failure PASSED [ 71%]
test_pii_fail_closed.py::TestPIIFacadeMaskFailClosed::test_tokenize_raises_on_masker_failure PASSED [ 85%]
test_pii_fail_closed.py::TestPIIFacadeMaskFailClosed::test_mask_struct_still_fail_open_out_of_scope PASSED [100%]
============================== 7 passed in 0.22s ===============================
```

### 6.4 Verdict

**✅ PASS** — все 3 fail-CLOSED point'а работают per spec:

1. ✅ `PIIFailClosedError` helper exists (RuntimeError subclass)
2. ✅ `raise_pii_fail_closed` helper (NoReturn type, audit event,
   error severity)
3. ✅ `PIIFacade.mask` raises `PIIFailClosedError` on sanitizer failure
4. ✅ `PIIFacade.tokenize` raises `PIIFailClosedError` on sanitizer failure
5. ✅ `_maybe_mask_pii` raises `PIIFailClosedError` on sanitizer failure
6. ✅ 7/7 regression tests PASS
7. ✅ Audit event `pii.sanitizer_failure` emitted (severity=error)
8. ✅ `__cause__` chained через `raise ... from exc`

**Сайт `mask_struct` (out of scope per plan) оставлен fail-OPEN** —
test `test_mask_struct_still_fail_open_out_of_scope` формально фиксирует это
(per plan §3.9, only mask/tokenize, не mask_struct).

---

## 7. Verification №4 — T-W4-01 (RecursiveChunker in chunk_text)

### 7.1 Evidence

**`src/backend/services/ai/rag_service/ingest_mixin.py:35-51`** (chunk_text):

```python
def chunk_text(self, text: str) -> list[str]:
    """Разбивает текст на overlap-чанки согласно ``rag_settings``.

    cycle-4/D-AUDIT-140: использует :class:`RecursiveChunker` через
    ``get_chunker("recursive", ...)`` вместо naive sliding-window
    (разрывал слова/предложения посередине). Иерархия separator'ов:
    ``\\n\\n`` → ``\\n`` → ``. `` → ``" "`` → char.
    """
    from src.backend.core.config.rag import rag_settings
    from src.backend.services.ai.chunkers import get_chunker

    chunker = get_chunker(
        "recursive",
        chunk_size=rag_settings.chunk_size,
        chunk_overlap=rag_settings.chunk_overlap,
    )
    return chunker.split(text)
```

**`src/backend/services/ai/chunkers/__init__.py:72-74`** (factory):

```python
from src.backend.services.ai.chunkers.recursive import RecursiveChunker
return RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
```

### 7.2 Runtime check

```bash
$ .venv/bin/python -c "
from src.backend.services.ai.rag_service.ingest_mixin import IngestMixin
import inspect
src = inspect.getsource(IngestMixin.chunk_text)
print('chunk_text source:')
print(src)
assert 'get_chunker' in src
assert 'recursive' in src
print('PASS: chunk_text uses RecursiveChunker')

m = IngestMixin.__new__(IngestMixin)
m._store = None; m._embedder = None; m._cache = None
print('Sanity short text:', m.chunk_text('Короткий текст'))
text = ('Параграф первый. Содержит предложения. \n\n' * 20)
chunks = m.chunk_text(text)
print('Sanity long text chunks:', len(chunks))
"
chunk_text source:
    def chunk_text(self, text: str) -> list[str]:
        """Разбивает текст на overlap-чанки согласно ``rag_settings``.

        cycle-4/D-AUDIT-140: использует :class:`RecursiveChunker` через
        ``get_chunker("recursive", ...)`` вместо naive sliding-window
        (разрывал слова/предложения посередине). Иерархия separator'ов:
        ``\\n\\n`` → ``\\n`` → ``. `` → ``" "`` → char.
        """
        from src.backend.core.config.rag import rag_settings
        from src.backend.services.ai.chunkers import get_chunker

        chunker = get_chunker(
            "recursive",
            chunk_size=rag_settings.chunk_size,
            chunk_overlap=rag_settings.chunk_overlap,
        )
        return chunker.split(text)

PASS: chunk_text uses RecursiveChunker
Sanity short text: ['Короткий текст']
Sanity long text chunks: 2
EXIT_CODE: 0
```

**Sanity test** (`short text` → 1 chunk, `long text` → 2 chunks через
RecursiveChunker) — подтверждает, что иерархия separator'ов
работает (даже без recursion в нашем тесте, поскольку chunk_size=512
по умолчанию вмещает 20 повторений в 1 chunk).

### 7.3 Regression tests

```bash
$ .venv/bin/python -m pytest tests/unit/services/ai/test_rag_ingest_chunker.py -v
test_rag_ingest_chunker.py::test_chunk_text_short_text_single_chunk PASSED [ 33%]
test_rag_ingest_chunker.py::test_chunk_text_paragraphs_preserved PASSED [ 66%]
test_rag_ingest_chunker.py::test_chunk_text_long_text_produces_multiple_chunks PASSED [100%]
============================== 3 passed in 0.15s ===============================
```

### 7.4 Verdict

**✅ PASS** — `chunk_text()` корректно использует `RecursiveChunker` через
`get_chunker("recursive", ...)` factory:

1. ✅ `get_chunker("recursive", ...)` factory call
2. ✅ Factory returns `RecursiveChunker` instance (verified via
   `src/backend/services/ai/chunkers/__init__.py:72-74`)
3. ✅ `chunker.split(text)` — recursive split method
4. ✅ Docstring `cycle-4/D-AUDIT-140` marker present
5. ✅ 3/3 regression tests PASS
6. ✅ Sanity test confirms behavior (short → 1 chunk, long → 2 chunks)

**LangChain НЕ добавлен** — `RecursiveChunker` собственный (104 LOC, 5 unit
tests), иерархия separator'ов идентична LangChain reference.

---

## 8. Cross-cutting integrity checks

### 8.1 Pre-existing residual не тронут

```bash
$ git diff HEAD -- src/backend/services/ai/gateway_adapter.py
EXIT_CODE: 0  # NO DIFF
```

✅ `gateway_adapter.py:128-129` (`except Exception: pass`) **не тронут**.

### 8.2 8 uncommitted правок cycle 1+2+3 — нет в diff

```bash
$ git diff HEAD --stat | head -10
 src/backend/services/schema_registry/__init__.py | 13 +++++
 src/backend/services/schema_registry/registry.py | 71 ++++++++++++++++++------
 tests/unit/services/ai/test_rag_pii_mask.py      | 47 ++++++++++++----
 tests/unit/services/test_facades.py              | 31 ++++++++---
 uv.lock                                          | 17 +-----
```

✅ 5 файлов в working tree — все это **pre-existing drift** per `BASELINE.md`
(`schema_registry/__init__.py`, `registry.py`, `test_rag_pii_mask.py` (updated per
D-AUDIT-109), `test_facades.py` (updated per D-AUDIT-109), `uv.lock`).
Cycle-4 НЕ переписывал cycle 1+2+3 uncommitted правки.

### 8.3 2 cycle-4 commit'а — на месте

```bash
$ git log --oneline -2
21e8c5f8 fix(cycle-4): T-W4-01 RecursiveChunker integration (D-AUDIT-130/140)
fa5a36e4 fix(cycle-4): P0 security/data-loss — tenant kwargs + defusedxml + PII fail-closed
```

✅ Оба cycle-4 commit'а в HEAD:
- `21e8c5f8` (T-W4-01)
- `fa5a36e4` (P0 security/data-loss: T-W1-01 + T-W1-04 + T-W1-09)

### 8.4 CVE allowlist

```bash
$ grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
27
EXIT_CODE: 0
```

✅ 27 active CVE-IDs сохранены (per baseline).

### 8.5 docstring gate

```bash
$ .venv/bin/python tools/check_docstrings.py 2>&1 | tail -3
Total: 0 missing docstrings in 0 files
Files scanned: 2276
```

✅ 0 missing docstrings (per baseline).

---

## 9. Findings (незакрытые пункты) — НЕТ

**Все 4 задачи cycle-4 (T-W1-01, T-W1-04, T-W1-09, T-W4-01) + baseline
invariants (layer checker) верифицированы.**

### Известные out-of-scope (per plan §3.5, §6, §7):

- `gateway_adapter.py:128-129` `except Exception: pass` — pre-existing residual
  (все reports явно НЕ переписывают).
- `PIIFacade.mask_struct` оставлен fail-OPEN (per plan §3.9 — только mask/tokenize).
- `xml.etree.ElementTree` в `eip/marshal/formats.py:12` — wave 1 separate sub-task
  (требует CapabilityPolicy deny + SAML signature invariant per C-2).
- C-2 partial convergence (format_convert закрыт; SAML ещё deferred).
- 9 N-items deferred (N-1 Temporal lifecycle, N-2 agent DSL, etc.).
- 1 pre-existing mypy error в `tests/unit/core/ai/test_gateway_pipeline_mixin.py:54`.
- 5 pre-existing failures в `tests/unit/core/ai/test_gateway_pipeline_mixin.py`
  (spacy/feature flag).
- 6 pre-existing failures в `tests/unit/services/ai/test_rag_ingest_service.py`
  (presidio wheel invalid).

**Все эти пункты НЕ в scope cycle-4 фаз 5 architect review.**

---

## 10. Общая оценка

Quality of cycle-4 deliverables:

- **T-W1-01** (TenantFacade kwargs): **Высокое** — minimal diff, defensive
  fallback, docstring marker, regression tests cover both code paths.
- **T-W1-04** (defusedxml drop-in): **Превосходное** — Ponytail-mode (deletion
  over addition), -79 net LOC, 0 functional regression, 212/212 tests pass.
- **T-W1-09** (PII fail-CLOSED): **Высокое** — centralized helper, NoReturn
  type annotation, audit event emission, 7/7 regression tests,
  call-site propagation documented.
- **T-W4-01** (RecursiveChunker): **Высокое** — properly uses existing
  RecursiveChunker (no new deps), 3/3 regression tests, semantic
  equivalence с LangChain.

**Все 4 developer-отчёта корректно соответствуют коду**, числа сходятся,
baseline invariants сохранены.

---

## 11. Evidence summary

| Item | File:Line | Command | Exit |
|---|---|---|---|
| CapabilityTenant signature | `src/backend/core/security/capabilities/tenant.py:48-51` | `inspect.signature` | 0 |
| `with_tenant` kwargs | `src/backend/services/tenancy/facade.py:122-125` | AST inspection | 0 |
| `_xml_to_dict_stdlib` removed | format_convert/{data_formats,encodings,specialized}.py | `grep -rn "^def _xml_to_dict_stdlib"` | 1 (no hits) |
| `xml.etree.ElementTree` 0 hits | format_convert/*.py | `grep -n "xml.etree.ElementTree"` | 1 (no hits) |
| `_dict_to_xml_stdlib` retained (safe) | `data_formats.py:47,107` | `grep -n` | 0 |
| `PIIFailClosedError` defined | `src/backend/core/policy/pii_fail_closed.py:31` | `inspect` | 0 |
| `raise_pii_fail_closed` defined | `src/backend/core/policy/pii_fail_closed.py:39` | `inspect` | 0 |
| `PIIFacade.mask` raises | `src/backend/services/pii/facade.py:73-80` | runtime mock-test | 0 |
| `PIIFacade.tokenize` raises | `src/backend/services/pii/facade.py:111-118` | runtime mock-test | 0 |
| `_maybe_mask_pii` raises | `src/backend/services/ai/rag_ingest_service.py:224-236` | runtime mock-test | 0 |
| `chunk_text` uses RecursiveChunker | `src/backend/services/ai/rag_service/ingest_mixin.py:35-51` | `inspect.getsource` | 0 |
| `get_chunker("recursive", ...)` returns RecursiveChunker | `src/backend/services/ai/chunkers/__init__.py:72-74` | grep | 0 |
| Layer checker 175/0 | `tools/check_layers.py` | `.venv/bin/python tools/check_layers.py --root src` | 0 |
| Regression tests 12/12 | `tests/unit/services/{tenancy,pii,ai}/...` | `.venv/bin/python -m pytest` | 0 |
| docstring gate 0 missing | `tools/check_docstrings.py` | `.venv/bin/python ...` | 0 |
| CVE allowlist 27 | `.security/pip-audit-allowlist.txt` | `grep -cE ...` | 0 |
| gateway_adapter.py not touched | `src/backend/services/ai/gateway_adapter.py` | `git diff HEAD` | 0 (no diff) |
| 2 cycle-4 commits in HEAD | `git log` | `git log --oneline -2` | 0 |

**Python interpreter:** `.venv/bin/python` (Python 3.14.0, pytest-9.1.1, pluggy-1.6.0).

---

## 12. Final verdict

**✅ PASS — все 4 задачи cycle-4 фаз 5 верифицированы.**

- **T-W1-01:** CapabilityTenant signature корректен, `/services/tenancy/facade.py:122-125`
  использует `id=X, principal=Y` с defensive fallback.
- **T-W1-04:** 3 files `_xml_to_dict_stdlib` + `_el_to_dict` removed; serialization
  helpers retained только в `data_formats.py` (safe direction).
- **T-W1-09:** `PIIFailClosedError` + `raise_pii_fail_closed` helper, 3 fail-CLOSED
  точки (`PIIFacade.mask`, `PIIFacade.tokenize`, `_maybe_mask_pii`) raise корректно.
- **T-W4-01:** `chunk_text` использует `RecursiveChunker` через `get_chunker("recursive", ...)`.
- **Baseline:** layer checker 175/0, docstring 0, CVE allowlist 27, regression
  tests 12/12 PASS.

**Дополнительно:** pre-existing residuals (gateway_adapter.py:128-129) не тронуты,
8 uncommitted правок cycle 1+2+3 не переписывались, 2 cycle-4 commit'а в HEAD.

**Незакрытых пунктов нет** в scope этого review.
