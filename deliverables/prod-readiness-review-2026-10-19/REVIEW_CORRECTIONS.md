# Review corrections (fact-check after writing the review)

## Why this file exists

Within minutes of writing `REVIEW.md`, fact-gathering surfaced **a major drift** that changed the verdict:

**G-12 (pymdown-extensions CVE cap) was already CLOSED** by commit `56ecf3c3a` (2026-10-15) — a Dependabot wave that fixed 31 of 38 CVEs. The CURRENT report (Sep 28) saw the cap; HEAD `127d4d011` (Oct 19) does not. 19 days of evidence drift.

## What changed in the review

1. **Verdict drift line** — net drift changed from -0.3 to -0.05 (Dependabot is a major positive).
2. **G-12 row** — status from ❌ OPEN to ✅ CLOSED, owner/recommendation columns cleared.
3. **Top-5 list** — entry #2 (pymdown fix) removed; entry #5 (Sprint 171+ addendum) extended to also cover Dependabot wave.
4. **Trend table** — pymdown row from `NEW ❌` to `⬆⬆ ✅`.
5. **Executive verdict** — added bullet about Dependabot wave between CURRENT and TODAY.

## Implication for the meta-review methodology

The pymdown drift demonstrates exactly the value of cross-checking reports against current HEAD. Without the grep, I would have shipped a review that:
- Listed G-12 as a top-5 immediate action (wrong)
- Created an `apply_pymdown_fix.py` that exits with error (drift-detected, no fix needed)
- Misled the reader about current state

**Rule for future reviews:** every "new finding" or "open blocker" must be grep-checked against `git log` of the relevant file, not just trusted from the report.

## What to do with `apply_pymdown_fix.py`

Since the cap was already fixed in commit `56ecf3c3a`, the apply script is now **historical** (would correctly refuse to apply because OLD is no longer in the file). Kept in the deliverables dir as evidence of the drift-detection process.
