"""CLI-проверка semver-совместимости plugin.toml манифестов.

Назначение:
    Сканирует директорию плагинов, читает каждый plugin.toml и проверяет:
    - наличие обязательных полей: name, version, requires_core;
    - соответствие version шаблону ^X.Y.Z(-pre-суффикс)?$;
    - валидность requires_core как PEP 440 specifier (≥X.Y,<X.Z и пр.);
    - exit 1 при наличии хотя бы одного невалидного манифеста.

Использование:
    python tools/checks/check_plugin_semver.py
    python tools/checks/check_plugin_semver.py --plugins-dir extensions/ --strict

Аргументы:
    --plugins-dir   Директория с плагинами (default: extensions/).
    --strict        Завершить с ошибкой при любом предупреждении.

Зависимости:
    packaging — уже в стеке проекта (stdlib-совместимый PEP 440).
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet

# Паттерн для SemVer: X.Y.Z с опциональным pre-release суффиксом.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*)?$")

_OK = "[OK]"
_WARN = "[WARN]"
_ERR = "[ERROR]"


def _validate_version(version: str) -> str | None:
    """Проверяет строку version на соответствие SemVer-шаблону.

    Args:
        version: Строка версии из plugin.toml.

    Returns:
        Строка с описанием ошибки или None, если версия валидна.
    """
    if not _SEMVER_RE.match(version):
        return f"version '{version}' не соответствует SemVer X.Y.Z(-pre)?"
    return None


def _validate_requires_core(requires_core: str) -> str | None:
    """Проверяет requires_core как корректный PEP 440 SpecifierSet.

    Args:
        requires_core: Строка спецификации версии ядра из plugin.toml.

    Returns:
        Строка с описанием ошибки или None, если спецификатор валиден.
    """
    try:
        SpecifierSet(requires_core)
    except InvalidSpecifier as exc:
        return f"requires_core '{requires_core}' не является валидным PEP 440 specifier: {exc}"
    return None


def _check_manifest(toml_path: Path) -> tuple[bool, list[str]]:
    """Проверяет один plugin.toml файл.

    Args:
        toml_path: Путь к файлу plugin.toml.

    Returns:
        Кортеж (valid: bool, errors: list[str]).
    """
    errors: list[str] = []

    try:
        with toml_path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        return False, [f"TOML parse error: {exc}"]

    # Обязательные поля.
    for field in ("name", "version", "requires_core"):
        if field not in data:
            errors.append(f"обязательное поле '{field}' отсутствует")

    if errors:
        return False, errors

    # Валидация значений.
    if err := _validate_version(str(data["version"])):
        errors.append(err)

    if err := _validate_requires_core(str(data["requires_core"])):
        errors.append(err)

    return len(errors) == 0, errors


def _run(plugins_dir: Path, strict: bool) -> int:
    """Сканирует директорию плагинов и проверяет каждый plugin.toml.

    Args:
        plugins_dir: Директория с поддиректориями плагинов.
        strict: При True — любая ошибка → exit 1.

    Returns:
        Код завершения: 0 при успехе, 1 при ошибках.
    """
    if not plugins_dir.exists():
        print(f"{_WARN} Директория плагинов не найдена: {plugins_dir}", file=sys.stderr)
        return 0

    manifests = sorted(plugins_dir.rglob("plugin.toml"))
    if not manifests:
        print(f"{_WARN} plugin.toml файлы не найдены в {plugins_dir}")
        return 0

    total = len(manifests)
    invalid_count = 0

    for toml_path in manifests:
        plugin_name = toml_path.parent.name
        valid, errors = _check_manifest(toml_path)

        if valid:
            print(f"{_OK} {plugin_name}: semver OK")
        else:
            invalid_count += 1
            for err in errors:
                print(f"{_ERR} {plugin_name}: {err}", file=sys.stderr)

    print(f"\nПроверено манифестов: {total}. Невалидных: {invalid_count}.")

    if invalid_count > 0:
        return 1
    return 0


def main() -> None:
    """Точка входа CLI для проверки semver манифестов плагинов."""
    parser = argparse.ArgumentParser(
        description="Проверка semver plugin.toml манифестов (K1 S3 W5).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--plugins-dir",
        default="extensions/",
        help="Директория с плагинами (default: extensions/).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Strict-режим: завершить с ошибкой при любом предупреждении.",
    )
    args = parser.parse_args()

    plugins_dir = Path(args.plugins_dir)
    exit_code = _run(plugins_dir, strict=args.strict)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
