"""Unit tests for Argon2id migration (S172 M2 — ARC-004).

Tests:
- Argon2id path: hash_key → PHC string, verify happy path.
- Argon2id parameters: time_cost / memory_cost / parallelism honored.
- Legacy SHA-256 path: backward-compat verify.
- Dual-verify (Argon2 primary + SHA-256 fallback): legacy hash upgrades gracefully.
- Rehash-pending hint: existing Argon2 hash with weak params flagged.
- Malformed stored hash → safe False (no exception).
- allow_legacy_sha256=False disables legacy path.
"""

from __future__ import annotations

import pytest
from argon2 import PasswordHasher

from src.backend.core.auth.api_key_backend import (
    APIKeyAuth,
    is_argon2_hash,
    needs_argon2_upgrade,
)


class TestIsArgon2Hash:
    """Tests for :func:`is_argon2_hash` static helper."""

    def test_argon2_phc_prefix_detected(self) -> None:
        h = "$argon2id$v=19$m=65536,t=2,p=2$abc$xyz"
        assert is_argon2_hash(h) is True

    def test_argon2i_prefix_rejected(self) -> None:
        """argon2i (без "id") не принимается — мы строго argon2id-only."""
        h = "$argon2i$v=19$m=65536,t=2,p=2$abc$xyz"
        assert is_argon2_hash(h) is False

    def test_sha256_hex_not_detected(self) -> None:
        h = "a" * 64  # SHA-256 hex length
        assert is_argon2_hash(h) is False

    def test_plain_string_not_detected(self) -> None:
        assert is_argon2_hash("plain-password") is False


class TestAPIKeyAuthArgon2:
    """Tests for Argon2id primary path."""

    @pytest.fixture
    def auth(self) -> APIKeyAuth:
        # OWASP 2026 lower-bound (faster test): 32MB, time_cost=1.
        # Production default — 64MB, time_cost=2 (см. docstring).
        return APIKeyAuth(
            time_cost=1,
            memory_cost=32768,
            parallelism=1,
        )

    def test_hash_key_returns_argon2_phc(self, auth: APIKeyAuth) -> None:
        h = auth.hash_key("my-secret-key-12345")
        assert is_argon2_hash(h)
        # PHC: ``$argon2id$v=19$m=...,t=...,p=...$salt$hash`` segments.
        parts = h.split("$")
        assert len(parts) == 6  # empty + argon2id + v=19 + params + salt + hash
        assert parts[1] == "argon2id"

    def test_hash_key_unique_per_call(self, auth: APIKeyAuth) -> None:
        """Per-key random salt — одинаковый raw даёт разный hash."""
        h1 = auth.hash_key("same-key")
        h2 = auth.hash_key("same-key")
        assert h1 != h2  # different salt → different hash

    def test_verify_argon2_success(self, auth: APIKeyAuth) -> None:
        h = auth.hash_key("secret-A")
        assert auth.verify("secret-A", h) is True

    def test_verify_argon2_wrong_key_fails(self, auth: APIKeyAuth) -> None:
        h = auth.hash_key("secret-A")
        assert auth.verify("secret-B", h) is False

    @pytest.mark.parametrize(
        "bad_hash",
        [
            "$argon2id$corrupt$params",
            "garbage",
            "",
        ],
    )
    def test_verify_corrupt_hash_returns_false(
        self, auth: APIKeyAuth, bad_hash: str
    ) -> None:
        """Malformed stored hash → False (no exception propagates)."""
        assert auth.verify("any-key", bad_hash) is False


class TestAPIKeyAuthLegacySHA:
    """Tests for legacy SHA-256 backward-compat path."""

    @pytest.fixture
    def auth(self) -> APIKeyAuth:
        return APIKeyAuth(enable_argon2=False)

    def test_legacy_hash_uses_sha256(self, auth: APIKeyAuth) -> None:
        h = auth.hash_key("my-secret")
        assert not is_argon2_hash(h)
        # SHA-256 hex = 64 chars.
        assert len(h) == 64

    def test_legacy_verify_constant_time(self, auth: APIKeyAuth) -> None:
        h = auth.hash_key("secret-X")
        assert auth.verify("secret-X", h) is True
        assert auth.verify("secret-Y", h) is False

    def test_legacy_disabled_returns_false(self) -> None:
        auth = APIKeyAuth(enable_argon2=False, allow_legacy_sha256=False)
        # Создаём SHA-хеш через прямой вызов bypass'а
        sha_hash = APIKeyAuth(enable_argon2=False).hash_key("key")
        assert auth.verify("key", sha_hash) is False


class TestAPIKeyAuthDualVerify:
    """Mixed: stored hash может быть SHA (legacy) или Argon2 (new)."""

    def test_argon2_path_used_for_argon2_hash(self) -> None:
        auth = APIKeyAuth(time_cost=1, memory_cost=8192, parallelism=1)
        argon_hash = auth.hash_key("test-key")
        assert is_argon2_hash(argon_hash)

        # Same auth instance, dual-verify mode (default):
        assert auth.verify("test-key", argon_hash) is True
        assert auth.verify("wrong", argon_hash) is False

    def test_legacy_sha_hash_accepted_with_flag(self) -> None:
        """Legacy SHA-хеш принимается пока allow_legacy_sha256=True."""
        legacy_auth = APIKeyAuth(enable_argon2=False)
        legacy_hash = legacy_auth.hash_key("legacy-key")

        # Switch to Argon2 mode для нового auth instance:
        new_auth = APIKeyAuth(time_cost=1, memory_cost=8192, parallelism=1)
        # Новый ключ верифицируется через legacy SHA path (backward-compat).
        assert new_auth.verify("legacy-key", legacy_hash) is True
        # Неверный ключ — false.
        assert new_auth.verify("wrong-key", legacy_hash) is False


class TestNeedsArgon2Upgrade:
    """Tests for :func:`needs_argon2_upgrade`.

    Baseline: ``PasswordHasher()`` defaults (argon2-cffi 23.x):
    ``time_cost=3, memory_cost=65536, parallelism=4``. Hash, созданный с
    этими параметрами, не нуждается в upgrade (baseline >= target).
    """

    def test_legacy_hash_needs_upgrade(self) -> None:
        assert needs_argon2_upgrade("a" * 64) is True

    def test_weak_argon2_needs_upgrade(self) -> None:
        # Слабее baseline (time_cost=1, parallelism=1, memory=64MB OK).
        weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(
            "x"
        )
        assert needs_argon2_upgrade(weak) is True

    def test_argon2id_default_does_not_need_upgrade(self) -> None:
        """Default ``PasswordHasher()`` = baseline → no rehash needed."""
        baseline = PasswordHasher()  # baseline 3, 65536, 4
        strong = baseline.hash("x")
        assert needs_argon2_upgrade(strong) is False

    def test_corrupt_hash_needs_upgrade(self) -> None:
        assert needs_argon2_upgrade("garbage") is True
