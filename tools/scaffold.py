"""Scaffold-утилита: генерация шаблонов Processor / Service / Route.

Запуск::

    python tools/scaffold.py processor --name MyCustom --module custom
    python tools/scaffold.py service --name Payments --group integrations
    python tools/scaffold.py route --name invoices.sync --source "timer:60s"

Генерируемые файлы содержат русские docstring'и, базовую структуру и
``# TODO`` для мест, где разработчик должен дописать логику. Опция
``--dry-run`` показывает содержимое без записи.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


# ──────────────────── Templates ────────────────────


def processor_template(class_name: str) -> str:
    """Возвращает код нового DSL-процессора."""
    return dedent(f'''
        """{class_name} processor.

        Описание работы процессора — заполните при реализации.
        """

        from __future__ import annotations

        from typing import Any

        from src.dsl.engine.context import ExecutionContext
        from src.dsl.engine.exchange import Exchange
        from src.dsl.engine.processors.base import BaseProcessor


        class {class_name}Processor(BaseProcessor):
            """Кратко опишите назначение процессора."""

            def __init__(self, *, name: str | None = None) -> None:
                super().__init__(name=name or "{class_name.lower()}")

            async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
                """Основная логика. Модифицирует ``exchange`` in-place.

                Args:
                    exchange: Текущее сообщение pipeline.
                    context: Контекст исполнения (settings, metrics, tracing).
                """
                # TODO: реализуйте бизнес-логику
                return None
    ''').lstrip()


def service_template(class_name: str) -> str:
    """Возвращает код нового сервиса."""
    return dedent(f'''
        """{class_name}Service — бизнес-сервис.

        Инстанс создаётся как module-level object и доступен через
        ``get_{class_name.lower()}_service()``. Регистрируется как action
        в ``src/dsl/commands/setup.py``.
        """

        from __future__ import annotations

        import logging
        from typing import Any

        logger = logging.getLogger(__name__)


        class {class_name}Service:
            """Опишите ответственность сервиса."""

            def __init__(self) -> None:
                pass

            async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
                """Пример action-метода, вызываемого из DSL/очереди/AI-tool.

                Args:
                    payload: Входные параметры (валидация — на вызывающей стороне).

                Returns:
                    Результат в dict-виде.
                """
                return {{"ok": True}}


        _{class_name.lower()}_service_instance = {class_name}Service()


        def get_{class_name.lower()}_service() -> {class_name}Service:
            """Возвращает module-level инстанс сервиса."""
            return _{class_name.lower()}_service_instance
    ''').lstrip()


def route_template(route_id: str, source: str) -> str:
    """Возвращает код нового DSL-маршрута."""
    return dedent(f'''
        """Маршрут {route_id}.

        Запускается по источнику ``{source}``. Генерирован scaffold-скриптом.
        """

        from __future__ import annotations

        from src.dsl.builder import RouteBuilder


        route = (
            RouteBuilder.from_("{route_id}", source="{source}")
            .correlation_id()
            .log("start")
            # TODO: добавьте процессоры по необходимости
            .build()
        )
    ''').lstrip()


# ──────────────────── CLI ────────────────────


def cmd_processor(args: argparse.Namespace) -> None:
    """Создаёт файл процессора в ``src/dsl/engine/processors/<module>.py``."""
    module = args.module or "custom"
    class_name = args.name
    path = SRC / "dsl" / "engine" / "processors" / f"{module}.py"
    code = processor_template(class_name)
    _emit(path, code, args.dry_run)


def cmd_service(args: argparse.Namespace) -> None:
    """Создаёт файл сервиса в ``src/services/<group>/<name>.py``."""
    group = args.group or "core"
    class_name = args.name
    filename = class_name.lower() + ".py"
    path = SRC / "services" / group / filename
    code = service_template(class_name)
    _emit(path, code, args.dry_run)


def cmd_route(args: argparse.Namespace) -> None:
    """Создаёт файл маршрута в ``src/dsl/routes/<name>.py``."""
    # Используем route_id в имени файла: "invoices.sync" → "invoices_sync.py"
    safe_name = args.name.replace(".", "_")
    path = SRC / "dsl" / "routes" / f"{safe_name}.py"
    code = route_template(args.name, args.source or "internal:manual")
    _emit(path, code, args.dry_run)


def _emit(path: Path, code: str, dry_run: bool) -> None:
    """Пишет файл или печатает содержимое при ``dry_run``."""
    if dry_run:
        print(f"# DRY-RUN: would create {path}")
        print(code)
        return

    if path.exists():
        print(f"ERROR: файл уже существует: {path}")
        sys.exit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    print(f"Created: {path}")


def main() -> None:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description="Scaffold для новых компонентов")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("processor", help="Создать новый DSL-процессор")
    p.add_argument("--name", required=True, help="Имя класса (без Processor-суффикса)")
    p.add_argument("--module", help="Имя файла в processors/ (default: custom)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_processor)

    s = sub.add_parser("service", help="Создать новый сервис")
    s.add_argument("--name", required=True, help="Имя класса (без Service-суффикса)")
    s.add_argument("--group", choices=["ai", "ops", "integrations", "io", "core"], help="Подпакет")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_service)

    r = sub.add_parser("route", help="Создать новый DSL-маршрут")
    r.add_argument("--name", required=True, help="route_id (e.g., invoices.sync)")
    r.add_argument("--source", help="Источник (default: internal:manual)")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(func=cmd_route)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
