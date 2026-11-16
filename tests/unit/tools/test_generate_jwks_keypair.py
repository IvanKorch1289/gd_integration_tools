"""ADR-0455 — генератор keypair для JWKS (RS256)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.generate_jwks_keypair import generate, main

pytestmark = pytest.mark.unit


def test_generates_rsa_jwks_document(tmp_path: Path) -> None:
    """Генерируется приватный ключ (0600) и JWKS-документ с RS256."""
    private_pem, jwks_json, fingerprint = generate(tmp_path, kid="k1")

    assert private_pem.exists()
    assert private_pem.stat().st_mode & 0o777 == 0o600
    assert fingerprint

    data = json.loads(jwks_json.read_text(encoding="utf-8"))
    key = data["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["kid"] == "k1"
    assert key["n"] and key["e"]


def test_refuses_output_inside_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Каталог ключей внутри репозитория → отказ (приватный ключ не в git)."""
    repo_root = Path(__file__).resolve().parents[3]
    inside = repo_root / ".tmp-jwt-test"
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    try:
        code = main(["--out-dir", str(inside)])
    finally:
        if inside.exists():  # pragma: no cover — защитный сценарий
            for item in inside.iterdir():
                item.unlink()
            inside.rmdir()
    assert code == 2
