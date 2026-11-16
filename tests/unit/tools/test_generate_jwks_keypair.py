"""ADR-0455 — генератор keypair для JWKS (RS256)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.generate_jwks_keypair import generate, main

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _cleanup_keys(directory: Path) -> None:
    """Удалить артефакты генератора из каталога (защита от утечки в тест)."""
    if not directory.exists():
        return
    for item in directory.iterdir():
        if item.name in {"jwt-private.pem", "jwt-public.pem", "jwks.json"}:
            item.unlink()


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


def test_refuses_output_inside_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Каталог ключей внутри репозитория → отказ (приватный ключ не в git)."""
    inside = _REPO_ROOT / ".tmp-jwt-test"
    monkeypatch.setattr(Path, "resolve", lambda self: self)
    try:
        code = main(["--out-dir", str(inside)])
    finally:
        _cleanup_keys(inside)
        if inside.exists():  # pragma: no cover — защитный сценарий
            inside.rmdir()
    assert code == 2


def test_refuses_repository_root(tmp_path: Path) -> None:
    """Корень репозитория — тоже «внутри репозитория» → отказ.

    Корень не является собственным parent'ом, поэтому проверка «repo_root in
    out_dir.parents» его пропускала: приватный ключ писался в рабочее дерево.
    """
    try:
        code = main(["--out-dir", str(_REPO_ROOT)])
    finally:
        _cleanup_keys(_REPO_ROOT)
    assert code == 2


def test_regeneration_in_same_dir_succeeds(tmp_path: Path) -> None:
    """Повторный прогон (ротация ключа) не падает на read-only jwks.json."""
    first_private, first_jwks, _ = generate(tmp_path, kid="k1")
    second_private, second_jwks, _ = generate(tmp_path, kid="k2")

    assert first_private.exists() and second_private.exists()
    assert first_jwks.exists() and second_jwks.exists()
    data = json.loads(second_jwks.read_text(encoding="utf-8"))
    assert data["keys"][0]["kid"] == "k2"
