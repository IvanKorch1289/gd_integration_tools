"""Генерация блока «текущие метрики» в README из кода.

Зачем
----
README содержал inline-число ``ActionHandlerRegistry (109 actions)``, которое
разошлось с фактическим runtime-значением. Ручные метрики в документации
устаревают молча: их никто не пересчитывает и ничто не проверяет.

Этот инструмент решает обе проблемы:

* ``--write`` пересчитывает метрики и перезаписывает блок между маркерами
  ``<!-- BEGIN GENERATED METRICS -->`` / ``<!-- END GENERATED METRICS -->``;
* ``--check`` (по умолчанию) ничего не пишет и возвращает exit 1, если блок
  разошёлся с кодом — то есть пригоден как CI-гейт против повторного
  устаревания.

Каждая метрика берётся из фактического состояния, а не из документации:

===========================  ==================================================
Метрика                      Источник
===========================  ==================================================
HEAD                         ``git rev-parse HEAD``
action count                 ``ActionHandlerRegistry.list_actions()``
                             после ``create_app()`` — регистрация действий
                             происходит в startup-фазах, до него реестр пуст
DSL route count              ``RouteRegistry.list_routes()``
protocol count               число протокольных entrypoint-пакетов
                             (исключаются ``middlewares``/``dependencies``/
                             приватные модули)
middleware count             длина ``app.user_middleware`` — фактический стек
OpenAPI paths/schemas        ``app.openapi()``
test count                   ``pytest --collect-only -q`` (последняя строка)
coverage threshold           ``[tool.coverage.report] fail_under`` в pyproject
layer baseline               вывод ``tools/check_layers.py``
===========================  ==================================================

Использование::

    uv run python tools/generate_current_metrics.py --write
    uv run python tools/generate_current_metrics.py --check
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
README = PROJECT_ROOT / "README.md"

BEGIN_MARKER = "<!-- BEGIN GENERATED METRICS -->"
END_MARKER = "<!-- END GENERATED METRICS -->"

#: Пакеты entrypoints, не являющиеся самостоятельными протоколами.
_NON_PROTOCOL_PACKAGES = {"middlewares", "dependencies", "__pycache__"}


def _git(*args: str) -> str:
    """Выполнить git-команду и вернуть stdout без пробелов.

    Args:
        args: аргументы git.

    Returns:
        stdout команды или пустая строка при ошибке.

    """
    git_bin = shutil.which("git")
    if git_bin is None:
        return ""
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный список аргументов, shell=False
            [git_bin, *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""
    except OSError, subprocess.SubprocessError:
        return ""


def _protocol_packages() -> list[str]:
    """Перечислить протокольные пакеты entrypoints.

    Returns:
        Отсортированные имена пакетов-протоколов.

    """
    base = PROJECT_ROOT / "src" / "backend" / "entrypoints"
    if not base.is_dir():
        return []
    return sorted(
        p.name
        for p in base.iterdir()
        if p.is_dir()
        and p.name not in _NON_PROTOCOL_PACKAGES
        and not p.name.startswith("_")
        and not p.name.startswith(".")
    )


def _pytest_count() -> str:
    """Получить количество собранных тестов.

    Returns:
        Строка вида ``20679 tests collected`` либо ``unavailable``.

    """
    try:
        proc = subprocess.run(  # noqa: S603 — литеральный argv, shell=False
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
    except OSError, subprocess.SubprocessError:
        return "unavailable"
    for line in reversed(proc.stdout.strip().splitlines()):
        if "collected" in line:
            match = re.search(r"(\d+)\s+tests?\s+collected", line)
            if match:
                return match.group(1)
        if "error" in line.lower():
            return f"COLLECTION_ERROR: {line.strip()}"
    return "unavailable"


def _coverage_threshold() -> str:
    """Извлечь порог покрытия из pyproject.

    Returns:
        Значение ``fail_under`` или ``unset``.

    """
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"fail_under\s*=\s*([0-9.]+)", text)
    return match.group(1) if match else "unset"


def _layer_baseline() -> str:
    """Получить строку baseline слоёв из канонического гейта.

    Returns:
        Строка вида ``0 новых / 22 legacy`` либо ``unavailable``.

    """
    try:
        proc = subprocess.run(  # noqa: S603 — литеральный argv, shell=False
            [sys.executable, str(PROJECT_ROOT / "tools" / "check_layers.py")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except OSError, subprocess.SubprocessError:
        return "unavailable"
    for line in proc.stdout.splitlines():
        if "Нарушений" in line:
            return line.strip()
    return "unavailable"


def collect_metrics() -> dict[str, object]:
    """Собрать все метрики из фактического состояния кода.

    Returns:
        Словарь метрик.

    """
    metrics: dict[str, object] = {
        "HEAD": _git("rev-parse", "HEAD"),
        "protocol_count": len(_protocol_packages()),
        "protocols": _protocol_packages(),
        "coverage_fail_under": _coverage_threshold(),
        "layer_baseline": _layer_baseline(),
        "test_count": _pytest_count(),
    }

    actions = routes = middleware = paths = schemas = "n/a"
    try:
        from src.backend.plugins.composition.app_factory import create_app

        app = create_app()
        from src.backend.dsl.commands.registry import action_handler_registry
        from src.backend.dsl.registry import route_registry

        actions = len(action_handler_registry.list_actions())
        routes = len(route_registry.list_routes())
        middleware = len(app.user_middleware)
        openapi = app.openapi()
        paths = len(openapi.get("paths", {}))
        schemas = len(openapi.get("components", {}).get("schemas", {}))
    except Exception as exc:  # noqa: BLE001 — метрики не должны ронять инструмент
        metrics["runtime_error"] = f"{type(exc).__name__}: {exc}"

    metrics["action_count"] = actions
    metrics["dsl_route_count"] = routes
    metrics["middleware_count"] = middleware
    metrics["openapi_paths"] = paths
    metrics["openapi_schemas"] = schemas
    return metrics


def render_block(metrics: dict[str, object]) -> str:
    """Отрисовать блок метрик для README.

    Args:
        metrics: Собранные метрики.

    Returns:
        Текст блока между маркерами.

    """
    generated_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    head = str(metrics.get("HEAD", "n/a"))[:12]
    protocols = ", ".join(metrics.get("protocols", []) or [])  # type: ignore[arg-type]
    lines = [
        BEGIN_MARKER,
        "",
        "<!-- СГЕНЕРИРОВАНО: `uv run python tools/generate_current_metrics.py --write`.",
        "     Проверка актуальности (CI-гейт): "
        "`... --check` → exit 1 при расхождении с кодом.",
        "     Правьте код, а не этот блок. -->",
        "",
        f"**Снимок кода:** `{head}` · сгенерировано {generated_at}",
        "",
        "| Метрика | Значение | Источник |",
        "|---|---:|---|",
        f"| HEAD | `{head}` | `git rev-parse HEAD` |",
        f"| Actions (runtime) | {metrics.get('action_count')} | "
        "`ActionHandlerRegistry.list_actions()` после `create_app()` |",
        f"| DSL-маршрутов | {metrics.get('dsl_route_count')} | "
        "`RouteRegistry.list_routes()` |",
        f"| Протоколов | {metrics.get('protocol_count')} | "
        f"пакеты entrypoints: {protocols} |",
        f"| Middleware в стеке | {metrics.get('middleware_count')} | "
        "`len(app.user_middleware)` |",
        f"| OpenAPI paths / schemas | {metrics.get('openapi_paths')} / "
        f"{metrics.get('openapi_schemas')} | `app.openapi()` |",
        f"| Тестов собрано | {metrics.get('test_count')} | "
        "`pytest --collect-only -q` |",
        f"| Порог покрытия | {metrics.get('coverage_fail_under')}% | "
        "`[tool.coverage.report] fail_under` |",
        f"| Layer baseline | {metrics.get('layer_baseline')} | "
        "`tools/check_layers.py` |",
        "",
    ]
    if metrics.get("runtime_error"):
        lines += [
            f"> ⚠️ Метрики времени выполнения недоступны: "
            f"`{metrics['runtime_error']}` — вероятно, требуется окружение "
            "(переменные БД/Redis). Числа выше тогда неполны.",
            "",
        ]
    lines.append(END_MARKER)
    return "\n".join(lines)


def _current_block(text: str) -> str | None:
    """Извлечь текущий сгенерированный блок из README.

    Args:
        text: содержимое README.

    Returns:
        Текст блока или ``None``, если маркеров нет.

    """
    match = re.search(
        rf"{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}", text, re.S
    )
    return match.group(0) if match else None


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI.

    Args:
        argv: аргументы командной строки.

    Returns:
        0 при успехе, 1 при расхождении блока с кодом (``--check``).

    """
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="перезаписать блок в README")
    mode.add_argument(
        "--check", action="store_true", help="только проверить актуальность (CI-гейт)"
    )
    mode.add_argument("--json", action="store_true", help="вывести метрики в JSON")
    args = parser.parse_args(argv)

    metrics = collect_metrics()

    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2, default=str))
        return 0

    block = render_block(metrics)
    text = README.read_text(encoding="utf-8")
    existing = _current_block(text)

    if args.write:
        if existing is None:
            print(
                "Маркеры не найдены в README — вставьте блок вручную:\n"
                f"{BEGIN_MARKER}\n...\n{END_MARKER}",
                file=sys.stderr,
            )
            return 2
        README.write_text(text.replace(existing, block, 1), encoding="utf-8")
        print(
            f"README обновлён: {metrics.get('action_count')} actions, "
            f"{metrics.get('test_count')} тестов"
        )
        return 0

    # По умолчанию и при --check — проверка.
    if existing is None:
        print(
            f"В README нет сгенерированного блока метрик ({BEGIN_MARKER} не найден).",
            file=sys.stderr,
        )
        return 1

    fresh = _strip_volatile(block)
    stale_stripped = _strip_volatile(existing)
    if fresh != stale_stripped:
        print(
            "Сгенерированный блок метрик в README устарел.\n"
            "Исправить: uv run python tools/generate_current_metrics.py --write",
            file=sys.stderr,
        )
        print("--- в README ---", file=sys.stderr)
        print(stale_stripped, file=sys.stderr)
        print("--- из кода ---", file=sys.stderr)
        print(fresh, file=sys.stderr)
        return 1

    print("Метрики README актуальны.")
    return 0


def _strip_volatile(block: str) -> str:
    """Убрать нестабильные части блока для сравнения.

    Args:
        block: текст блока.

    Returns:
        блок без строки-времени генерации.

    """
    return re.sub(r"· сгенерировано [^\n|]*", "", block)


if __name__ == "__main__":
    raise SystemExit(main())
