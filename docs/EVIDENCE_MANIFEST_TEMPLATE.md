# EVIDENCE_MANIFEST — Release evidence (template + filled example)

> **Цель (аудит 2026-09-21)**: один документ с SHA, lockfile, image digest,
> SBOM digest, migration head, тестами, coverage, SLO и contract diff.
> Генерируется автоматически при release cut.

---

## Template

```yaml
# evidence-manifest.yaml — заполняется tools/checks/generate_evidence_manifest.py
release:
  version: <semver>           # 0.21.0
  candidate_sha: <40-char>    # git rev-parse HEAD
  short_sha: <7-char>         # git rev-parse --short HEAD
  branch: master
  generated_at: <iso8601>     # date -u +%Y-%m-%dT%H:%M:%SZ
  generated_by: <ci-job>      # release-gate / manual

identity:
  python_version: 3.14.0      # python --version
  uv_lock_sha256: <digest>    # sha256sum uv.lock
  pyproject_sha256: <digest>  # sha256sum pyproject.toml
  lockfile_changed_since_last_release: <bool>

artifacts:
  container_image: <registry/image:tag>
  image_digest_sha256: <digest>   # sha256:abc...
  cosign_signature: <signature>   # cosign verify output
  sbom_path: dist/sbom.cdx.json
  sbom_sha256: <digest>
  sbom_component_count: <int>
  sbom_vulnerabilities: 0          # MUST be 0 for release

database:
  alembic_head: <revision-id>      # alembic current
  migration_count: <int>           # count of migrations since last release
  migration_dry_run_passed: <bool>

tests:
  unit_passed: <int>
  unit_failed: <int>               # MUST be 0
  unit_skipped: <int>              # documented exceptions only
  integration_passed: <int>
  integration_failed: <int>        # MUST be 0
  coverage_overall_pct: <float>    # MUST be ≥70
  coverage_per_domain:
    core: <float>
    dsl: <float>
    services: <float>
    infrastructure: <float>

static_analysis:
  ruff_errors: 0                   # MUST be 0
  ruff_f821_errors: 0              # MUST be 0
  mypy_strict_errors: 0            # MUST be 0
  bandit_high: 0                   # MUST be 0
  bandit_medium: <int>             # documented
  bandit_low: <int>                # informational
  vulture_dead_code: 0             # MUST be 0
  layer_violations_new: 0          # MUST be 0
  layer_violations_baseline: <int> # allowlist size
  ast_parse_errors: 0              # MUST be 0
  python2_except_clauses: 0        # MUST be 0

security:
  cve_high_unhandled: 0            # MUST be 0
  cve_medium_unhandled: 0          # MUST be 0 (or waiver)
  bandit_security_issues: 0        # MUST be 0
  cosign_verified: <bool>          # MUST be true

performance:
  p50_ms: <float>
  p95_ms: <float>
  p99_ms: <float>                  # MUST be ≤300 ms at 300 VU
  throughput_rps: <float>
  error_rate_pct: <float>          # MUST be ≤ agreed SLO
  load_test_report_path: <artifact-path>

contract:
  breaking_changes: 0              # MUST be 0 without version bump + waiver
  api_schema_diff: <path>          # openapi/openapi.json diff
  asyncapi_diff: <path>
  protobuf_diff: <path>
  contract_test_passed: <bool>

release_signoff:
  tech_lead_approved: <bool>
  security_approved: <bool>
  sre_approved: <bool>
  product_approved: <bool>
  waivers:
    - id: <waiver-id>
      reason: <text>
      expires_at: <iso8601>
      approver: <name>
```

---

## Filled example (2026-09-21 audit reference)

```yaml
release:
  version: 0.21.0-rc1
  candidate_sha: b5a641152482cd5614cbf009a51cb7f4322b85a0
  short_sha: b5a641152
  branch: master
  generated_at: 2026-09-21T12:23:23Z
  generated_by: manual (audit follow-up)

identity:
  python_version: 3.14.0
  uv_lock_sha256: <not verified in local env>
  pyproject_sha256: <not verified in local env>
  lockfile_changed_since_last_release: true

artifacts:
  container_image: not built
  image_digest_sha256: not built
  cosign_signature: not signed
  sbom_path: dist/sbom.cdx.json
  sbom_sha256: <not verified locally>
  sbom_component_count: 357
  sbom_vulnerabilities: 0

database:
  alembic_head: <not verified locally>
  migration_count: <not verified locally>
  migration_dry_run_passed: <not verified locally>

tests:
  unit_passed: 12835
  unit_failed: 2              # ⚠️ pre-existing, see CURRENT_STATUS.md
  unit_skipped: 129           # env-specific
  integration_passed: <not run in local env>
  integration_failed: <not run in local env>
  coverage_overall_pct: <not measured in this audit>

static_analysis:
  ruff_errors: 0              # ✅
  ruff_f821_errors: 0         # ✅ (CI gate)
  mypy_strict_errors: 0       # ✅ (per prior STATUS.md)
  bandit_high: 0              # ✅ verified locally
  bandit_medium: 47
  bandit_low: 35
  vulture_dead_code: 0        # ✅ (per prior STATUS.md)
  layer_violations_new: 0     # ✅
  layer_violations_baseline: 22
  ast_parse_errors: 0         # ✅ verified locally
  python2_except_clauses: 0   # ✅ verified locally

security:
  cve_high_unhandled: 0       # ✅ per SBOM scan
  cve_medium_unhandled: 0     # ✅ per SBOM scan
  bandit_security_issues: 0
  cosign_verified: false      # not yet signed in this HEAD

performance:
  p50_ms: not measured
  p95_ms: not measured
  p99_ms: not measured
  throughput_rps: not measured
  error_rate_pct: not measured
  load_test_report_path: missing

contract:
  breaking_changes: 0         # ✅ (no public API change in this audit)
  api_schema_diff: not generated
  asyncapi_diff: not generated
  protobuf_diff: not generated
  contract_test_passed: not run

release_signoff:
  tech_lead_approved: false
  security_approved: false
  sre_approved: false
  product_approved: false
  waivers: []
```

---

## Regeneration

```bash
# Manual (TODO: implement):
python tools/checks/generate_evidence_manifest.py > dist/evidence-manifest.yaml

# As part of release cut (TODO: integrate in release.yml):
- name: Generate evidence manifest
  run: python tools/checks/generate_evidence_manifest.py
- name: Upload artifact
  uses: actions/upload-artifact@v7
  with:
    name: evidence-manifest-${{ github.sha }}
    path: dist/evidence-manifest.yaml
```

---

## Что пока не верифицировано локально

- Performance (p99, throughput, error_rate) — требует prod-like stend
- Image digest / cosign signature — не собирали локально
- Alembic migration dry-run — не запускали
- Integration tests — не запускали локально

Эти поля должны быть заполнены **в release pipeline**, не локально.
