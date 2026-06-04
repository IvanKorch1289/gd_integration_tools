"""Генерация CycloneDX SBOM через cyclonedx-py CLI.

Назначение:
    Обёртка вокруг ``cyclonedx-py environment`` для использования в CI
    и через ``make sbom``. Поддерживает форматы JSON / XML / all.
    При отсутствии ``cyclonedx-py`` в окружении завершается с кодом 1
    и понятным сообщением вместо необработанного FileNotFoundError.

Использование:
    python tools/checks/generate_sbom.py --output-dir dist/sbom --format json
    python tools/checks/generate_sbom.py --output-dir dist/sbom --format all

Аргументы:
    --output-dir  Каталог для выходных файлов (по умолчанию: dist/sbom).
    --format      Формат вывода: json | xml | all (по умолчанию: json).

Зависимости (optional-dependencies[security]):
    cyclonedx-bom>=4.0  — устанавливается через ``pip install .[security]``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_TOOL = "cyclonedx-py"


def _check_tool_available() -> None:
    """Проверяет наличие ``cyclonedx-py`` в PATH.

    Raises:
        SystemExit: завершает процесс с кодом 1, если инструмент не найден.
    """
    if shutil.which(_TOOL) is None:
        print(
            f"[ERROR] '{_TOOL}' не найден в PATH.\n"
            "Установите: pip install 'cyclonedx-bom>=4.0' или "
            "pip install '.[security]'",
            file=sys.stderr,
        )
        sys.exit(1)


def _generate(output_dir: Path, fmt: str) -> None:
    """Запускает генерацию SBOM в указанном формате.

    Args:
        output_dir: Каталог для выходных файлов.
        fmt: Формат вывода (``json``, ``xml`` или ``all``).

    Raises:
        SystemExit: при ненулевом коде возврата дочернего процесса.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    formats: list[tuple[str, str]] = []
    match fmt:
        case "json":
            formats = [("JSON", "sbom.cdx.json")]
        case "xml":
            formats = [("XML", "sbom.cdx.xml")]
        case "all":
            formats = [("JSON", "sbom.cdx.json"), ("XML", "sbom.cdx.xml")]
        case _:
            print(
                f"[ERROR] Неизвестный формат: '{fmt}'. Допустимы: json, xml, all",
                file=sys.stderr,
            )
            sys.exit(1)

    for of_flag, filename in formats:
        output_path = output_dir / filename
        cmd = [_TOOL, "environment", "--of", of_flag, "-o", str(output_path)]
        print(f"[INFO] Генерация SBOM ({of_flag}): {output_path}")
        result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
        if result.returncode != 0:
            print(
                f"[ERROR] {_TOOL} завершился с кодом {result.returncode}:",
                file=sys.stderr,
            )
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            sys.exit(result.returncode)
        print(f"[OK] SBOM записан: {output_path}")


def main() -> None:
    """Точка входа CLI: разбор аргументов и запуск генерации SBOM."""
    parser = argparse.ArgumentParser(
        description="Генерация CycloneDX SBOM для supply-chain CI gate (K1 S3 W3)."
    )
    parser.add_argument(
        "--output-dir",
        default="dist/sbom",
        help="Каталог для выходных файлов (по умолчанию: dist/sbom).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "xml", "all"],
        default="json",
        help="Формат вывода: json | xml | all (по умолчанию: json).",
    )
    args = parser.parse_args()

    _check_tool_available()
    _generate(Path(args.output_dir), args.format)


if __name__ == "__main__":
    main()
