"""Генерация RSA-ключевой пары для JWT (RS256) — ADR-0411.

Утилита эксплуатационная: владелец prod-окружения выпускает ключевую
пару **без обращения к сети** и без внешних зависимостей — только
``cryptography`` (уже в ``pyproject.toml``) и ``joserfc`` (канонический
JWT-бэкенд проекта).

Форматы (RFC 7468 / RFC 5958):

* приватный ключ — PEM ``PKCS#8`` (``BEGIN PRIVATE KEY``);
* публичный ключ — PEM ``SPKI`` (``BEGIN PUBLIC KEY``);
* ``kid`` — детерминированный отпечаток публичного ключа
  (``sha256`` от DER SPKI, первые 16 hex-символов): смена ключа даёт
  новый ``kid`` без ручного согласования.

Идемпотентность по пути: повторный ``generate --out <dir>`` **не**
перетирает уже выпущенный ключ (иначе все ранее выпущенные токены
мгновенно перестают проверяться). Перевыпуск требует явного ``--force``.

CLI::

    python -m src.backend.core.security.jwt_keys generate --out <dir>

Файлы в ``<dir>``:

* ``jwt_private.pem`` — приватный ключ (права ``0600``);
* ``jwt_public.pem`` — публичный ключ (права ``0644``);
* ``jwks.json`` — JWKS-документ для публикации на JWKS-endpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from joserfc.jwk import RSAKey

from src.backend.core.logging import get_logger

__all__ = (
    "DEFAULT_KEY_SIZE",
    "JWKS_FILENAME",
    "PRIVATE_KEY_FILENAME",
    "PUBLIC_KEY_FILENAME",
    "KeyPairFiles",
    "RsaKeyPair",
    "derive_kid",
    "generate_rsa_keypair",
    "load_private_key_pem",
    "load_public_key_pem",
    "main",
    "public_jwks",
    "public_pem_from_private",
    "write_keypair",
)

_logger = get_logger(__name__)

#: Размер RSA-ключа по умолчанию (2048 бит — минимум для RS256 в проде).
DEFAULT_KEY_SIZE: int = 2048

PRIVATE_KEY_FILENAME: str = "jwt_private.pem"
PUBLIC_KEY_FILENAME: str = "jwt_public.pem"
JWKS_FILENAME: str = "jwks.json"

_PRIVATE_MODE: int = 0o600
_PUBLIC_MODE: int = 0o644


@dataclass(frozen=True, slots=True)
class RsaKeyPair:
    """Сгенерированная RSA-ключевая пара в PEM-формате.

    Attrs:
        private_pem: Приватный ключ (PKCS#8 PEM).
        public_pem: Публичный ключ (SPKI PEM).
        kid: Идентификатор ключа (детерминированный отпечаток).

    """

    private_pem: str
    public_pem: str
    kid: str


@dataclass(frozen=True, slots=True)
class KeyPairFiles:
    """Пути записанных файлов ключевой пары.

    Attrs:
        private_path: Путь к приватному ключу (PKCS#8 PEM).
        public_path: Путь к публичному ключу (SPKI PEM).
        jwks_path: Путь к JWKS-документу.
        kid: Идентификатор ключа.
        created: ``True`` — файлы выпущены этим вызовом; ``False`` —
            найдены ранее выпущенные (идемпотентный повтор).

    """

    private_path: Path
    public_path: Path
    jwks_path: Path
    kid: str
    created: bool


def _public_der(public_pem: str) -> bytes:
    """Возвращает DER публичного ключа (SPKI) для отпечатка ``kid``."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    key = load_pem_public_key(public_pem.encode("utf-8"))
    return key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def derive_kid(public_pem: str) -> str:
    """Вычисляет детерминированный ``kid`` по публичному ключу.

    Отпечаток — ``sha256`` от DER SPKI, первые 16 hex-символов. Один и тот
    же ключ всегда даёт один ``kid`` (важно для JWKS-резолва и для ротации:
    новый ключ → новый ``kid``).

    Args:
        public_pem: Публичный ключ в SPKI PEM.

    Returns:
        Строка ``kid`` (16 hex-символов).

    """
    return hashlib.sha256(_public_der(public_pem)).hexdigest()[:16]


def generate_rsa_keypair(*, key_size: int = DEFAULT_KEY_SIZE) -> RsaKeyPair:
    """Генерирует RSA-ключевую пару (PKCS#8 + SPKI, PEM).

    Args:
        key_size: Размер ключа в битах (по умолчанию 2048).

    Returns:
        :class:`RsaKeyPair` с PEM-строками и ``kid``.

    Raises:
        ValueError: Если ``key_size`` меньше 2048 бит (небезопасно для продa).

    """
    if key_size < 2048:
        raise ValueError(f"key_size должен быть ≥ 2048 бит, получено {key_size}")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return RsaKeyPair(
        private_pem=private_pem, public_pem=public_pem, kid=derive_kid(public_pem)
    )


def public_jwks(public_pem: str, kid: str, *, alg: str = "RS256") -> dict[str, Any]:
    """Собирает JWKS-документ из публичного ключа.

    Args:
        public_pem: Публичный ключ в SPKI PEM.
        kid: Идентификатор ключа.
        alg: Алгоритм подписи (``alg`` в JWK), по умолчанию ``RS256``.

    Returns:
        Словарь ``{"keys": [...]}`` — готовый JWKS-документ.

    """
    key = RSAKey.import_key(public_pem)
    jwk = key.as_dict()
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = alg
    return {"keys": [jwk]}


def write_keypair(
    out_dir: str | Path,
    *,
    kid: str | None = None,
    key_size: int = DEFAULT_KEY_SIZE,
    force: bool = False,
) -> KeyPairFiles:
    """Пишет ключевую пару в каталог (идемпотентно по пути).

    Если приватный ключ уже существует и ``force=False`` — файлы **не**
    перетираются: возвращаются ранее выпущенные пути и тот же ``kid``.
    Перевыпуск (``force=True``) инвалидирует все ранее выпущенные токены.

    Args:
        out_dir: Каталог для файлов (создаётся при отсутствии).
        kid: Явный ``kid``; по умолчанию — детерминированный отпечаток.
        key_size: Размер RSA-ключа в битах.
        force: Перевыпустить ключ, даже если файл уже существует.

    Returns:
        :class:`KeyPairFiles` с путями, ``kid`` и признаком ``created``.

    """
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    private_path = directory / PRIVATE_KEY_FILENAME
    public_path = directory / PUBLIC_KEY_FILENAME
    jwks_path = directory / JWKS_FILENAME

    if private_path.exists() and not force:
        public_pem = (
            public_path.read_text(encoding="utf-8")
            if public_path.exists()
            else _derive_public_pem(private_path)
        )
        resolved_kid = kid or derive_kid(public_pem)
        _logger.info(
            "jwt_keys.keypair_exists path=%s kid=%s (idempotent, не перетираю)",
            private_path,
            resolved_kid,
        )
        return KeyPairFiles(
            private_path=private_path,
            public_path=public_path,
            jwks_path=jwks_path,
            kid=resolved_kid,
            created=False,
        )

    pair = generate_rsa_keypair(key_size=key_size)
    resolved_kid = kid or pair.kid
    private_path.write_text(pair.private_pem, encoding="utf-8")
    public_path.write_text(pair.public_pem, encoding="utf-8")
    jwks_path.write_text(
        json.dumps(public_jwks(pair.public_pem, resolved_kid), indent=2),
        encoding="utf-8",
    )
    os.chmod(private_path, _PRIVATE_MODE)
    os.chmod(public_path, _PUBLIC_MODE)
    os.chmod(jwks_path, _PUBLIC_MODE)
    _logger.info(
        "jwt_keys.keypair_generated dir=%s kid=%s key_size=%s",
        directory,
        resolved_kid,
        key_size,
    )
    return KeyPairFiles(
        private_path=private_path,
        public_path=public_path,
        jwks_path=jwks_path,
        kid=resolved_kid,
        created=True,
    )


def _derive_public_pem(private_path: Path) -> str:
    """Восстанавливает публичный PEM из приватного (SPKI)."""
    return public_pem_from_private(private_path.read_text(encoding="utf-8"))


def public_pem_from_private(private_pem: str) -> str:
    """Восстанавливает публичный ключ (SPKI PEM) из приватного (PKCS#8 PEM).

    Args:
        private_pem: Приватный ключ в PKCS#8 PEM.

    Returns:
        Публичный ключ в SPKI PEM.

    Raises:
        ValueError: Если PEM нечитаем.

    """
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    private_key = load_pem_private_key(private_pem.encode("utf-8"), password=None)
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )


def load_public_key_pem(path: str | Path) -> RSAKey:
    """Загружает публичный ключ из SPKI PEM-файла.

    Args:
        path: Путь к PEM-файлу публичного ключа.

    Returns:
        :class:`joserfc.jwk.RSAKey` — готов к проверке подписи.

    Raises:
        FileNotFoundError: Если файла нет.
        ValueError: Если PEM нечитаем или это не RSA-ключ.

    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Публичный ключ не найден: {file_path}")
    return RSAKey.import_key(file_path.read_text(encoding="utf-8"))


def load_private_key_pem(path: str | Path) -> RSAKey:
    """Загружает приватный ключ из PKCS#8 PEM-файла.

    Args:
        path: Путь к PEM-файлу приватного ключа.

    Returns:
        :class:`joserfc.jwk.RSAKey` — готов к подписи.

    Raises:
        FileNotFoundError: Если файла нет.
        ValueError: Если PEM нечитаем или это не RSA-ключ.

    """
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Приватный ключ не найден: {file_path}")
    return RSAKey.import_key(file_path.read_text(encoding="utf-8"))


def _build_parser() -> argparse.ArgumentParser:
    """Собирает CLI-парсер утилиты."""
    parser = argparse.ArgumentParser(
        prog="python -m src.backend.core.security.jwt_keys",
        description="Генерация RSA-ключевой пары для JWT (RS256, ADR-0411).",
    )
    sub = parser.add_subparsers(dest="command")

    generate = sub.add_parser("generate", help="Выпустить ключевую пару в каталог.")
    generate.add_argument("--out", required=True, help="Каталог для файлов ключей.")
    generate.add_argument(
        "--kid", default=None, help="Явный kid (по умолчанию — отпечаток)."
    )
    generate.add_argument(
        "--key-size",
        type=int,
        default=DEFAULT_KEY_SIZE,
        help=f"Размер RSA-ключа в битах (по умолчанию {DEFAULT_KEY_SIZE}).",
    )
    generate.add_argument(
        "--force",
        action="store_true",
        help="Перевыпустить ключ (инвалидирует ранее выпущенные токены).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы командной строки (по умолчанию — ``sys.argv[1:]``).

    Returns:
        ``0`` — успех; ``2`` — ошибка аргументов/выполнения.

    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "generate":
        parser.print_usage(sys.stderr)
        return 2
    try:
        files = write_keypair(
            args.out, kid=args.kid, key_size=args.key_size, force=args.force
        )
    except (OSError, ValueError) as exc:
        _logger.error("jwt_keys.generate_failed out=%s err=%s", args.out, exc)
        print(f"Ошибка генерации ключей: {exc}", file=sys.stderr)
        return 2
    action = "выпущена" if files.created else "уже существует (не перетираю)"
    print(f"Ключевая пара {action}: kid={files.kid}")
    print(f"  private: {files.private_path}")
    print(f"  public:  {files.public_path}")
    print(f"  jwks:    {files.jwks_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI-точка входа
    sys.exit(main())
