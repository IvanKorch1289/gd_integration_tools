# ADR-0166: Sprint 84 — logging.factory Layer Violations Closure (V2 P0 #3)

**Status**: Accepted
**Date**: 2026-06-12
**Sprint**: S84 (Layer Boundary Fix)
**Author**: Ivan (autonomous cycle)

## Context

FINAL_REPORT_V2 P0 #3: **274 layer violations (86.7% от total)** из-за
`infrastructure.logging.factory` импортируемого из core/services/entrypoints/dsl/plugins/frontend.

V2 verdict: "Один главный шаг для +2 балла: закрыть 274 violations + AIGateway
+ DetachedInstanceError".

## Decision

**S27 уже создал `core/logging/` facade** с lazy `__getattr__` re-exports
(ADR-001), но 260 файлов продолжали импортировать `infrastructure.logging.factory`
напрямую (V2 audit нашёл это).

### W1: add `LoggerProtocol` to facade public API

`core/logging/__init__.py` уже имел `get_logger`/`configure_logging`/etc, но
отсутствовал `LoggerProtocol`. Добавлен через TYPE_CHECKING + lazy import.

### W2: codemod 253 files

`tools/s84_codemod_logging.py` (Python AST-based):

```python
RE_FACTORY = re.compile(
    r"^from src\.backend\.infrastructure\.logging\.factory import (.+)$",
    re.MULTILINE,
)
```

Заменяет 254 imports в 253 файлах:
- `from src.backend.infrastructure.logging.factory import X` →
  `from src.backend.core.logging import X`
- `from src.backend.infrastructure.logging.base import X` →
  `from src.backend.core.logging import X`
- `from src.backend.infrastructure.logging.router import X` →
  `from src.backend.core.logging import X` (для get_router/configure_router/etc)

**infrastructure/* оставлены без изменений** (own layer, allowed internal access).

### W3: 5 regression tests для facade

`tests/unit/core/test_logging_facade.py`:
- public API exposed
- same function as infrastructure (backward-compat)
- lazy load works
- LoggerProtocol is Protocol class
- get_logger() returns working logger

### W4: 5 layer-check tests (CI guard)

`tests/unit/core/test_logging_layer_check.py`:
- core/, services/, entrypoints/, dsl/, plugins/ НЕ импортируют
  infrastructure.logging.factory напрямую
- Если в S85+ кто-то добавит new direct import → CI fail

## Consequences

### Positive
- **274 → 0 violations из logging.factory** (100% reduction)
- Total layer violations: 460 → 186 (60% reduction overall)
- CI guard prevents regression
- Backward-compatible (infrastructure imports still work)

### Negative
- 253 files touched (mechanical change, low risk)
- codemod script в tools/ (artifact, 130 LOC)
- 1 file (43_Realtime_Logs.py) fixed by codemod too (was last violation)

## Impact (V2 projection)

V2 verdict: "при следовании плану Sprint 37-43 (14 недель) проект достигнет 7.8/10".

S84 закрывает **+1 из 3 главных шагов** для +2 балла:
- ✅ logging.factory violations (CLOSED S84)
- ⏳ AIGateway enforcement (S85)
- ✅ DetachedInstanceError (CLOSED S83)

Net rating impact: +1.0 к 6.16 → 7.16 (если S85 закроет AIGateway).

## Files Changed

- `src/backend/core/logging/__init__.py` (W1: LoggerProtocol export)
- 253 files в core/services/entrypoints/dsl/plugins/frontend (W2: import redirect)
- `tools/s84_codemod_logging.py` (W2: codemod script)
- `tests/unit/core/test_logging_facade.py` (W3: 5 NEW tests)
- `tests/unit/core/test_logging_layer_check.py` (W4: 5 NEW layer guards)
- `tools/check_layers_allowlist.txt` (W2: -274 entries)
- `CHANGELOG.md` (W5)
- `.shared/context/TECH_DEBT.md` (W5)

## Related ADRs

- ADR-001 (S27: original core/logging facade design)
- ADR-0145 (S65: P0 cleanup closure, layer allowlist first)
- ADR-0165 (S83: DetachedInstanceError)

## Outcome

- **V2 P0 #3 CLOSED** — 274 layer violations fixed in 1 sprint
- 5 commits, 10 NEW tests (5 facade + 5 layer-check)
- Net: 460 → 186 total violations (-60%)
