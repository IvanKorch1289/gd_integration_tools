# ADR-0077: Sandbox Decision — E2B for Production, NoOp for Dev

**Status:** Accepted
**Date:** 2026-05-26
**Authors:** К4
**Sources:** S28 W7, AI Audit 2026-05-26

---

## Context

S28 W7 requires a formal decision on the code execution sandbox strategy.
Three candidates were evaluated:

1. **E2B** (`e2b-code-interpreter`) — cloud-hosted Python sandbox with SDK;
2. **Pyodide** — WebAssembly Python runtime in browser/Node.js;
3. **NoOp** — reject all code execution.

The system executes user-submitted Python code from plugins via
`PluginSandboxAdapter.run()` (S14 W2). The decision governs which backend
handles this in production vs development environments.

---

## Decision

**E2B for production (self-hosted compatible). NoOp for missing credentials.
Pyodide deferred — not suitable for backend server-side execution.**

### Rationale

| Criterion | E2B | Pyodide | NoOp |
|-----------|-----|---------|------|
| Production ready | Yes (SDK v2) | No (browser-only) | N/A |
| Self-hosted | Partial (BYOC) | N/A | Yes |
| Python 3.14 support | Yes | Uncertain | Yes |
| Code isolation | Strong (VM-level) | Weak (WASM) | Full |
| Artifact support | Yes (files) | Limited | No |
| Latency | ~500ms cold start | ~100ms (cached) | 0ms |

**E2B** is the only option that provides production-grade VM isolation,
artifact persistence, and a stable SDK with self-hosted (BYOC) option for
data-sensitive deployments.

**Pyodide** runs in WebAssembly — designed for browser/Node.js environments.
Server-side Python execution with Pyodide requires significant engineering
(persistent WASM instances, filesystem abstraction, IPC) that is out of scope
for S28. Deferred to a future wave if browser-based code execution is needed.

**NoOp** is the correct fallback when `E2B_API_KEY` is not set — code
execution is rejected with `PluginSandboxError`, preventing accidental
unrestricted execution.

---

## Implementation

`sandbox.py` already implements this decision:

- `mode == "e2b"` → calls `E2BSandbox.run()` (production)
- `mode == "none"` → raises `PluginSandboxError` (enforced by policy R-V15-4)
- E2B SDK not installed → `NoOpSandbox` registered with warning

No code changes required. This ADR documents the existing implementation
and formally closes the Pyodide option.

---

## Consequences

- **Accepted**: E2B is the production sandbox. `e2b-code-interpreter` stays
  in `[ai]` extra.
- **Deferred**: Pyodide — revisit if browser-based execution is required
  (not a backend use case).
- **NoOp**: Correctly prevents code execution without E2B credentials.
  Capability `code.execute` gate still checked before sandbox invocation.

---

## Notes

- E2B BYOC (Bring Your Own Cloud) supports self-hosted control plane —
  relevant for compliance-sensitive deployments. Evaluate in S29 if needed.
- For local development without E2B credentials, use `mode = "none"` and
  test plugins via unit tests with mocked sandbox results.
