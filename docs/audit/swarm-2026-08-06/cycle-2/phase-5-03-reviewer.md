# Phase 5 reviewer — cycle 2

## Verdict: FAIL

Independent review of the current Phase 4 artifacts. No source, lockfile, allowlist, `s3.py`, or `blue_green` source was modified by this review.

## Evidence

- `bash tools/cycle-1-preflight.sh` — exit **1**. Layer checker, allowlist, docstring gate and `s3.py` checks passed, but working tree check failed (24 entries) and `uv.lock` churn failed (40 lines). The current tree includes unrelated/unapproved artifacts such as `.blue_green.state`, `pip-audit.json`, and `uv.lock` modification.
- `python` AST parse over all `git diff --name-only` Python files — exit **0**; all listed Python files reported `AST OK`.
- `ruff check $(git diff --name-only -- "*.py")` — exit **127**: `ruff` is not installed/available in the active environment.
- `python -m mypy ...` — unavailable or failed; no mypy result could be established.
- Requested focused pytest command — exit **2** during collection. Missing environment dependencies: `prometheus_client`, `argon2`, `fastapi`, and `email_validator`.
- Cycle-1 regression pytest command (multicast, redelivery, policy mixin, gateway adapter, embedding cache) — exit **2** during collection. Missing `prometheus_client`, `aiofiles`, and `hypothesis`.
- `git diff --check` was included in the inspection command and produced no whitespace diagnostics before the status output.

## Code review findings

1. **Blocking verification gap:** the required test suites cannot be collected in the current environment, so the Phase 4 behavior is not independently verified. This applies both to the requested security/auth tests and to all listed cycle-1 regression tests.
2. **Blocking tooling gap:** `ruff` and mypy are unavailable, so the required static checks are not complete.
3. **Blocking tree/lockfile hygiene:** preflight reports an unclean working tree and `uv.lock` churn. The lockfile diff removes `svcs` dependency/package records; this is outside the stated reviewer scope and must be explained or reverted by the owning change set.
4. **Potential security correctness concern:** `src/backend/dsl/engine/processors/security.py` only catches `AuthenticationProviderUnavailableError`; `importlib.import_module()` failures and malformed registry values can still propagate rather than consistently setting the exchange fail-closed state. This needs an explicit test/decision.
5. **Potential policy concern:** `src/backend/core/ai/gateway_pipeline_mixin/policy_mixin.py` catches `TypeError` from the capability checker and retries with the legacy one-argument form. If a canonical checker raises an internal `TypeError` after accepting the call, this fallback can mask a real implementation error; the behavior should be covered by a regression test or narrowed.

## Passed checks

- Changed Python files parse successfully with `ast.parse`.
- No whitespace errors observed from `git diff --check`.
- Diff inspection confirms the cycle-1 multicast constructor fix (`ExecutionEngine()`), redelivery exception tuple syntax, embedding cache TTL/LRU implementation, and gateway adapter fail-fast path remain present in the working tree. Their tests, however, were not executable due to collection dependencies.

## Required before PASS

- Restore/use the project test environment with required dependencies and rerun every requested test plus the cycle-1 regression tests.
- Make `ruff` and mypy available and record successful runs on changed files.
- Resolve the preflight working-tree failure and explain/remove unauthorized `uv.lock` churn.
- Add or document coverage for auth module import failure/malformed verifier registry and the capability-checker `TypeError` fallback semantics.
