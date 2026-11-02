"""Unit-тесты утилиты генерации RSA-ключевой пары (ADR-0411).

Покрытие:
* формат PEM (PKCS#8 private / SPKI public) и детерминированный ``kid``;
* round-trip: подпись RS256 приватным ключом → проверка публичным;
* ``write_keypair`` идемпотентен по пути (существующий ключ не перетирается);
* права на файл приватного ключа (0600);
* JWKS-документ (``kid``/``kty``/``use``/``alg``);
* CLI ``generate --out <dir>`` — exit code, файлы, повторный вызов.

Зависимостей не добавлялось: генерация — на ``cryptography`` (уже в
pyproject), проверка подписи — на ``joserfc`` (канонический JWT-бэкенд).
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from joserfc import jwt as joserfc_jwt

from src.backend.core.security.jwt_keys import (
    JWKS_FILENAME,
    PRIVATE_KEY_FILENAME,
    PUBLIC_KEY_FILENAME,
    derive_kid,
    generate_rsa_keypair,
    load_private_key_pem,
    load_public_key_pem,
    main,
    public_jwks,
    write_keypair,
)


def test_generate_rsa_keypair_emits_pkcs8_and_spki_pem() -> None:
    pair = generate_rsa_keypair()
    assert pair.private_pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert pair.public_pem.startswith("-----BEGIN PUBLIC KEY-----")
    assert "BEGIN RSA PRIVATE KEY" not in pair.private_pem
    assert pair.kid


def test_kid_is_deterministic_for_the_same_public_key() -> None:
    pair = generate_rsa_keypair()
    assert derive_kid(pair.public_pem) == pair.kid
    other = generate_rsa_keypair()
    assert other.kid != pair.kid


def test_round_trip_sign_with_private_verify_with_public() -> None:
    pair = generate_rsa_keypair()
    private_key = load_private_key_pem_text(pair.private_pem)
    public_key = load_public_key_pem_text(pair.public_pem)
    token = joserfc_jwt.encode(
        {"alg": "RS256", "kid": pair.kid}, {"sub": "user-1"}, private_key
    )
    decoded = joserfc_jwt.decode(token, key=public_key, algorithms=["RS256"])
    assert decoded.claims["sub"] == "user-1"


def test_write_keypair_creates_files_and_is_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "keys"
    first = write_keypair(out)
    assert first.created is True
    private_path = out / PRIVATE_KEY_FILENAME
    public_path = out / PUBLIC_KEY_FILENAME
    jwks_path = out / JWKS_FILENAME
    assert private_path.is_file()
    assert public_path.is_file()
    assert jwks_path.is_file()

    original = private_path.read_text(encoding="utf-8")

    second = write_keypair(out)
    assert second.created is False
    assert private_path.read_text(encoding="utf-8") == original
    assert second.kid == first.kid


def test_write_keypair_sets_private_key_permissions(tmp_path: Path) -> None:
    out = tmp_path / "keys"
    write_keypair(out)
    mode = stat.S_IMODE(os.stat(out / PRIVATE_KEY_FILENAME).st_mode)
    assert mode == 0o600


def test_public_jwks_contains_kid_and_rsa_parameters() -> None:
    pair = generate_rsa_keypair()
    jwks = public_jwks(pair.public_pem, pair.kid)
    keys = jwks["keys"]
    assert len(keys) == 1
    assert keys[0]["kid"] == pair.kid
    assert keys[0]["kty"] == "RSA"
    assert keys[0]["use"] == "sig"
    assert keys[0]["alg"] == "RS256"
    assert keys[0]["n"] and keys[0]["e"] == "AQAB"


def test_load_public_key_pem_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "keys"
    files = write_keypair(out)
    public_key = load_public_key_pem(files.public_path)
    assert public_key.as_dict()["kty"] == "RSA"


def test_load_private_key_pem_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "keys"
    files = write_keypair(out)
    private_key = load_private_key_pem(files.private_path)
    assert private_key.as_dict()["kty"] == "RSA"


def test_load_public_key_pem_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_public_key_pem(tmp_path / "nope.pem")


def test_cli_generate_writes_keys_and_is_idempotent(tmp_path: Path) -> None:
    out = tmp_path / "cli-keys"
    exit_code = main(["generate", "--out", str(out)])
    assert exit_code == 0
    assert (out / PRIVATE_KEY_FILENAME).is_file()
    payload = json.loads((out / JWKS_FILENAME).read_text(encoding="utf-8"))
    assert payload["keys"]

    before = (out / PRIVATE_KEY_FILENAME).read_text(encoding="utf-8")
    exit_code = main(["generate", "--out", str(out)])
    assert exit_code == 0
    assert (out / PRIVATE_KEY_FILENAME).read_text(encoding="utf-8") == before


def test_cli_without_arguments_returns_error_code() -> None:
    assert main([]) == 2


# ── local helpers (text-based loaders are exercised through files) ─────────


def load_private_key_pem_text(pem: str) -> object:
    """Импортирует приватный ключ из PEM-строки (test-helper)."""
    from joserfc.jwk import RSAKey

    return RSAKey.import_key(pem)


def load_public_key_pem_text(pem: str) -> object:
    """Импортирует публичный ключ из PEM-строки (test-helper)."""
    from joserfc.jwk import RSAKey

    return RSAKey.import_key(pem)
