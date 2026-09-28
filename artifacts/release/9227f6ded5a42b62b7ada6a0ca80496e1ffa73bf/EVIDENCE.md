# Evidence — `9227f6ded` (gRPC test isolation)

All claims below were produced **after** the change landed, on this exact tree.
No result is carried over from an earlier SHA.

## Claim ledger

| Claim | Evidence command | Exit | Code path | Runtime/test | Counterevidence | Status |
|---|---|---:|---|---|---|---|
| gRPC cluster is green | `pytest tests/unit/entrypoints/grpc -q` | 0 | `tests/unit/entrypoints/grpc/test_file_stream.py::_install_protobuf_stubs` | 66 passed ×5 random seeds | none found | **VERIFIED** |
| Bug was real at parent SHA | same command on `ac776e490` | 1 | same | 3 failed / 63 passed ×3 seeds | — | **VERIFIED** |
| Fix is the cause, not luck | minimal diff = 1 fixture file | 0 | only `_install_protobuf_stubs` changed | reverting restores 3 failures | — | **VERIFIED** |
| Stub now matches production | `grep '^\s*rpc ' protobuf/{files,invoker}.proto` | 0 | `grpc_server/file_stream.py:58` | 4 + 1 RPC names match | — | **VERIFIED** |
| No assertion was weakened | `git diff --stat` | 0 | 1 file, +15/-0 | diff contains no test assertion | — | **VERIFIED** |
| `make ci` passes | `make ci` | 0 | — | 20752 tests collected, "CI gate passed" | 10 output markers checked individually, all benign | **VERIFIED** |
| Frontend isolation still broken | not re-measured this cycle | — | — | — | — | **NOT VERIFIED** |
| `mcp` cluster | `pytest tests/unit/entrypoints/mcp -q` | 1 | — | 8 failed / 98 passed / 1 xfailed, 305.74 s | — | **FAIL (pre-existing)** |

## Root cause

`test_file_stream.py::_install_protobuf_stubs()` runs at **module level** and
installs `FileServiceServicer = type("Stub", (), {})` — an empty base class. A
servicer imported while that stub is in `sys.modules` inherits it permanently:

```
class FileStreamGRPCServicer(BaseGRPCServicer, FileServiceServicer)
```

Rolling back `sys.modules` cannot repair this — by then the class object
already exists with the stub baked into its MRO. Because the empty base had no
RPC methods, `DeleteFile` and `GetFile` were absent from the MRO, and three
tests in *sibling* files failed:

- `test_grpc_getattr_fallback.py::test_method_dict_attr_works_daudit_19801`
- `test_grpc_subclass_methods_patch.py::test_delete_file_has_request_streaming`
- `test_grpc_subclass_methods_patch.py::test_get_file_has_request_streaming`

The failing tests were **correct**. They assert on `_patch_rpc_methods()`
(the NEW-12 fix) for RPCs that genuinely exist in `files.proto`. The stub was
the defective artefact, so the fix edits the stub, not the assertions.

## Why the stub now lists these four methods

`files.proto` declares exactly four RPCs, and `invoker.proto` exactly one.
`FileStreamGRPCServicer` declares `DownloadFile` and `UploadFile` itself; the
other two are inherited from the generated base. The stub now reproduces that
surface:

```
files.proto:  GetFile  DeleteFile  DownloadFile  UploadFile
invoker.proto: Invoke
```

Names were read from the `.proto` sources, not assumed.

## Before / after

| Run | Result |
|---|---|
| HEAD `ac776e490`, full grpc dir, 3 random seeds | `3 failed, 63 passed` |
| `9227f6ded`, full grpc dir, 5 random seeds | `66 passed` |
| `9227f6ded`, each of the 7 files standalone | 15 / 8 / 17 / 4 / 4 / 12 / 6 passed |

## Two errors I made and corrected

Worth recording, because both were caught by experiment rather than reasoning:

1. I also edited `test_grpc_server.py`. That was **scope creep** — the three
   failures live in other files, and `test_file_stream.py` alone is the
   poisoner. Worse, my edit there accidentally deleted the `elif "orders"`
   branch (making `_order_methods` dead code) and the two unconditional
   `add_*_to_server` assignments, which broke 12 tests in that file when run
   standalone. Reverting it removed both regressions; the single-file diff is
   the correct one.
2. My first reproduction attempt showed both two-file orderings passing at
   HEAD, which appeared to contradict the failure. The trigger is the whole
   directory, not the pair — the module-level stub only poisons siblings once
   a third file is collected. Chasing the pair would have "fixed" nothing.

## Wider measurement at this SHA

All 16 clusters under `tests/unit/entrypoints/`, run separately to stay under
the RAM ceiling:

| cluster | result | | cluster | result |
|---|---:|---|---|---:|
| grpc | 66 passed | | mqtt | 27 passed |
| api | 338 passed, 21 skipped, 4 xfailed, 3 xpassed | | scheduler | 15 passed |
| asyncapi | 11 passed | | sse | 36 passed |
| cdc | 10 passed | | stream | 16 passed |
| email | 33 passed, 1 skipped, 1 xfailed | | webhook | 12 passed |
| express | 17 passed | | websocket | 65 passed |
| filewatcher | 25 passed | | middlewares | 575 passed, 3 skipped |
| graphql | 30 passed, 1 skipped | | **mcp** | **8 failed**, 98 passed, 1 xfailed |
| http3 | 13 passed | | | |

A single combined `pytest tests/unit/entrypoints` run **cannot complete on
this machine**: it is SIGKILLed (exit 137) at ~47% by the OOM killer. That is
the same environment ceiling already recorded for the coverage runs, not a new
defect. Its failures, however, are attributable — all 8 are the `mcp` cluster
above, none in gRPC.
