"""Scaffold-утилита: генерация шаблонов Processor / Service / Route.

Запуск::

    python tools/scaffold.py processor --name MyCustom --module custom
    python tools/scaffold.py service --name Payments --group integrations
    python tools/scaffold.py route --name invoices.sync --source "timer:60s"

Генерируемые файлы содержат русские docstring'и, базовую структуру и
``# TODO`` для мест, где разработчик должен дописать логику. Опция
``--dry-run`` показывает содержимое без записи.

MINIMAX W6 P1-8 Phase 10 (cycle 153): мигрирован с ``argparse`` на ``typer`` +
``rich`` (libraries > custom, per ADR-0084). Сохранены: 3 subcommands
(processor/service/route) + ``--dry-run`` safety flag.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import typer
from rich.console import Console

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

        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.exchange import Exchange
        from src.backend.dsl.engine.processors.base import BaseProcessor


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

        from src.backend.dsl.builder import RouteBuilder


        route = (
            RouteBuilder.from_("{route_id}", source="{source}")
            .correlation_id()
            .log("start")
            # TODO: добавьте процессоры по необходимости
            .build()
        )
    ''').lstrip()


# ──────────────────── CLI ────────────────────


app = typer.Typer(
    name="scaffold",
    help="Scaffold для новых компонентов (Processor / Service / Route).",
    no_args_is_help=True,
    add_completion=False,
)
_console = Console()


def _emit(path: Path, code: str, dry_run: bool) -> None:
    """Пишет файл или печатает содержимое при ``dry_run``."""
    if dry_run:
        _console.print(f"[yellow]# DRY-RUN: would create {path}[/]")
        # Plain print для сохранить content readable без rich markup.
        print(code)
        return

    if path.exists():
        _console.print(f"[red]ERROR: файл уже существует: {path}[/]")
        raise typer.Exit(code=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    _console.print(f"[green]Created:[/] {path}")


@app.command(name="processor", help="Создать новый DSL-процессор")
def cmd_processor(
    name: str = typer.Option(
        ...,
        "--name",
        help="Имя класса (без Processor-суффикса).",
    ),
    module: str | None = typer.Option(
        None,
        "--module",
        help="Имя файла в processors/ (default: custom).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Показать содержимое без записи.",
    ),
) -> None:
    """Создаёт файл процессора в ``src/backend/dsl/engine/processors/<module>.py``."""
    module_name = module or "custom"
    path = SRC / "backend" / "dsl" / "engine" / "processors" / f"{module_name}.py"
    code = processor_template(name)
    _emit(path, code, dry_run)


@app.command(name="service", help="Создать новый сервис")
def cmd_service(
    name: str = typer.Option(
        ...,
        "--name",
        help="Имя класса (без Service-суффикса).",
    ),
    group: str | None = typer.Option(
        None,
        "--group",
        help="Подпакет: ai / ops / integrations / io / core (default: core).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Показать содержимое без записи.",
    ),
) -> None:
    """Создаёт файл сервиса в ``src/services/<group>/<name>.py``."""
    group_name = group or "core"
    filename = name.lower() + ".py"
    path = SRC / "backend" / "services" / group_name / filename
    code = service_template(name)
    _emit(path, code, dry_run)


@app.command(name="route", help="Создать новый DSL-маршрут")
def cmd_route(
    name: str = typer.Option(
        ...,
        "--name",
        help="route_id (e.g., invoices.sync).",
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        help="Источник (default: internal:manual).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Показать содержимое без записи.",
    ),
) -> None:
    """Создаёт файл маршрута в ``src/backend/dsl/routes/<name>.py``."""
    # Используем route_id в имени файла: "invoices.sync" → "invoices_sync.py"
    safe_name = name.replace(".", "_")
    path = SRC / "backend" / "dsl" / "routes" / f"{safe_name}.py"
    code = route_template(name, source or "internal:manual")
    _emit(path, code, dry_run)


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI (backward-compat shim для существующих скриптов).

    Запускает typer app через typer.testing.CliRunner (для тестов)
    или sys.argv (для CLI invocation). Возвращает exit code.
    """
    if argv is not None:
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, argv)
        return result.exit_code
    # CLI invocation: typer сам подхватит sys.argv[1:]
    try:
        app()
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
