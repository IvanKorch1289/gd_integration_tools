"""Запуск pip-audit с выводом отчёта об уязвимостях (warn-only режим).

Назначение:
    Обёртка вокруг ``pip-audit`` для использования в CI и через
    ``make audit-deps``. Запускает сканирование, парсит JSON-отчёт,
    выводит сводку и завершается с кодом возврата pip-audit.
    При отсутствии ``pip-audit`` завершается с кодом 1 и понятным сообщением.

    В warn-only режиме (``make audit-deps``) Makefile-вызывающий добавляет
    ``|| echo "[WARN] ..."`` вокруг вызова этого скрипта — сам скрипт
    корректно отдаёт реальный exit code pip-audit.

Использование:
    python tools/checks/run_pip_audit.py
    python tools/checks/run_pip_audit.py --output dist/pip-audit.json

Аргументы:
    --output  Путь для JSON-отчёта (по умолчанию: dist/pip-audit.json).

Зависимости (optional-dependencies[security]):
    pip-audit>=2.7  — устанавливается через ``pip install .[security]``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_TOOL = "pip-audit"


def _check_tool_available() -> None:
    """Проверяет наличие ``pip-audit`` в PATH.

    Raises:
        SystemExit: завершает процесс с кодом 1, если инструмент не найден.
    """
    if shutil.which(_TOOL) is None:
        print(
            f"[ERROR] '{_TOOL}' не найден в PATH.\n"
            "Установите: pip install 'pip-audit>=2.7' или "
            "pip install '.[security]'",
            file=sys.stderr,
        )
        sys.exit(1)


def _parse_report(output_path: Path) -> tuple[int, int]:
    """Разбирает JSON-отчёт pip-audit и возвращает статистику уязвимостей.

    Args:
        output_path: Путь к JSON-файлу отчёта.

    Returns:
        Кортеж (vuln_count, affected_packages) — общее число уязвимостей
        и число затронутых пакетов.
    """
    if not output_path.exists():
        return 0, 0

    try:
        with output_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return 0, 0

    # Формат pip-audit JSON: {"dependencies": [{"name": ..., "vulns": [...]}]}
    dependencies: list[dict] = data.get("dependencies", [])
    affected = 0
    vuln_count = 0
    for dep in dependencies:
        vulns = dep.get("vulns", [])
        if vulns:
            affected += 1
            vuln_count += len(vulns)

    return vuln_count, affected


def main() -> None:
    """Точка входа CLI: запуск pip-audit и вывод сводки уязвимостей."""
    parser = argparse.ArgumentParser(
        description="pip-audit scan (warn-only) для supply-chain CI gate (K1 S3 W3).",
    )
    parser.add_argument(
        "--output",
        default="dist/pip-audit.json",
        help="Путь для JSON-отчёта (по умолчанию: dist/pip-audit.json).",
    )
    args = parser.parse_args()

    _check_tool_available()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [_TOOL, "--format=json", f"--output={output_path}"]
    print(f"[INFO] Запуск pip-audit → {output_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603

    vuln_count, affected = _parse_report(output_path)

    match result.returncode:
        case 0:
            print(f"[OK] pip-audit: уязвимостей не обнаружено. Отчёт: {output_path}")
        case _:
            print(
                f"[WARN] pip-audit завершился с кодом {result.returncode}. "
                f"Уязвимостей: {vuln_count} в {affected} пакетах. "
                f"Отчёт: {output_path}",
                file=sys.stderr,
            )
            if result.stderr:
                print(result.stderr, file=sys.stderr)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
