"""Runtime servers cluster для ``manage.py``.

P1 CLI decomposition W11 (v4 §10 P1, 2026-09-24): извлечено из
``manage.py`` для bounded maintainability. 5 runtime server commands
(run / http3-serve / grpc-serve / run-frontend / run-all) + helper
``settings_default`` — все связаны с dev/prod startup workflow.

Per v4 §10 P1 «CLI decomposition»: «декомпозировать manage.py малыми
командами на уже используемом Typer/Rich, сохраняя CLI contract и help
snapshots. Не создавать второй CLI».

CLI contract (preserved 100%):
- ``python manage.py run [--host] [--port] [--workers] [--server uvicorn|granian]``
  — FastAPI backend через выбранный ASGI-сервер.
- ``python manage.py http3-serve [--port] [--certfile] [--keyfile]`` —
  HTTP/3 + WebTransport server (Sprint 8 opt-in).
- ``python manage.py grpc-serve [--socket] [--max-workers]`` —
  gRPC server on Unix socket (D-AUDIT-20801).
- ``python manage.py run-frontend [--port 8501]`` — Streamlit dashboard.
- ``python manage.py run-all [--backend-port 8000] [--frontend-port 8501]``
  — backend + frontend параллельно.

NOT @app.command() decorated здесь — manage.py imports + decorates для
сохранения CLI contract (top-level команды).

Note: ``bootstrap-admin`` НЕ переехал — это auth-setup, отдельная wave (W13).
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from pathlib import Path

import typer


def settings_default(field: str) -> str:
    """Возвращает default value для path из settings (для echo в cli)."""
    try:
        from src.backend.core.config.settings import settings as _s

        parts = field.split(".")
        obj = _s
        for p in parts:
            obj = getattr(obj, p)
        return str(obj)
    except Exception:
        return "<default>"


def run(
    host: str | None = typer.Option(None, help="Bind host (override APP_HOST)"),
    port: int | None = typer.Option(None, help="Bind port (override APP_PORT)"),
    workers: int | None = typer.Option(
        None, help="Worker count (override APP_WORKERS)"
    ),
    server: str | None = typer.Option(
        None, help="ASGI server: uvicorn | granian (override APP_SERVER)"
    ),
) -> None:
    """Запуск FastAPI backend через выбранный ASGI-сервер.

    Делегирует выбор бэкенда (uvicorn/granian) в ``src.backend.main:run`` —
    управляется ``settings.app.server`` (env ``APP_SERVER``).
    """
    if host is not None:
        os.environ["APP_HOST"] = host
    if port is not None:
        os.environ["APP_PORT"] = str(port)
    if workers is not None:
        os.environ["APP_WORKERS"] = str(workers)
    if server is not None:
        os.environ["APP_SERVER"] = server

    cmd = [sys.executable, "-m", "src.backend.main"]
    typer.echo(
        f"Starting backend (server={os.environ.get('APP_SERVER', 'uvicorn')})..."
    )
    os.execvp(cmd[0], cmd)  # noqa: S606  # CLI developer tool: cmd сформирован из sys.executable + фиксированных аргументов


def http3_serve(
    port: int | None = typer.Option(None, help="UDP port (override APP_HTTP3_PORT)"),
    certfile: str | None = typer.Option(
        None, help="PEM cert (override APP_HTTP3_CERTFILE)"
    ),
    keyfile: str | None = typer.Option(
        None, help="PEM key (override APP_HTTP3_KEYFILE)"
    ),
) -> None:
    """Запуск опционального HTTP/3 + WebTransport сервера (Sprint 8 opt-in).

    Требует extra ``http3`` (``uv sync --extra http3``) и валидные
    TLS-сертификаты с ALPN h3/h3-29.
    """
    if port is not None:
        os.environ["APP_HTTP3_PORT"] = str(port)
    if certfile is not None:
        os.environ["APP_HTTP3_CERTFILE"] = certfile
    if keyfile is not None:
        os.environ["APP_HTTP3_KEYFILE"] = keyfile
    os.environ["APP_HTTP3_ENABLED"] = "true"

    from src.backend.entrypoints.http3.cli import run_from_settings

    typer.echo("Starting HTTP/3 server (aioquic) ...")
    run_from_settings()


def grpc_serve(
    socket_path: str | None = typer.Option(
        None, "--socket", help="Unix socket path (override grpc.socket_path)"
    ),
    max_workers: int | None = typer.Option(
        None,
        "--max-workers",
        help="ThreadPoolExecutor size (override grpc.max_workers)",
    ),
) -> None:
    """Запуск standalone gRPC-сервера на Unix socket (D-AUDIT-20801).

    Lightweight вариант для dev/test (cycle 207b deferred — теперь
    реализовано). В production gRPC server поднимается как отдельный
    compose service или K8s pod. Использует `settings.grpc.socket_path`
    (default ``/tmp/order_service.sock``) если --socket не задан.

    Examples:
        # Default (Unix socket из base.yml)
        uv run manage.py grpc-serve

        # Custom socket
        uv run manage.py grpc-serve --socket /tmp/test.sock
    """
    if socket_path is not None:
        os.environ["GRPC_SOCKET_PATH"] = socket_path
    if max_workers is not None:
        os.environ["GRPC_MAX_WORKERS"] = str(max_workers)

    from src.backend.entrypoints.grpc.grpc_server.server import serve

    typer.echo(
        f"Starting gRPC server (socket={socket_path or settings_default('grpc.socket_path')}, "
        f"workers={max_workers or settings_default('grpc.max_workers')}) ..."
    )
    asyncio.run(serve())


def run_frontend(port: int = typer.Option(8501, help="Streamlit port")) -> None:
    """Запуск Streamlit dashboard.

    S93 W2-C11: добавлен PYTHONPATH=$(pwd) для sys.path, чтобы убрать
    хаки sys.path.insert в 3 page-файлах. Запускать из project root.
    """
    project_root = Path.cwd().resolve()
    # S46 fix: streamlit installed in .venv (uv python 3.14), but
    # manage.py may run under system python (sys.executable != .venv python).
    # Use .venv/bin/python explicitly for streamlit subprocess.
    venv_python = project_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        typer.echo(
            f"[WARNING] {venv_python} not found — falling back to sys.executable",
            err=True,
        )
        venv_python = Path(sys.executable)
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    paths_str = (
        [str(project_root), *existing.split(os.pathsep)]
        if existing
        else [str(project_root)]
    )
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths_str))

    cmd = [
        str(venv_python),
        "-m",
        "streamlit",
        "run",
        "src/frontend/streamlit_app/app.py",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]
    typer.echo(f"Starting Streamlit on :{port} (PYTHONPATH={env['PYTHONPATH']})...")
    os.execvpe(cmd[0], cmd, env)  # noqa: S606  # CLI developer tool: cmd сформирован из sys.executable + фиксированных аргументов


def run_all(
    backend_port: int = typer.Option(8000, help="Backend port"),
    frontend_port: int = typer.Option(8501, help="Frontend port"),
) -> None:
    """Запуск backend + frontend параллельно."""
    procs: list[subprocess.Popen] = []

    try:
        typer.echo(
            f"Starting backend on :{backend_port} + frontend on :{frontend_port}..."
        )

        # S46 fix: streamlit in .venv, backend in sys.executable
        venv_python = Path(__file__).parent / ".venv" / "bin" / "python"
        if not venv_python.exists():
            typer.echo(
                f"[WARNING] {venv_python} not found — falling back to sys.executable",
                err=True,
            )
            venv_python = Path(sys.executable)

        backend = subprocess.Popen(  # noqa: S603  # CLI developer tool: фиксированный sys.executable + literal args
            [
                sys.executable,
                "-m",
                "uvicorn",
                "src.backend.main:app",
                "--host",
                "0.0.0.0",  # noqa: S104  # CLI developer tool: dev-режим, listen на всех интерфейсах
                "--port",
                str(backend_port),
            ]
        )
        procs.append(backend)

        frontend_env = os.environ.copy()
        project_root = Path.cwd().resolve()
        existing = frontend_env.get("PYTHONPATH", "")
        paths_str = (
            [str(project_root), *existing.split(os.pathsep)]
            if existing
            else [str(project_root)]
        )
        frontend_env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths_str))

        frontend = subprocess.Popen(  # noqa: S603  # CLI developer tool: фиксированный sys.executable + literal args
            [
                str(venv_python),
                "-m",
                "streamlit",
                "run",
                "src/frontend/streamlit_app/app.py",
                "--server.port",
                str(frontend_port),
                "--server.headless",
                "true",
            ],
            env=frontend_env,
        )
        procs.append(frontend)

        typer.echo("Both services running. Press Ctrl+C to stop.")
        for p in procs:
            p.wait()

    except KeyboardInterrupt:
        typer.echo("\nStopping services...")
        for p in procs:
            p.send_signal(signal.SIGTERM)
        for p in procs:
            p.wait(timeout=10)
        typer.echo("Services stopped.")


__all__ = (
    "grpc_serve",
    "http3_serve",
    "run",
    "run_all",
    "run_frontend",
    "settings_default",
)
