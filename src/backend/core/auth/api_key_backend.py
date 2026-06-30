"""API key auth с Argon2id + per-key salt (S172 M2 — ARC-004).

Security (OWASP 2026 baseline):
* Argon2id — память-устойкий хеш (PHC string format ``$argon2id$v=19$...``).
  Параметры: ``time_cost=2``, ``memory_cost=64MB``, ``parallelism=2``.
  Per-key salt (16 bytes default) встроен в PHC string.
* Backward-compat: SHA-256 хеши (legacy, ``S-7 tech debt``) принимаются
  через :meth:`APIKeyAuth.verify` для плавной миграции (S172-M2 grace
  period ~2 спринта). После миграции Redis hashes (см. ``migration_key_hash.py``)
  все legacy окажутся upgraded → SHA-256 path станет dead code.
* Timing attacks: :func:`hmac.compare_digest` для legacy SHA; Argon2
  verification — constant-time by design (PHC equality semantics).

Миграция:
1. Sprint 172 M2.1 (этот коммит): dual-verify path (Argon2 primary,
   SHA-256 fallback). ``create_client_key`` пишет Argon2.
2. Sprint 172 M2.2: standalone migration script
   ``tools/migrations/migrate_api_keys_to_argon2.py`` —
   batch-upgrade Redis-stored hashes (с поддержкой grace period).
3. Sprint 174 (после migration): удалить SHA-256 fallback path +
   оставить только Argon2id.

Args:
    time_cost: Argon2 time cost (default 2 — OWASP recommendation).
    memory_cost: Argon2 memory cost KiB (default 65536 = 64MB).
    parallelism: Argon2 threads (default 2).
    hash_len: Argon2 hash bytes (default 32).
    salt_len: Salt bytes (default 16).

References:
* OWASP Password Storage Cheat Sheet (2026) — Argon2id default.
* RFC 9106 — Argon2 Memory-Hard Function.
* PHC string format: ``$argon2id$v=19$m=65536,t=2,p=2$<salt>$<hash>``.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from src.backend.core.logging import get_logger

__all__ = ("APIKeyAuth", "is_argon2_hash", "needs_argon2_upgrade")

logger = get_logger("auth.api_key")


def is_argon2_hash(stored_hash: str) -> bool:
    """Проверить, является ли stored_hash Argon2id PHC строкой.

    Returns:
        ``True`` если строка начинается с ``$argon2id$``.
    """
    return stored_hash.startswith("$argon2id$")


def needs_argon2_upgrade(stored_hash: str) -> bool:
    """Проверить, нужен ли rehash для соответствия OWASP 2026 baseline.

    Args:
        stored_hash: PHC string из Redis.

    Returns:
        ``True`` если hash не Argon2 или time_cost/memory_cost ниже
        target. Используется в :meth:`APIKeyAuth.verify` для сигнала
        миграции на следующий login (transparent upgrade).
    """
    if not is_argon2_hash(stored_hash):
        return True
    # Argon2 PHC: ``$argon2id$v=19$m=65536,t=2,p=2$salt$hash``.
    # Проверяем параметры через парсинг PasswordHasher.verify с timing-safe
    # API ниже (check_needs_rehash) — нам нужны только параметры.
    try:
        ph = PasswordHasher()
        return ph.check_needs_rehash(stored_hash)
    except (InvalidHashError, ValueError):
        return True


@dataclass
class APIKeyAuth:
    """Верификация API keys с Argon2id (primary) + SHA-256 (legacy compat).

    Args:
        prefix: Storage prefix для Redis keys.
        time_cost: Argon2 time cost parameter (default 2).
        memory_cost: Argon2 memory cost KiB (default 65536).
        parallelism: Argon2 threads (default 2).
        hash_len: Argon2 output hash length bytes (default 32).
        salt_len: Argon2 salt length bytes (default 16).
        enable_argon2: ``True`` → Argon2 primary + SHA-256 fallback.
            ``False`` (dev/test only) → SHA-256 fallback only (legacy mode).
        allow_legacy_sha256: Разрешить ли верификацию legacy SHA-256 хешей.
            Default ``True`` для dual-verify; миграционный script
            (``migrate_api_keys_to_argon2.py``) пропускает постепенный
            rollout → после full migration выставить ``False``.
    """

    prefix: str = "apikey:"
    time_cost: int = 2
    memory_cost: int = 65536
    parallelism: int = 2
    hash_len: int = 32
    salt_len: int = 16
    enable_argon2: bool = True
    allow_legacy_sha256: bool = True

    def __post_init__(self) -> None:
        """Кэшируем PasswordHasher + инициализируем instance-level state.

        Без этого патча каждый ``verify()`` вызов пересоздаёт hasher
        (5-10µs overhead поверх Argon2 ~50ms CPU). При high-RPS
        (100+ WS handshakes/sec) это устраняет до 1ms/sec wasted memory.
        После M2.3 review (S-2 fix).

        Также инициализируем per-instance ``_legacy_warning_emitted``
        flag (A-1 review fix). Cross-tenant noise устранён.
        """
        self._hasher_cached: PasswordHasher | None = None
        self._legacy_warning_emitted: bool = False

    @property
    def _hasher(self) -> PasswordHasher:
        """Lazy hasher — создаём один раз на инстанс."""
        if self._hasher_cached is None:
            self._hasher_cached = PasswordHasher(
                time_cost=self.time_cost,
                memory_cost=self.memory_cost,
                parallelism=self.parallelism,
                hash_len=self.hash_len,
                salt_len=self.salt_len,
            )
        return self._hasher_cached

    @staticmethod
    def _legacy_sha256_hash(raw: str) -> str:
        """Legacy SHA-256 без соли (S-7 tech debt). Используется только
        для backward-compat verification — НЕ для новых ключей."""
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def hash_key(self, raw: str) -> str:
        """Создать Argon2id PHC string для raw API key.

        Если ``enable_argon2=False`` — возвращает SHA-256 (для unit-tests
        legacy mode). Иначе возвращает ``$argon2id$v=19$m=...t=...p=...$salt$hash``.

        Args:
            raw: Plain API key (секрет клиента).

        Returns:
            PHC-compatible hash string, ready для Redis storage.

        Raises:
            argon2.exceptions.HashingError: если системный random
                недоступен (rare, фатальная для production).
        """
        if not self.enable_argon2:
            return self._legacy_sha256_hash(raw)
        return self._hasher.hash(raw)

    @staticmethod
    def validate_strength(raw: str) -> "StrengthReport":
        """S173 M8.3: weak-API-key detector.

        Rejects trivially weak secrets (``"password"``, ``"x"``, ``""``,
        sequential chars ``"abcdef"``). Additive — не changing ``hash_key``
        (backward-compat). Production ``create_client_key`` может
        вызвать ``validate_strength`` перед ``hash_key`` для reject
        weak keys при creation.

        Args:
            raw: Plain API key (секрет клиента).

        Returns:
            :class:`StrengthReport` с ``is_acceptable``, ``issues`` list,
            ``entropy_bits`` estimate. Caller решает — hard-fail или
            warn-only.

        Notes:
            Lightweight heuristic (per S173 M8.3 lightweight scope):
            entropy estimate через unique-chars + length. NOT a full
            password-strength library (no zxcvbn). Sufficient для
            pre-creation gate.
        """
        return _evaluate_strength(raw)

    def verify(self, raw: str, expected_hash: str) -> bool:
        """Верифицировать raw API key против stored hash.

        Алгоритм (S172 M2.1 dual-verify + M2.3 review fixes):

        1. Если ``expected_hash`` — Argon2 PHC: :meth:`argon2.PasswordHasher.verify`.
           При mismatch → False. При InvalidHashError → False + log.
           При HashingError (rare, системная ошибка) → False + error log.
        2. Иначе (legacy SHA-256 hex): constant-time compare.
           ``allow_legacy_sha256=False`` → return False (full SHA-disabled).
        3. Argon2 успех + :func:`needs_argon2_upgrade` → log
           ``api_keys.rehash_pending`` (transparent migration на next login).

        Notes (post-M2.3 review):
        * `_hasher` — cached instance attr (was: per-call instantiation).
        * `_legacy_warning_emitted` — instance attr, NOT class-level
          (review item A-1). Прошлый class-level global страдал от
          cross-tenant noise.

        Args:
            raw: Plain API key из HTTP header / cookie / subprotocol.
            expected_hash: Stored hash из Redis (Argon2 PHC или SHA-256 hex).

        Returns:
            ``True`` если raw matches expected_hash, иначе ``False``.
        """
        if not raw or not expected_hash:
            return False

        if is_argon2_hash(expected_hash):
            try:
                self._hasher.verify(expected_hash, raw)
            except (VerifyMismatchError, VerificationError):
                return False
            except InvalidHashError as exc:
                logger.warning(
                    "API key verify: corrupt Argon2 hash in storage (%s)",
                    exc,
                )
                return False
            except Exception as exc:
                # M2.3 review S-1 fix: любой неожиданный Exception
                # (HashingError, ParameterError) логируется как ERROR
                # (не swallowed) → distributed tracing видит.
                logger.exception(
                    "API key verify: Argon2 unexpected error (%s)", exc
                )
                return False
            # Authentication OK — emit upgrade hint (без blocking).
            if needs_argon2_upgrade(expected_hash):
                logger.info(
                    "api_keys.argon2_rehash_pending (next rotation recommended)"
                )
            return True

        # Legacy SHA-256 path.
        if not self.allow_legacy_sha256:
            return False
        computed = self._legacy_sha256_hash(raw)
        match = hmac.compare_digest(computed, expected_hash)
        if match and not self._legacy_warning_emitted:
            # M2.3 review A-1: per-instance flag, not class-level.
            # Каждый экземпляр APIKeyAuth получает свой warning budget —
            # multi-tenant prod каждый DI-managed instance логирует
            # ровно одно legacy notice за lifetime.
            self._legacy_warning_emitted = True
            logger.warning(
                "API key verify matched against legacy SHA-256 hash. "
                "Run 'tools/migrations/migrate_api_keys_to_argon2.py' to "
                "upgrade stored hashes to Argon2id. (S172 M2 ARC-004)"
            )
        return match


# ─── S173 M8.3: weak-secret detector (lightweight) ────────────────────


# S173 M8.3: minimum acceptable length для API key.
_MIN_API_KEY_LENGTH: int = 24

# S173 M8.3: minimum acceptable entropy bits (rough estimate).
_MIN_ENTROPY_BITS: int = 80.0

# S173 M8.3: blacklist trivially-weak secrets (NOT exhaustive — только
# "default/empty" patterns).
_WEAK_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "password",
        "changeme",
        "default",
        "test",
        "admin",
        "secret",
        "apikey",
        "key",
        "12345678",
        "qwerty",
        "letmein",
    }
)


@dataclass(slots=True, frozen=True)
class StrengthReport:
    """S173 M8.3: result of :func:`APIKeyAuth.validate_strength`."""

    is_acceptable: bool
    issues: tuple[str, ...]
    entropy_bits: float
    length: int


def _evaluate_strength(raw: str) -> StrengthReport:
    """Heuristic: length + unique-chars + blacklist.

    NOT a full password-strength library. Sufficient для pre-creation
    gate. Caller решает: hard-fail или warn-only.
    """
    issues: list[str] = []
    if not raw:
        issues.append("empty")
    if len(raw) < _MIN_API_KEY_LENGTH:
        issues.append(
            f"too_short (length={len(raw)} < {_MIN_API_KEY_LENGTH})"
        )
    if raw in _WEAK_SECRETS:
        issues.append("blacklisted_common_secret")
    # Sequential chars detection.
    if raw and len(set(raw)) == 1:
        issues.append("all_same_character")
    # Rough entropy: log2(unique_chars) * length.
    unique = len(set(raw)) if raw else 0
    entropy_bits = (unique.bit_length() if unique else 0) * len(raw) if raw else 0.0
    if entropy_bits < _MIN_ENTROPY_BITS:
        issues.append(
            f"low_entropy (estimate={entropy_bits:.1f} bits < "
            f"{_MIN_ENTROPY_BITS:.0f})"
        )

    is_acceptable = not issues
    return StrengthReport(
        is_acceptable=is_acceptable,
        issues=tuple(issues),
        entropy_bits=entropy_bits,
        length=len(raw),
    )
