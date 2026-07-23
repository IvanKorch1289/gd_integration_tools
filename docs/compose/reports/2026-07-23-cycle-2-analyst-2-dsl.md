# Cycle 2 — Analyst 2 (DSL processors) — Consolidated

**Status**: success
**Files scanned**: ~401 .py across `dsl/engine/processors/`, `dsl/builders/`, `dsl/orchestration/`, `dsl/codec/`, `dsl/contracts/`, `dsl/workflow/`

## P0 (capability/auth checks missing)
1. `src/backend/dsl/engine/processors/security/pii_erase.py:71` — `PiiEraseProcessor` no `required_capability` + no `auth_check()`
2. `src/backend/dsl/engine/processors/security/card_tokenize.py:139` — `CardTokenizeProcessor` no `required_capability` + no `auth_check()`
3. `src/backend/dsl/engine/processors/storage/s3.py:84,179,235,299,339` — 5 S3 processors missing `auth_check()` despite having capability decorator
4. `src/backend/dsl/engine/processors/storage_ext.py:24,99,204` — Neo4jQuery/TimeSeriesWrite/PriorityEnqueue
5. `src/backend/dsl/engine/processors/agent_dsl/*.py` — 20+ files declare `required_capability` but **never invoke `self.auth_check()`** (massive authorization gap)

## P1
- 100 files layer-violation imports (dsl → services/infrastructure/entrypoints), worst: `dsl/orchestration/triggers.py:301` direct entrypoint import
- 290 instances of `Optional[X] = <non-None default>` (type mismatch), 5 specific cases flagged
- `eip/reliability/_legacy.py:39-44` — `__all__` lists 4 missing processor classes (dead re-exports)
- `dsl/builders/base/__init__.py:69` — `get_route_builder` in `__all__` but undefined
- **Duplicate banking AI processors**: `ai_banking/` (1284 LOC) vs `ai/banking_processors/` (615 LOC) with 6 IDENTICAL class names — import ambiguity risk

## P0 verified clean
- 0 bare `except:` (good)
- 0 real `from __future__` ordering violations (false positives eliminated with docstring-aware filter)
- 0 docstring-outside-docstring violations (the matches in `ai/banking_processors/` are legitimate `prompt_template` class fields)

## P2
- Naming inconsistency: `rpa/operations/` and `components/` use lowercase filenames (17+8 files); `ai/` mixed naming
- Magic numbers: 15+ instances of hardcoded timeouts/sizes (300.0s agent timeouts, 10000 batch sizes, etc.)
