# cycle-8 / D-AUDIT-805 — T-C8-05-DEAD-RELIABILITY

**Task:** remove dead `src/backend/dsl/engine/processors/eip/reliability.py` (442 LOC orphan)
**Plan ref:** cycle-4 phase-1/06-dsl.md DSL-P2-001
**Status:** ✅ **NO-OP — already resolved before cycle 8 (stale task premise)**

## Findings

The target file does **not exist**. It was removed in commit `e96dda55`
(`refactor(dsl): remove 442 LOC legacy eip/reliability.py god-file`), which is
an ancestor of current HEAD `f06d7856`.

```
$ ls src/backend/dsl/engine/processors/eip/reliability.py
ls: src/backend/dsl/engine/processors/eip/reliability.py: Нет такого файла или каталога

$ git log --oneline -1 -- src/backend/dsl/engine/processors/eip/reliability.py
e96dda55 refactor(dsl): remove 442 LOC legacy eip/reliability.py god-file
```

This is corroborated by cycle-4 `PHASE-2-SUMMARY.md:71`, which already recorded
`eip/reliability.py -442 LOC` as a downstream commit outside that cycle's scope.

## Why the specified test assertion must NOT be applied

The task asked to verify that
`.venv/bin/python -c "import src.backend.dsl.engine.processors.eip.reliability"`
**fails**. It succeeds — and that is correct, not a regression:

```
$ .venv/bin/python -c "import src.backend.dsl.engine.processors.eip.reliability as m; print(m.__file__)"
/home/user/dev/gd_integration_tools/src/backend/dsl/engine/processors/eip/reliability/__init__.py   # exit=0
```

The name `...eip.reliability` now resolves to a **live package directory**
(`reliability/`, 675 LOC across 6 modules), not the deleted flat module. The
442 LOC file was never a true orphan: it was *shadowed* by this package, so
Python always resolved imports through `reliability/__init__.py`. Removing it
deleted dead code without changing any import target.

The package has real consumers:

| Consumer | Line |
| --- | --- |
| `src/backend/dsl/engine/processors/eip/__init__.py` | 64 |
| `tests/unit/dsl/engine/processors/eip/test_s56_w3_eip_reliability.py` | 19, 41 |
| `tests/unit/dsl/engine/processors/eip/test_processor_decorator_cycle38.py` | 18 |

Making that import fail would break the EIP processor registry and 41 tests.
**No change was made.**

## Verification

```
$ .venv/bin/python -m pytest \
    tests/unit/dsl/engine/processors/eip/test_s56_w3_eip_reliability.py \
    tests/unit/dsl/engine/processors/eip/test_processor_decorator_cycle38.py -q
41 passed in 14.76s
```

Preflight (`bash tools/cycle-1-preflight.sh`) — exit 1, **pre-existing, not
caused by this task** (no source files were touched):

```
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 27
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 37 entries
  [OK]   uv.lock churn — 0 diff lines
  [OK]   s3.py untouched — не modified
```

The 37 dirty entries are other agents' untracked `docs/audit/.../cycle-*/`
reports, `.blue_green.state`, and a modified
`src/backend/services/ai/gateway/client.py` — all outside this task's scope.
Gates within budget: layer 175/0 ✓, allowlist 27 ✓, uv.lock 0 new lines ✓.

## Outcome

No code change, no commit. Only this report is added. The DSL-P2-001 dead-code
item is closed as **already fixed upstream**; the residual 89 LOC `_legacy.py`
compat shim inside the package is live (re-exported header constants and type
aliases) and is out of scope here.
