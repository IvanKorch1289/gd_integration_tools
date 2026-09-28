# Pre-fix snapshot — read as BEFORE evidence, not as current status

This directory holds runtime evidence captured at SHA `32ef4f246` — the
**state before** commits `f013e7317` and the `data_masking` canonical-pattern
change. It is kept deliberately as the counterfactual for those fixes, and it
is **not** the canonical per-SHA evidence.

Canonical evidence for the current SHA: see
`artifacts/release/f013e73173154a979fbf8d900c97e65e8dbc5da2/EVIDENCE.md`.

## What this directory proves

`curl_matrix.txt` was captured while the defects were still present:

- `/ready` answered `"timestamp":"+***0928T15:12:46.355395+00:00"` — the
  PII phone pattern had eaten the ISO-8601 date. Fixed in `32ef4f246`
  (duplicate patterns removed in favour of `core.security.pii_patterns`).
- `auth_matrix.txt` records a step-up token being **rejected** immediately
  after being issued, which is the symptom behind `f013e7317`. The measured
  corruption rate on the live service was 8 of 40; the same measurement after
  the fix gave 0 of 40.

`openapi.json` is the specification served by that process. It has an empty
`components.securitySchemes` and no `security` field on any operation — the
defect is still open and is listed as a blocker in the canonical document.
