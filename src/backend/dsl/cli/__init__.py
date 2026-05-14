"""gdi dsl <command> — CLI-инструменты для DSL (E2).

Commands:
* lint — проверка YAML DSL-файла (legacy ``lint``).
* linter — расширенный validator route.toml + *.dsl.yaml
  (K3 S6 [wave:s6/k3-dsl-linter-lsp]).
* lsp_server — Language Server Protocol через pygls.
* repl — интерактивная отладка route.
* diff — сравнение v1/v2 route.
* profile — профилирование route (time/memory per step).
* inspect — runtime introspect.

Запускается как ``python -m src.backend.dsl.cli <command>`` или, при
наличии entry-point в pyproject, как ``gdi dsl <command>``.
"""

from src.backend.dsl.cli.lint import lint_file
from src.backend.dsl.cli.linter import DSLLinter, LintIssue, lint_path

__all__ = (
    "lint_file",
    "DSLLinter",
    "LintIssue",
    "lint_path",
)
