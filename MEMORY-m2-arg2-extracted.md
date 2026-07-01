# Memory spillover — M2 Argon2id narrow facts (cycle 38 S172)
_Extracted from MEMORY.md "Discovered durable knowledge" to bring main file under token budget. Historical / completed-step M2 narrow crypto + API-contract + review-fix facts. Reference via index line in MEMORY.md._

## D308 Edit-tool partial-match leaves duplicate defs (cycle 38 S172 M1.1, BINDING)

When the `edit` tool's `old_string` does NOT span the full extent of a function/block, the original code BELOW the matched region remains untouched. Symptom: file now has 2 copies of `^(async )?def <func_name>` (verified: `grep -c` returns 2+). Python silently shadows, and depending on import order the wrong def wins. **Rule (binding for future edits)**: when replacing >20 LOC or a complete function, prefer `Write` the whole file over `Edit`. Verification per edit: `grep -c "^def <name>\|^async def <name>" <file>` MUST return 1. Recorded after M1.1 partial-edit produced 390-line `ws_handler.py` with two `ws_router` defs.

## D320 Argon2 family prefix is permissive (cycle 38 S172 M2.1, FACT)

`is_argon2_hash()` accepts both `$argon2id$` and `$argon2i$` family prefixes (PHC standard). For strict argon2id-only, would need regex `^\$argon2id\$`. Current implementation is permissive — fine for verification but strict version may be needed if compliance requires explicit argon2id attestation.

## D321 Dual-verify transition state pattern (cycle 38 S172 M2.1, BINDING, reusable)

When migrating from one-way hash to stronger one-way hash, legacy hash MUST be accepted until all clients have rotated. Pattern: new writes go through new hash, legacy reads still match via old-hash path, migration script audits coverage. Kill-switch `allow_legacy_sha256=False` for "all clients rotated" state. Reusable for future hash upgrades (Argon2id → Argon2id-tuned, SHA-256 → SHA-512, etc.).

## D322 Per-key random salt is critical (cycle 38 S172 M2.1, FACT)

`PasswordHasher.hash(raw)` generates fresh 16-byte salt per call. Two calls with same `raw` produce DIFFERENT hashes. SHA-256 without salt (pre-M2) was vulnerable to rainbow-table attacks for common keys; Argon2 with random salt is not. OWASP core recommendation.

## D324 Migration script re-hashes when raw_key supplied externally (cycle 38 S172 M2.2, REFINEMENT of D319)

D319 originally said rotation-coordinator only. Refinement: if operator supplies raw keys via `--keys-file`, the script DOES verify-against-legacy-hash + rehash + write-back. Workflow: gather raw keys from secure secret store → enumerate stored keys → verify + rehash + write → emit audit-event. Reduces operator distribution burden vs full rotation.

## D325 `APIKeyAuth.verify()` API contract change (cycle 38 S172 M2.3, FACT)

Pre-M2.3, `APIKeyManager.validate_key` pre-computed `key_hash = self._hash_key(raw_key)` and compared with stored. Post-M2.3, verification delegates to `APIKeyAuth.verify(raw, stored_hash)` which auto-detects hash format. The `key_hash` field on returned `APIKeyInfo` is the **stored** hash (not computed from raw). Downstream consumers checking `key_hash` for re-verification would need to call `APIKeyAuth.verify` again, not compare directly. None found so far.

## D326 `APIKeyManager.upgrade_to_argon2()` distinct from `rotate_client_key()` (cycle 38 S172 M2.3, BINDING)

`upgrade_to_argon2(client_id, current_raw_key)` — verifies ownership via current stored hash, rehashes to Argon2 (no version increment, no grace period; pure hash migration). `rotate_client_key(client_id)` — generates new raw key, increments version + grace period. Two distinct admin ops: algorithm upgrade vs key rotation. Reusable for future hash transitions.

## D327 `hash_algo` field on Redis records (cycle 38 S172 M2.3, BINDING)

All `apikey:{client_id}` Redis records now carry `hash_algo` field (`"argon2id"` or `"sha256"`). Stamped on `create_client_key`, `rotate_client_key`, `upgrade_to_argon2`. `list_clients()` exposes it for migration dashboards. Read path (`validate_key`) doesn't depend on `hash_algo` — `APIKeyAuth.verify` auto-detects. Observability-only field, but critical for migration coverage stats.

## D328 Read-then-edit locally, never Write mid-edit (cycle 38 S172 M2.2, SESSION-LOCAL — promotable to project if pattern repeats)

When mid-edit interrupted (Read issued, Edit not yet applied), DO NOT call `Write` to re-create file from memory. Read again, issue narrow `Edit`. Reason: in-memory file state may already differ from live state from intervening partial edits in same session; Write produces divergent variants. Triggered 2026-06-30 in M2.2 argparse-rework fix sequence.
