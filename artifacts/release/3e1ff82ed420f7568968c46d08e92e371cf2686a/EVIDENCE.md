# Evidence — `3e1ff82ed` (frontend cluster: 23 failures → 5)

Two commits: `1bbf9e909` (a real production bug) and `3e1ff82ed` (test
pollution). Both measured on this tree after landing.

## Claim ledger

| Claim | Evidence command | Exit | Code path | Runtime/test | Counterevidence | Status |
|---|---|---:|---|---|---|---|
| Marketplace fallback was unreachable | runtime probe with `httpx.ConnectError` | 1 | `plugin_marketplace_client.list_plugins` | before: `LEAKED ConnectError` | — | **VERIFIED (bug)** |
| …and is reachable after the fix | same probe | 0 | same | after: fallback list of 4 | — | **VERIFIED (fixed)** |
| Siblings had a latent `UnboundLocalError` | probe with `httpx` import blocked | 1 | `get_plugin_manifest`, `toggle_plugin` | before: `UnboundLocalError: cannot access local variable 'httpx'` | — | **VERIFIED** |
| …now an honest `ImportError` | same probe | 0 | same | after: `ImportError: No module named 'httpx'` | — | **VERIFIED (fixed)** |
| New tests are not vacuous | revert production, re-run | 1 | — | 4 failed / 2 passed | — | **VERIFIED** |
| Stubs leaked for the whole session | full frontend cluster | 1 | `test_components.py` module level | 23 failed / 426 passed | — | **VERIFIED (bug)** |
| Attribution: 9 from leak #1 | cluster with the file excluded | 1 | — | 12 failed / 429 passed | — | **VERIFIED** |
| …plus 7 more from leak #2 | cluster after the fix | 1 | — | 5 failed / 446 passed | — | **VERIFIED** |
| `make ci` passes | `make ci` | 0 | — | 20760 collected, "CI gate passed" | 10 markers, all benign | **VERIFIED** |
| Frontend layer boundaries clean | 5 ratchet tests | 1 | — | 6 upper-layer + 12 facade violations | — | **FAIL (real, untouched)** |

## 1. A real production bug, found because the test was right

`list_plugins()` documents: *"При недоступности backend возвращает mock-список
для dev-окружения"*. It did not.

`httpx.ConnectError` is **not** a subclass of builtin `ConnectionError`:

```
ConnectError → NetworkError → TransportError → RequestError → HTTPError → Exception
```

Nothing in `except (ConnectionError, TimeoutError, RuntimeError, ValueError,
TypeError)` matched, so the documented fallback was dead code for both likely
failure modes — connection refused, and `raise_for_status()` on 4xx/5xx.
`get_plugin_manifest` and `toggle_plugin` already listed `httpx.HTTPError`;
`list_plugins` was simply missed by that earlier fix. A helper
`_is_transport_error()` at line 91 already matches `httpx.TransportError`
correctly and is **dead code** — never called. Left in place to keep the diff
minimal.

A second, latent defect affected all three: `import httpx` sat *inside* the
`try` while `httpx.HTTPError` was named in the `except` tuple. Importing inside
a function makes the name local, so when the import itself failed, evaluating
the tuple raised `UnboundLocalError: cannot access local variable 'httpx'`.
That contradicts the module docstring ("модуль не требует httpx"). The import
now precedes the `try` in all three.

Runtime, before → after:

| scenario | before | after |
|---|---|---|
| `httpx.ConnectError` | `LEAKED ConnectError` | fallback list of 4 |
| HTTP 500 via `raise_for_status` | (fallback unreachable) | fallback list of 4 |
| `httpx` not installed | `UnboundLocalError` | honest `ImportError` |

Reverting the production fix fails all 4 tests in the file, so none is
vacuously green.

## 2. Test pollution: two leaks from one file

`test_components.py` installed its `streamlit` and `pandas` mocks at **module
level** — i.e. during collection — and never restored them.

**Leak #1 — `sys.modules` poisoned.** `streamlit` stayed a 4-attribute module
and `pandas` a module with only `DataFrame` for the whole process. Anything
importing `import streamlit as st` afterwards got the mock; `api_clients/
cached.py` died on `@st.cache_data(...)` with `AttributeError: module
'streamlit' has no attribute 'cache_data'`.

**Leak #2 — the module under test was cached against the mock.**
`from ...shared.components import ...` ran at collection time while the stubs
were active, so the cached `components` module permanently held a `st` bound to
the mock. Every later importer inherited that.

Both are now scoped by a module-scoped `components_env` fixture that installs
the stubs, imports the module under test, and restores `sys.modules` in
teardown, popping `components` on both sides.

### Why two measurements were needed

| run | result |
|---|---|
| full cluster, before | 23 failed, 426 passed |
| full cluster **with this file excluded** | 12 failed, 429 passed |
| full cluster, after the fix | 5 failed, 446 passed |

The excluded-file run says the file caused 9 failures. The fix removed 18.
The extra 7 were leak #2, which that floor could not reveal — removing the
*file* still leaves the poisoned `components` module in `sys.modules`. Only
running the fixed file against the cluster exposed it.

## 3. The 5 that remain are correct failures

All five are layer-boundary ratchets (`test_layer_boundary.py` ×3,
`test_arch_ratchet.py` ×2), reporting real violations in frontend production
code:

- 6 files import `from src.backend.services` (an upper layer)
- 12 facade-boundary violations, including
  `src.backend.core.registry_explorer`, `src.backend.core.cost_attribution`,
  `src.backend.core.interfaces.import_gateway`, `src.backend.services.dsl_portal`

These are **not** test defects. The gates are the ratchet doing its job, and
editing them to pass would hide exactly what they exist to catch. They remain
an open blocker.

Note this also corrects an earlier note in the canonical doc, which described
this cluster as failing "only in combined runs". It fails in isolation too:
with `-p no:randomly` the same 23 failures appear. What actually varies is
whether the polluting file is collected into the process.
