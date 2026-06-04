"""CLI-обёртка для экспорта JSON-Schema всех DSL-процессоров (ADR-0058).

Запуск::

    python tools/dsl_export_schemas.py
    python tools/dsl_export_schemas.py --output docs/reference/schemas/processors
    python tools/dsl_export_schemas.py --output /tmp/schemas --verbose

Вызывает :func:`src.backend.dsl.registry.json_schema_exporter.export_processors_schema`
и выводит количество экспортированных схем.

Используется в ``make schemas`` (CI gate, ADR-0058).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    """Строит CLI-парсер аргументов.

    Returns:
        Настроенный :class:`argparse.ArgumentParser`.
    """

    parser = argparse.ArgumentParser(
        prog="dsl_export_schemas",
        description="Экспорт JSON-Schema DSL-процессоров (ADR-0058).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("docs/reference/schemas/processors"),
        help=(
            "Директория для записи схем (default: docs/reference/schemas/processors)"
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Включить DEBUG-логирование.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: Аргументы командной строки (``None`` → ``sys.argv[1:]``).

    Returns:
        Код возврата: 0 — успех, 1 — ошибка.
    """

    parser = _build_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")

    # Отложенный импорт — чтобы CLI-синтаксис не падал без зависимостей
    try:
        from src.backend.dsl.registry.json_schema_exporter import (
            export_processors_schema,
        )
    except ImportError as exc:
        print(f"ОШИБКА импорта: {exc}", file=sys.stderr)
        return 1

    try:
        count = export_processors_schema(args.output)
    except OSError as exc:
        print(f"ОШИБКА записи файлов: {exc}", file=sys.stderr)
        return 1

    print(f"Экспортировано {count} JSON-Schema процессоров → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
