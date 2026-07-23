# Cycle 2 — Analyst 8 (Config / Tests / Docs / Frontend) — Consolidated

**Status**: partial

## P0 — Test collection blockers
1. `tests/unit/ai/rag/test_docs_indexer.py:20` — `ImportError: cannot import name 'DocsIndexer' from 'src.backend.ai.rag.docs_indexer'` (real test rot)
2. `tests/unit/core/ai/policy/test_nemo_guard_fallback.py:17` — `ImportError: cannot import name '_NEMO_TO_LLM_GUARD_FALLBACK'` (real test rot)
3. `src/backend/infrastructure/database/database/initializer.py:222` — `resilient` decorator not imported → breaks 4+ test collection (transitive from Analyst #4)

## P0 — pyproject.toml dependency
- `fastapi>=0.116.0` (line 11) no upper bound; may resolve incompatible with `starlette>=1.3.1,<2.0.0`
- `opentelemetry-instrumentation-*` pins `>=0.51b0` no upper
- `strawberry-graphql[fastapi]>=0.262.0` unbounded
- `cryptography>=42.0.0,<46.0.0` overlaps with `mlflow` 3.x starlette conflict
- `opentelemetry-instrumentation-aiokafka>=0.51b0` vs `aiokafka>=0.12.0`
- `granian>=2.0.0` no upper
- ~80 env-related ModuleNotFoundError collection errors (test modules assume full venv)

## P2 — pyproject.toml metadata
- `[project]` lacks `classifiers`, `keywords`, `urls`, `license`
- `[tool.semantic_release] branch = "master"` (line 936) — out of sync with repo's `main` convention

## P1 — mypy overrides hiding issues
- 30+ `[[tool.mypy.overrides]]` blocks all set `ignore_missing_imports = true`
- Items like `"st_aggrid"`, `"xxhash"`, `"hdrh"` are not on PyPI (likely typos)
- `pyproject.toml:764` — comment-as-string-pin `"chromadb>=0.5.0,<2.0.0"` is unconventional TOML

## Config profiles
- 0 hardcoded secrets (verified with regex)
- `tools/config_audit.py` reports FAIL with 37-38 ORPHAN-GROUP findings across all 5 profiles (pre-existing baseline)
- Several hardcoded URLs: `botx.corp.example.ru`, `https://s3.prod.local`, `smtp-prod`, `graylog-prod` (placeholders not env-bound)
- `log.level: "DEBUG"` in base default for prod
- `http.ssl_verify: false` in base + `esbgreendata` literal for WAF

## Frontend
- 36+ Streamlit pages
- `tools/check_streamlit_deprecations.py` → 0 matches
- `tools/check_streamlit_security.py` → All security checks passed
- 8 `tools/check_secrets_simple.py` matches all in `tests/**` fixtures (not real secrets)
- `admin-react` is dist-only (no sources in repo, properly gitignored)
- `docs/_build/` exists locally but properly gitignored
