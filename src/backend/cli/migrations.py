"""Migration commands для ``manage.py``.

P1 CLI decomposition W7 (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для bounded maintainability. 5 thin wrappers вокруг ``alembic`` CLI
subprocess вызовов (migrate, makemigration, downgrade, migration-history,
migration-current).

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py migrate`` — alembic upgrade head.
- ``python manage.py makemigration <message> [--autogenerate|--empty]`` — alembic revision.
- ``python manage.py downgrade <target>`` — alembic downgrade <target>.
- ``python manage.py migration-history [--verbose]`` — alembic history.
- ``python manage.py migration-current`` — alembic current.

NOT @app.command() decorated здесь — manage.py imports + decorates для
сохранения CLI contract (top-level команды).

Note: ``subprocess.run([sys.executable, ...])`` вызывает ``alembic``
через module runner — same semantics как ``python -m alembic <cmd>``.
Developer tool (CLI), не production runtime path.
"""

from __future__ import annotations

import subprocess
import sys

import typer


def migrate() -> None:
    """Применить все накопившиеся миграции (alembic upgrade head)."""
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)  # noqa: S603  # CLI developer tool: фиксированные args
    typer.echo("Migrations applied.")


def make_migration(
    message: str = typer.Argument(
        ..., help="Описание миграции (станет частью имени файла)"
    ),
    autogenerate: bool = typer.Option(
        True,
        "--autogenerate/--empty",
        help="Авто-детект изменений моделей (по умолчанию) или создать пустую миграцию",
    ),
) -> None:
    """Создать новую alembic-миграцию.

    Примеры::

        uv run python manage.py makemigration "add orders table"
        uv run python manage.py makemigration "manual data backfill" --empty
    """
    cmd = [sys.executable, "-m", "alembic", "revision"]
    if autogenerate:
        cmd.append("--autogenerate")
    cmd.extend(["-m", message])
    subprocess.run(cmd, check=True)  # noqa: S603  # CLI developer tool: cmd собран из sys.executable + literal alembic args + user-supplied message
    typer.echo(
        "Migration created. Проверь сгенерированный файл в "
        "src/backend/infrastructure/database/migrations/versions/ перед `migrate`."
    )


def downgrade(
    target: str = typer.Argument("-1", help="Revision id или шаг (-1, -2, base)"),
) -> None:
    """Откатить миграцию к указанной ревизии (по умолчанию на одну назад)."""
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", target], check=True)  # noqa: S603  # CLI developer tool: фиксированные args + revision id
    typer.echo(f"Downgraded to {target}.")


def migration_history(
    verbose: bool = typer.Option(False, "-v", help="Развёрнутая история"),
) -> None:
    """Показать историю миграций (alembic history)."""
    cmd = [sys.executable, "-m", "alembic", "history"]
    if verbose:
        cmd.append("-v")
    subprocess.run(cmd, check=True)  # noqa: S603  # CLI developer tool: cmd собран из sys.executable + literal alembic args


def migration_current() -> None:
    """Показать текущую ревизию БД (alembic current)."""
    subprocess.run([sys.executable, "-m", "alembic", "current"], check=True)


__all__ = (
    "downgrade",
    "make_migration",
    "migrate",
    "migration_current",
    "migration_history",
)
