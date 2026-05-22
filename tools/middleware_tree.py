"""CLI ``make middleware-tree``: показать дерево зарегистрированных middleware.

Строит ``MiddlewareRegistry`` через ``build_default_registry`` (тот же
путь, что и production setup_middlewares), подгружает entry-points
``gd_integration_tools.middleware_hooks`` и печатает результат
``registry.render_tree()`` в stdout.

Аргументы CLI отсутствуют — выводит только текущее состояние.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    _ = argv  # CLI без аргументов; параметр сохранён для совместимости.
    from src.backend.entrypoints.middlewares.setup_middlewares import (
        build_default_registry,
    )

    registry = build_default_registry()
    try:
        registry.register_from_entry_points()
    except ValueError as exc:
        print(f"WARN: entry_points load failed: {exc}", file=sys.stderr)
    print(registry.render_tree())
    return 0


if __name__ == "__main__":
    sys.exit(main())
