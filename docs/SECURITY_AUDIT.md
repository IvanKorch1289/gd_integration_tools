# Security Audit Report — S40 W6

**Scope:** `src/backend/` (1478 .py files, 231 109 LOC)
**Date:** 2026-06-04
**Tools:** `grep` (regex sweep) + `bandit 1.9.4`
**Mode:** analyze-only, no source modifications

---

## 1. Executive Summary

| Category                                       | Count | Severity     |
|------------------------------------------------|------:|--------------|
| Hardcoded production secrets                   |     0 | OK           |
| Hardcoded placeholders / dev stubs             |     2 | Low          |
| Suspicious docstring example values (non-runtime) |  6 | Informational |
| Bandit HIGH                                    |     2 | Action       |
| Bandit MEDIUM                                  |    44 | Review       |
| Bandit LOW                                     |   147 | Backlog      |
| **Bandit total**                               | **193** | |
| HTTP (non-TLS) literals in code                |    42 | Mostly OK    |
| HTTPS literals in code                         |    87 | OK           |
| `hashlib.md5` / `sha1` usages                  |     3 | Low          |
| `pickle.loads` usages                          |     1 | Low (gated)  |
| `eval` / `exec` (dynamic)                      |     0 | OK           |
| `subprocess shell=True`                        |     0 | OK           |
| `verify=False` (TLS bypass)                    |     0 | OK           |

**Posture:** acceptable for production. The two HIGH findings are localized
and gated by `# noqa: S324` for non-security use. No real credentials live
in the source tree; secret material is read from Vault at runtime
(`src/backend/infrastructure/secrets/vault_client.py`).

---

## 2. Hardcoded Secrets

### 2.1 Real production secrets — 0
No API key, password, token, or AWS access string is embedded as a real
value in any production path. All credential fields are either
`Pydantic Field(default=None, …)` or `os.environ.get(…)` lookups.

### 2.2 Placeholders (intentional, dev-only) — 2

| File:Line                                       | Value                                  | Status   |
|-------------------------------------------------|----------------------------------------|----------|
| `src/backend/services/auth/ad_directory_client.py:34` | `bind_password="<from-vault>"`         | Doc placeholder, resolved at runtime. |
| `src/backend/dsl/builders/notify.py:207`        | `password="DEV_PASSWORD_PLACEHOLDER"`  | Annotated `# dev-only; prod — через Vault`. |

**Action:** add a runtime guard in `core/config/loader.py` that fails fast
if `DEV_PASSWORD_PLACEHOLDER` is detected in a non-`dev` profile.

### 2.3 Docstring / example values (non-runtime) — 6
`express_bot.py:216`, `telegram_bot.py:199`, `webhook_signature.py:11`,
`enrichment.py:127`, `enrichment.py:349`, `sources_mixin.py:536` — all
inside docstring snippets, not executed. **Action:** reword to
`<BOT_ID>` / `<SECRET_KEY>` style to avoid CI secret-scanner false positives.

### 2.4 Filtered false positives
`pii_token_map`, `password_from`, `token_map_property` are config field
names (correctly suppressed via `# noqa: S105/S107`). `auth_token="<redacted>"`
in `graphql_query.py:165` is an explicit redaction marker. The
`ai_sanitizer.py:57–66` dict stores *masks* (`"***"`, `"[KEY]"`), not real
credentials.

---

## 3. Bandit Security Audit

### 3.1 Summary
```
H severity:   2  (B324 — weak MD5 hash, x2)
M severity:  44  (top: B608 SQL x32, B314 XML x4, B104 bind x3)
L severity: 147  (top: B110 try/except pass x74, B101 assert x26,
                  B311 stdlib random x15, B105 hardcoded-pass x12,
                  B112 try/except continue x10, B107 hardcoded-default x5)
Total:      193  over 185 917 LOC scanned
```

### 3.2 HIGH-severity findings (full list)

| # | File:Line                                   | Test | Issue                                                            |
|---|---------------------------------------------|------|------------------------------------------------------------------|
| 1 | `src/backend/ai/rag/docs_indexer.py:45`     | B324 | `hashlib.md5(tok.encode())` — weak MD5 hash for security.        |
| 2 | `src/backend/services/ai/rag/docs_indexer.py:46` | B324 | Same pattern (duplicate copy under `services/`).              |

**Context:** `_embed_offline()` is a deterministic hash-bucketing embedder
(unit-test fallback), **not** a security primitive. Both sites already
carry `# noqa: S324`. **Fix:** pass `usedforsecurity=False` — same pattern
as `src/backend/dsl/engine/processors/generic.py:218` (SHA1, also non-security).

### 3.3 MEDIUM findings — top categories

| Test  | Count | Title                                                                | Disposition                                                         |
|-------|------:|----------------------------------------------------------------------|---------------------------------------------------------------------|
| B608  |    32 | SQL injection via string-based query construction.                  | All `# noqa: S608`, identifiers are DSL-provided, not user input.  |
| B314  |     4 | `xml.etree.ElementTree.fromstring` on untrusted XML.                 | Migrate to `defusedxml`; suppress only on proven-trusted sources.  |
| B104  |     3 | Bind on `0.0.0.0`.                                                   | Intentional for in-cluster pods; gate behind config flag.          |
| B615  |     2 | Hugging Face Hub download without `revision=` pinning.               | **Action:** add `revision=` (digest or tag).                       |
| B310  |     1 | `urlopen` audit for permitted schemes.                               | Add scheme allowlist.                                               |
| B301  |     1 | `pickle` deserialization (see §6).                                   | Already gated.                                                      |
| B108  |     1 | Insecure temp file usage.                                            | Use `tempfile.NamedTemporaryFile(delete=True)`.                    |

B608 hot-spots: `dsl/engine/processors/batch.py:80,140,195` and
`storage_ext.py:152`, `ml_inference.py:343` (f-string for table name;
column names from DSL schema).
B104 sites: `core/config/validator.py:581`, `core/scaling/granian_tuning.py:170`,
`workflows/worker_probes.py:74`.
B615 sites: `services/ai/rag/multimodal/blip2_captioner.py:71-72`.

### 3.4 LOW findings — top categories

| Test  | Count | Action                                                                  |
|-------|------:|-------------------------------------------------------------------------|
| B110  |    74 | `try/except: pass` → `logger.debug(...)`.                              |
| B101  |    26 | `assert` in production paths → `if not …: raise`.                      |
| B311  |    15 | `random` (stdlib) for routing — `# noqa: S311` where non-security.      |
| B105  |    12 | Hardcoded-password string — all 12 are masking placeholders (see §2.4). |
| B112  |    10 | `try/except: continue` — log before continue.                           |

---

## 4. HTTP vs HTTPS Ratio

* HTTP (non-TLS) literals: **42** across 26 files.
* HTTPS (TLS) literals: **87** across 51 files.
* **Ratio:** 1 : 2.07 (HTTPS-dominant).

All 42 HTTP occurrences fall into one of three buckets:

1. **Localhost / in-cluster defaults** (`http://vault:8200`,
   `http://otel-collector:4317`, `http://mlflow:5000`, `http://localhost:11434`,
   `http://windows-worker:9001`, `http://searxng:8080`, `http://nextcloud:80`,
   `http://influxdb:8086`) — internal cluster traffic where sidecar/pod-to-pod
   mTLS is enforced by the service mesh. **No action.**
2. **Docstring examples** (`mcp_tool.py:18`, `openapi_generator.py:68`,
   `bpmn_importer.py`) — non-runtime. **No action.**
3. **Config-schema defaults** (`core/config/{rag,elasticsearch,ai,base}.py`)
   — overridable by env/profile. **Audit once:** ensure production
   `config_profiles/prod.yaml` does not inherit the HTTP default for any
   external API (Dadata, SKB, antivirus).

**Action:** add a `make security-http-audit` CI check that fails build if
any non-`localhost`/non-`*.local` `http://` literal appears in
`src/backend/entrypoints/` or `src/backend/infrastructure/clients/`.

---

## 5. Weak Hash Usage (MD5 / SHA1) — 3 sites

| File:Line                                       | Hash | Purpose                                     | Fix                          |
|-------------------------------------------------|------|---------------------------------------------|------------------------------|
| `src/backend/ai/rag/docs_indexer.py:45`        | MD5  | Deterministic token→bucket embedder (unit)  | Add `usedforsecurity=False`. |
| `src/backend/services/ai/rag/docs_indexer.py:46`| MD5  | Duplicate copy of the above.                | Same.                        |
| `src/backend/dsl/engine/processors/generic.py:218` | SHA1 | Consistent-hash routing shard.            | Already uses `usedforsecurity=False` — good reference pattern. |

**Action:** one-line fix to the two MD5 sites, plus a CI grep
(`grep -rE 'hashlib\.(md5|sha1)\(' --include='*.py' src/backend/`) to keep
the count at zero.

---

## 6. Unsafe Deserialization (`pickle.loads`) — 1 site

| File:Line                                          | Code excerpt                                                  |
|----------------------------------------------------|---------------------------------------------------------------|
| `src/backend/dsl/builders/converters_mixin.py:426` | `return pickle.loads(raw)  # noqa: S301`                     |

**Context:** symmetric round-trip on the project's own msgpack output
(`_to_msgpack` / `_from_msgpack`, lines 398–426). Input is data the current
process produced (or a sibling process in the same deployment emitted);
the fallback to pickle exists only when `msgpack` is not installed
(dev_light profile).

**Action:** keep `# noqa: S301` and add a cheap guard —
`raw[:4] not in (b"\x80\x04\x95", b"\x80\x05\x95")` (PROTO+SHORT_BINUNICODE
opcodes) — to refuse anything that doesn't look like a plain-container
pickle. Alternative: switch the fallback to `json` (lossy but always safe).

---

## 7. Other Sweeps — all clean

* `eval` / `exec` dynamic execution: **0** runtime call sites
  (only `evaluator.eval(...)` on sandboxed `SimpleEval` — see
  `dsl/engine/processors/rule_engine.py:120`, `services/workflows/reactive_dispatcher.py:194`).
* `subprocess(..., shell=True)`: **0**.
* `requests.*(verify=False)`: **0**.
* `httpx.*(verify=False)`: **0**.

---

## 8. Prioritized Remediation Backlog

| Pri | Action                                                                    | Owner | ETA      |
|----:|---------------------------------------------------------------------------|-------|----------|
| P0  | Add `usedforsecurity=False` to two MD5 sites in `docs_indexer.py`.        | ai    | 1 hour   |
| P1  | Pin Hugging Face `revision=` in `blip2_captioner.py:71-72`.               | ai    | 1 day    |
| P1  | Wrap `0.0.0.0` bind in config-driven check (3 sites).                     | core  | 1 day    |
| P2  | Add `dev_password_placeholder` runtime guard in `config/loader.py`.       | sec   | 1 day    |
| P2  | Reword docstring example secrets to `<PLACEHOLDER>` style (6 sites).      | docs  | 1 day    |
| P3  | Convert 26 production `assert` to explicit `if/raise` (B101).             | core  | 3 days   |
| P3  | Replace 74 `try/except: pass` with `logger.debug(...)` (B110).            | core  | 1 week   |
| P3  | Move 12 `xml.etree` parses to `defusedxml` (B314).                        | integ | 1 week   |
| P4  | Add `make security-http-audit` CI check for external HTTP.               | sec   | 2 weeks  |

---

## 9. Verification

```bash
ls -la docs/SECURITY_AUDIT.md
.venv/bin/python -m bandit --version           # bandit 1.9.4
.venv/bin/python -m bandit -r src/backend/ -f json -o /tmp/bandit.json
```

Generated: 2026-06-04, Sprint 40 Wave 6.
**Not committed** — awaiting review per task spec.
