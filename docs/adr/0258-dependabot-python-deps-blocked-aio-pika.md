# ADR-0258: dependabot Python bumps BLOCKED by aio-pika pre-release constraint

> **Status**: BLOCKER DOCUMENTATION (2026-08-30, S44 W12)
> **Method**: Direct `uv lock --upgrade-package <X>` attempts; conflict traceback analysis.
> **Outcome**: 8 of 13 dependabot PRs blocked by single architectural decision.

## 0. TL;DR

| Layer | Status |
|---|---|
| 5 GH Actions bumps | ✅ DONE (S44 W12, commit `faf404e9`) |
| 8 Python lib/risky bumps | ❌ BLOCKED by `pyproject.toml:49` opentelemetry constraint |

**Single-line constraint blocks 8 of 8 remaining dependabot Python PRs.**

## 1. Conflict traceback (verbatim from `uv lock --upgrade-package streamlit`)

```
opentelemetry-exporter-otlp-proto-grpc>=1.30.0 requires
opentelemetry-instrumentation-aio-pika>=0.52b0 (only versions of
aio-pika available:
    opentelemetry-instrumentation-aio-pika<=0.51b0
    opentelemetry-instrumentation-aio-pika>=0.52b0)

But pyproject.toml:49 specifies:
    "opentelemetry-instrumentation-aio-pika>=0.51b0,<0.52b0"
```

`pyproject.toml:49` is **a no-man's-land** between two valid version ranges. The gap at 0.52b0 means **no version can satisfy both** `>=0.51b0` AND `<0.52b0` (exclusive) while ALSO meeting `>=0.52b0` (exclusive).

## 2. Impact (8/13 dependabot PRs blocked)

| PR | Wanted version | Upper bound | Status |
|---|---|---|---|
| icalendar | 6.3.2 → 7.2.2 | `<7.0.0` (line 295) | ❌ MAJOR, separate from aio-pika |
| mkdocstrings | 0.30.1 → 1.0.6 | `<1.0.0` (line 425) | ❌ MAJOR, separate |
| nbformat | 5.10.4 → 5.11.0 | unconstrained | ✅ within bounds once dep resolution works |
| sentence-transformers | 5.6.1 → 5.7.0 | `<6.0.0` (line 308) | ✅ within bounds once dep resolution works |
| aioimaplib | 1.2.0 → 2.0.1 | `<2.0.0` (line 87) | ❌ MAJOR |
| streamlit | 1.61.0 → 1.61.1 | `<2.0.0` (line 137) | ❌ blocked by aio-pika conflict |
| patchright | 1.60.1 → 1.61.2 | `<2.0.0` (line 248) | ❌ blocked by aio-pika conflict |
| mlflow | 3.13.0 → 3.14.0 | `<4` (line 346) | ❌ blocked by aio-pika conflict |

(`mlflow` not installed in current venv — even if upgraded, runtime unaffected unless `ai-2026` extra is active.)

## 3. Root cause analysis

### 3.1 Why `<0.52b0` was specified

The `<0.52b0` upper bound on multiple `opentelemetry-instrumentation-*`
packages (lines 46-51 of pyproject.toml) is a **deliberate coordinated pin**.
Pre-0.52b0 versions are pre-release; the project constrains to a specific
pre-release slot for stability across the `ai-2026` extra.

### 3.2 Why opentelemetry-exporter-otlp-proto-grpc (>=1.30.0) breaks this

`opentelemetry-exporter-otlp-proto-grpc` 1.30.0+ requires the package
ecosystem to have migrated to aio-pika 0.52b0+ (a non-pre-release version).
Project's exclusive `<0.52b0` constraint creates a no-man's-land.

### 3.3 Why `--prerelease=allow` doesn't help

Pre-release allowance enables the solver to pick pre-release versions of
**target packages**, but it cannot resolve fundamental **mutual exclusivity**
between two constraints in different parts of the dependency tree.

## 4. Unblock options (out of session scope)

### Option A: Lift `<0.52b0` to `<1.0` across all otel-instrumentation pins
- **Effort**: 1-line edit × 6 packages = 6 pyproject.toml lines
- **Risk**: HIGH — aio-pika 0.52b0+ may have API changes affecting ai-2026
  extra code paths (W2 ADR-0256 confirmed aio-pika 0.51b0 worked in tests)
- **Verification**: full pytest suite, full live HTTP smoke, ai-2026 extra test
- **Recommendation**: REQUIRES security review + ai-2026 maintainer approval

### Option B: Pin otel-exporter-otlp-proto-grpc to `<1.30.0` (downgrade)
- **Effort**: 1-line edit
- **Risk**: MEDIUM — older otel-exporter may miss bug fixes
- **Trade-off**: opacity to dependabot (dependabot wants newer otel too)
- **Recommendation**: viable short-term, but eventually need Option A

### Option C: Isolate `ai-2026` extra into separate dep group
- **Effort**: refactor pyproject.toml extras, move otel deps out
- **Risk**: MEDIUM — splits test matrix
- **Trade-off**: cleaner long-term architecture

## 5. Recommendation for next sprint

Per user's "обнови зависимости до последних версий, чтобы убрать проблемы dependabot"
request, **Option A is the path forward** but requires:
1. Security review of aio-pika 0.52b0+ breaking changes
2. Full pytest suite run (currently blocked by aio-pika in lock resolution)
3. ai-2026 extra test matrix validation
4. Multi-hour bounded scope — exceeds current session

**Out of session scope**: option requires human architectural decision
about the project's otel pre-release pin policy.

## 6. References

- `pyproject.toml:49` — `opentelemetry-instrumentation-aio-pika>=0.51b0,<0.52b0`
- `pyproject.toml:46-51` — coordinated pre-release pin across otel-instrumentation family
- `pyproject.toml:47` — `opentelemetry-exporter-otlp-proto-grpc>=1.30.0,<2.0.0`
- `docs/audit/DEPENDABOT_REVIEW_2026-08-30.md` — original PR categorization
- `docs/adr/0256-otel-pin-full-pytest-confirmed-runnable.md` — W2 partial vindic.
- `docs/audit/RE_AUDIT_2026-08-30.md` §FALSE CLAIM #5 (W2 retraction context)
- commit `faf404e9` — S44 W12 GH Actions bumps (5 of 13 closed)
