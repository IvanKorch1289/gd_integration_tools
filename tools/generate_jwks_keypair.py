#!/usr/bin/env python3
"""Генерация keypair для JWKS (RS256) — инфраструктурное действие (ADR-0455).

Зачем
-----
Прод-JWT переводится на асимметричную подпись (RS256): приватный ключ живёт
в secret-менеджере, публичный отдаётся JWKS-эндпоинтом. Код уже поддерживает
алгоритм (``core/auth/jwt_backend_helpers.py::_ASYMMETRIC_ALGS``), JWKS-бэкенд
есть (``core/auth/auth_selector.py``) — не хватает только keypair.

Безопасность
-------------
* ключи **никогда** не пишутся в репозиторий: каталог вывода задаётся явно и
  по умолчанию — временный (``--out-dir``), каталог внутри репозитория
  (включая его корень) отклоняется;
* приватный ключ — PKCS#8 PEM (шифрование закрывает KMS/secret-менеджер),
  публичный — JWK (base64url ``n``/``e``) для JWKS-документа;
* в stdout выводятся только **пути** и отпечатки (SHA-256 публичного ключа),
  не сами ключи.

Использование
--------------
::

    python tools/generate_jwks_keypair.py --out-dir /run/secrets/jwt
    # → /run/secrets/jwt/jwt-private.pem (0600)
    # → /run/secrets/jwt/jwks.json

JWKS-документ (публичный) кладётся в ConfigMap/Secret и отдаётся JWKS-эндпоинтом;
приватный — только в secret-менеджер (ADR-0364).

JWKS-endpoint в приложении читает ``security.jwks_url`` (env-префикс
``SEC_``) и требует **https** (SSRF-guard, ``core/auth/jwks_cache.py``);
сборка бэкенда — ``core/di/providers/auth.py::_build_jwks_cache_or_none``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

#: Размер RSA-ключа (bits) — под RS256 (ADR-0455).
_RSA_BITS = 2048


def _b64url(data: bytes) -> str:
    """base64url без паддинга (JWK, RFC 7517).

    Args:
        data: Сырые байты.

    Returns:
        base64url-строка без ``=``.

    """
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _run_openssl(*args: str) -> None:
    """Выполнить openssl с явными аргументами (без shell).

    Args:
        args: Аргументы openssl.

    Raises:
        RuntimeError: openssl завершился с ошибкой.

    """
    import subprocess

    proc = subprocess.run(  # noqa: S603  # dev-tool: openssl, фиксированные аргументы
        [shutil.which("openssl") or "/usr/bin/openssl", *args],  # noqa: S607  # dev-tool: openssl
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"openssl {' '.join(args)} failed: {proc.stderr.strip()}")


def generate(out_dir: Path, kid: str) -> tuple[Path, Path, str]:
    """Сгенерировать keypair и JWKS-документ.

    Args:
        out_dir: Каталог для записи (создаётся при необходимости).
        kid: Идентификатор ключа (JWK ``kid``).

    Returns:
        Кортеж ``(private_pem, jwks_json, fingerprint)``.

    """
    out_dir.mkdir(parents=True, exist_ok=True)
    private_pem = out_dir / "jwt-private.pem"
    public_pem = out_dir / "jwt-public.pem"
    jwks_json = out_dir / "jwks.json"

    # Повторный прогон (ротация ключа) не должен падать на read-only-файле
    # прошлого запуска: jwks.json закрывается 0444, поэтому перезапись
    # запрещена — старые файлы удаляем явно.
    for stale in (private_pem, public_pem, jwks_json):
        stale.unlink(missing_ok=True)

    # RSA-2048 → RS256 (алгоритм, который требует прод-JWT, ADR-0455).
    _run_openssl(
        "genpkey",
        "-algorithm",
        "RSA",
        "-pkeyopt",
        f"rsa_keygen_bits:{_RSA_BITS}",
        "-out",
        str(private_pem),
    )
    _run_openssl("pkey", "-in", str(private_pem), "-pubout", "-out", str(public_pem))

    jwk: dict[str, Any] = _public_jwk(public_pem, kid=kid)
    jwks_json.write_text(
        json.dumps({"keys": [jwk]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    private_pem.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.chmod(jwks_json, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    fingerprint = hashlib.sha256(jwks_json.read_bytes()).hexdigest()[:16]
    return private_pem, jwks_json, fingerprint


def _public_jwk(public_pem: Path, *, kid: str) -> dict[str, Any]:
    """Собрать JWK из публичного PEM (EC P-256).

    Args:
        public_pem: Публичный ключ (PEM).
        kid: Идентификатор ключа.

    Returns:
        JWK (dict) с ``kty``/``crv``/``x``/``y``/``kid``.

    Raises:
        RuntimeError: Ключ не удалось разобрать.

    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError as exc:  # pragma: no cover — зависимость обязательна
        raise RuntimeError("cryptography не установлена") from exc

    key = serialization.load_pem_public_key(public_pem.read_bytes())
    if not isinstance(key, rsa.RSAPublicKey):
        raise RuntimeError("ожидался RSA-ключ")
    numbers = key.public_numbers()
    size = (key.key_size + 7) // 8
    return {
        "kty": "RSA",
        "n": _b64url(numbers.n.to_bytes(size, "big")),
        "e": _b64url(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
    }


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы (для тестов).

    Returns:
        Код возврата.

    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/run/secrets/jwt"),
        help="Каталог для ключей (НЕ внутри репозитория!)",
    )
    parser.add_argument("--kid", default="jwt-1", help="Идентификатор ключа (JWK kid)")
    args = parser.parse_args(argv)

    out_dir = args.out_dir.resolve()
    repo_root = Path(__file__).resolve().parents[1]
    # Корень репозитория — тоже «внутри репозитория»: он не является
    # собственным parent'ом, поэтому проверка только по parents пропускала
    # --out-dir <корень> и приватный ключ писался в рабочее дерево.
    if out_dir == repo_root or repo_root in out_dir.parents:
        print(
            "REFUSED: каталог ключей находится внутри репозитория — "
            "приватный ключ не должен попадать в git",
            file=sys.stderr,
        )
        return 2

    private_pem, jwks_json, fingerprint = generate(out_dir, kid=args.kid)
    print(f"private key: {private_pem} (0600)")
    print(f"jwks document: {jwks_json}")
    print(f"public key fingerprint (sha256/16): {fingerprint}")
    print("Приватный ключ → secret-менеджер (ADR-0364); JWKS → ConfigMap/Secret.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
