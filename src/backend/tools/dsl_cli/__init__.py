"""gdi dsl <command> — CLI-инструменты для DSL (E2).

Commands:
* lint — проверка YAML DSL-файла.
* repl — интерактивная отладка route.
* diff — сравнение v1/v2 route.
* profile — профилирование route (time/memory per step).
* inspect — runtime introspect.

Запускается как ``python -m app.tools.dsl_cli <command>`` или, при
наличии entry-point в pyproject, как ``gdi dsl <command>``.
"""

from src.backend.tools.dsl_cli.lint import lint_file

__all__ = ("lint_file",)
