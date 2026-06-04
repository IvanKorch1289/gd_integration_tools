"""Подписание артефакта через cosign (keyless или key-based).

Назначение:
    Обёртка вокруг ``cosign sign`` для использования в CI и через
    ``make cosign-sign``. Поддерживает подпись через --key (PKCS8 PEM).
    При отсутствии ``cosign`` в PATH завершается с кодом 1 и понятным
    сообщением вместо необработанного FileNotFoundError.

    Типичный сценарий использования — подпись SBOM или OCI-образа
    перед публикацией в release pipeline (supply-chain V4, R3).

Использование:
    python tools/checks/cosign_sign.py --artifact dist/sbom/sbom.cdx.json --key cosign.key
    ARTIFACT=dist/sbom.cdx.json KEY=cosign.key make cosign-sign

Аргументы:
    --artifact  Путь к подписываемому артефакту (обязательный).
    --key       Путь к приватному ключу cosign в формате PEM (обязательный).

Зависимости:
    cosign — устанавливается отдельно (не Python пакет):
    https://docs.sigstore.dev/cosign/system_config/installation/
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_TOOL = "cosign"


def _check_tool_available() -> None:
    """Проверяет наличие ``cosign`` в PATH.

    Raises:
        SystemExit: завершает процесс с кодом 1, если инструмент не найден.
    """
    if shutil.which(_TOOL) is None:
        print(
            f"[ERROR] '{_TOOL}' не найден в PATH.\n"
            "Установите cosign: https://docs.sigstore.dev/cosign/system_config/installation/\n"
            "Или через: brew install cosign / apt install cosign",
            file=sys.stderr,
        )
        sys.exit(1)


def _validate_artifact(artifact_path: Path) -> None:
    """Проверяет существование артефакта перед подписанием.

    Args:
        artifact_path: Путь к подписываемому файлу.

    Raises:
        SystemExit: завершает процесс с кодом 1, если файл не найден.
    """
    if not artifact_path.exists():
        print(f"[ERROR] Артефакт не найден: {artifact_path}", file=sys.stderr)
        sys.exit(1)


def _validate_key(key_path: Path) -> None:
    """Проверяет существование файла ключа.

    Args:
        key_path: Путь к приватному ключу.

    Raises:
        SystemExit: завершает процесс с кодом 1, если файл не найден.
    """
    if not key_path.exists():
        print(f"[ERROR] Ключ не найден: {key_path}", file=sys.stderr)
        sys.exit(1)


def _sign(artifact_path: Path, key_path: Path) -> None:
    """Вызывает ``cosign sign --key <key> <artifact>``.

    Args:
        artifact_path: Путь к подписываемому артефакту.
        key_path: Путь к приватному ключу cosign в формате PEM.

    Raises:
        SystemExit: при ненулевом коде возврата cosign.
    """
    cmd = [
        _TOOL,
        "sign-blob",
        "--key",
        str(key_path),
        "--output-signature",
        f"{artifact_path}.sig",
        str(artifact_path),
    ]
    print(f"[INFO] Подписание артефакта: {artifact_path}")
    print(f"[INFO] Ключ: {key_path}")

    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603

    if result.returncode != 0:
        print(
            f"[ERROR] cosign завершился с кодом {result.returncode}:", file=sys.stderr
        )
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    sig_path = Path(f"{artifact_path}.sig")
    print(f"[OK] Подпись сохранена: {sig_path}")


def main() -> None:
    """Точка входа CLI: разбор аргументов и запуск подписания артефакта."""
    parser = argparse.ArgumentParser(
        description="cosign artifact signing для supply-chain CI gate (K1 S3 W3)."
    )
    parser.add_argument(
        "--artifact",
        required=True,
        help="Путь к подписываемому артефакту (обязательный).",
    )
    parser.add_argument(
        "--key",
        required=True,
        help="Путь к приватному ключу cosign в формате PEM (обязательный).",
    )
    args = parser.parse_args()

    artifact_path = Path(args.artifact)
    key_path = Path(args.key)

    _check_tool_available()
    _validate_artifact(artifact_path)
    _validate_key(key_path)
    _sign(artifact_path, key_path)


if __name__ == "__main__":
    main()
