"""T1.3.23 surgery: extract first 12 of 23 Sprint 19 fields to sprint19_dx.py.

Parallel state on disk (sprint5_k2 + sprint19_ai are racing siblings):
  - sprint5_k2 already added (T1.3.22) — class FeatureFlags already has it in MRO
  - sprint19_ai already added (T1.3.24) — already removed their 11 fields, MRO+import done
  - Our job (T1.3.23): remove 12 fields, add Sprint19DXFlags import+MRO+bullet

Methodology ('use Python not sed' to avoid T1.3.17 duplication):
  - anchor on field-name tokens (workflow_versioning_routes / testkit_public_api)
  - walk paren depth to find the exact end of the last field
  - use string slicing (byte-exact) on the original file content
  - re-build from captured substrings — no regex, no line-based munging
"""
from __future__ import annotations

from pathlib import Path

REPO = Path("/home/user/dev/gd_integration_tools")
INIT = REPO / "src/backend/core/config/features/__init__.py"
NEW = REPO / "src/backend/core/config/features/sprint19_dx.py"

TARGET_FIELDS = (
    "workflow_versioning_routes",
    "route_composition_include",
    "route_authz_requires_permission",
    "rag_multipart_ingest",
    "reranking_pipeline_enabled",
    "rpa_session_persistence",
    "banking_ai_processors_impl",
    "banking_ai_processors_enabled",
    "langmem_consolidation_impl",
    "vscode_extension_published",
    "lsp_server_strict",
    "testkit_public_api",
)
assert len(TARGET_FIELDS) == 12

src = INIT.read_text(encoding="utf-8")

# Idempotency: if we already did the surgery, bail
if "Sprint19DXFlags" in src:
    print("ERROR: Sprint19DXFlags already in __init__.py — refusing to re-run")
    raise SystemExit(1)

# 1) Locate the Sprint 19 header and the 12-field block boundaries
header_marker = "    # ─── Sprint 19 — DSL+AI Extensions + DX ────────────────────────────────"
hdr_idx = src.find(header_marker)
assert hdr_idx != -1, "Sprint 19 header not found"

first_field_token = f"\n    {TARGET_FIELDS[0]}: bool = Field("
first_idx = src.find(first_field_token, hdr_idx)
assert first_idx != -1, f"{TARGET_FIELDS[0]} block not found"
first_field_start = first_idx + 1  # skip the leading \n

last_field_token = f"{TARGET_FIELDS[-1]}: bool = Field("
last_field_open = src.find(last_field_token, hdr_idx)
assert last_field_open != -1, f"{TARGET_FIELDS[-1]} block not found"
depth = 0
i = last_field_open + len(last_field_token) - 1  # position of '('
started = False
while i < len(src):
    ch = src[i]
    if ch == "(":
        depth += 1
        started = True
    elif ch == ")":
        depth -= 1
        if started and depth == 0:
            break
    i += 1
close_paren_pos = i
eol = src.find("\n", close_paren_pos)
assert eol != -1
last_field_end_excl_nl = eol  # exclusive

extracted_block = src[first_field_start:last_field_end_excl_nl]
print(f"Extracted block: {len(extracted_block)} chars")
print(f"  head: {extracted_block[:60]!r}")
print(f"  tail: {extracted_block[-60:]!r}")
assert extracted_block.startswith(f"    {TARGET_FIELDS[0]}: bool = Field(")
assert extracted_block.rstrip().endswith("    )"), f"unexpected tail: {extracted_block[-40:]!r}"
for f in TARGET_FIELDS:
    assert f"    {f}: bool = Field(" in extracted_block, f"{f} missing"

# 2) sprint19_dx.py already exists from the previous (partial) run — verify & keep
existing_new = NEW.read_text(encoding="utf-8")
expected_field_count = sum(1 for f in TARGET_FIELDS if f"    {f}: bool = Field(" in existing_new)
print(f"Existing {NEW.name}: {expected_field_count}/12 target fields present")
assert expected_field_count == 12, "sprint19_dx.py does not have all 12 fields"

# 3) Patch __init__.py:

# 3a) Remove the 12-field block, replace with comment marker
replacement = (
    "    # Sprint 19 DSL+AI Extensions + DX — first 12 of 23 fields extracted в\n"
    "    # features/sprint19_dx.py::Sprint19DXFlags (S38 T1.3.23). Наследуются\n"
    "    # через multiple inheritance. См. class FeatureFlags(..., Sprint19DXFlags, ...).\n"
    "    # Remaining 11 Sprint 19 fields (K1 Security + K2 Resilience + K4 AI/RAG + K5 Frontend/DX):\n"
    "    # adaptive_timeout_enabled, multi_replica_failover, vault_zero_downtime_rotation,\n"
    "    # manage_py_diagnose, current_frames_fallback, adaptive_rag_strategy_enabled,\n"
    "    # ai_safety_capability_unify, prod_hot_reload_disable, dsl_usage_audit_enabled,\n"
    "    # admin_react_mvp, quick_wins_pack — extracted в features/sprint19_ai.py (T1.3.24)."
)
new_src = src[:first_field_start] + replacement + src[last_field_end_excl_nl:]
removed = len(src) - len(new_src)
print(f"Removed 12-field block: {removed} chars")

# 3b) Add import for Sprint19DXFlags (alphabetical: after Sprint19AIFlags, before Sprints1517Flags)
old_imports = (
    "from src.backend.core.config.features.sprint19_ai import Sprint19AIFlags\n"
    "from src.backend.core.config.features.sprints_15_17 import Sprints1517Flags\n"
)
new_imports = (
    "from src.backend.core.config.features.sprint19_ai import Sprint19AIFlags\n"
    "from src.backend.core.config.features.sprint19_dx import Sprint19DXFlags\n"
    "from src.backend.core.config.features.sprints_15_17 import Sprints1517Flags\n"
)
assert old_imports in new_src, "imports anchor not found"
new_src = new_src.replace(old_imports, new_imports, 1)
print("Added Sprint19DXFlags import (between Sprint19AIFlags and Sprints1517Flags)")

# 3c) Add Sprint19DXFlags to class FeatureFlags(...) MRO
old_mro = (
    "    Sprint19AIFlags,\n"
    "    Sprints1517Flags,\n"
)
new_mro = (
    "    Sprint19AIFlags,\n"
    "    Sprint19DXFlags,\n"
    "    Sprints1517Flags,\n"
)
assert old_mro in new_src, "MRO anchor not found"
new_src = new_src.replace(old_mro, new_mro, 1)
print("Added Sprint19DXFlags to FeatureFlags MRO")

# 3d) Add docstring bullet for Sprint19DXFlags (after Sprint19AIFlags bullet, before Sprints1821Flags)
old_anchor = (
    "    - Sprint19AIFlags (Sprint 19 K1 Security + K2 Resilience + K4 AI/RAG + K5 Frontend/DX:\n"
    "      11 fields, T1.3.24 → features/sprint19_ai.py)\n"
    "    - Sprints1821Flags (Sprint 18 Operational+Security GAP + Sprint 21 Resilience & Multi-tenancy:\n"
    "      18 fields, T1.3.20 → features/sprints_18_21.py)\n"
)
new_anchor = (
    "    - Sprint19AIFlags (Sprint 19 K1 Security + K2 Resilience + K4 AI/RAG + K5 Frontend/DX:\n"
    "      11 fields, T1.3.24 → features/sprint19_ai.py)\n"
    "    - Sprint19DXFlags (Sprint 19 DSL+AI Extensions + DX first 12 of 23 fields:\n"
    "      12 fields, T1.3.23 → features/sprint19_dx.py)\n"
    "    - Sprints1821Flags (Sprint 18 Operational+Security GAP + Sprint 21 Resilience & Multi-tenancy:\n"
    "      18 fields, T1.3.20 → features/sprints_18_21.py)\n"
)
assert old_anchor in new_src, "docstring anchor not found"
new_src = new_src.replace(old_anchor, new_anchor, 1)
print("Added Sprint19DXFlags docstring bullet")

# 4) Write back
INIT.write_text(new_src, encoding="utf-8")
print(f"Wrote {INIT} ({len(new_src)} chars)")

# 5) Sanity
import re
inline_count = len(re.findall(r"^\s+(\w+):\s+bool", new_src, re.MULTILINE))
print(f"Inline bool fields AFTER fix: {inline_count}")
print(f"  (expected: 16 = 28 original - 12 mine; sprint19_ai already removed their 11)")
assert inline_count == 16, f"expected 16 inline bool fields, got {inline_count}"
print("Surgery OK")
