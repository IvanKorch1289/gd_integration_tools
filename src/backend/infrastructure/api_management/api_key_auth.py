"""API key auth с хешированием (OWASP: никогда не храните keys в plain-text)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

__all__ = ("APIKeyAuth",)


@dataclass(slots=True)
class APIKeyAuth:
    """Validates hashed API keys. Плоские keys в БД НЕ хранятся."""

    prefix: str = "apikey:"

    @staticmethod
    def hash_key(raw: str) -> str:
        """SHA-256 hash — применяется при регистрации ключа."""
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def verify(self, raw: str, expected_hash: str) -> bool:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest() == expected_hash
