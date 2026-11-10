"""CLI-обёртка линтера DSL-YAML.

Каноничная реализация переехала в ``src.backend.dsl.cli.lint`` (ADR-0434):
раньше в проекте было **три** линтера DSL-YAML (``tools/dsl_lint.py``,
``src/backend.dsl.cli.lint`` — устаревшая версия, ``src.backend.dsl.cli.linter``
— другой уровень, route.toml + *.dsl.yaml). Теперь:

* ``src.backend.dsl.cli.lint`` — единственная реализация (capability-aware,
  с JSON-выводом);
* ``tools/dsl_lint.py`` — тонкая CLI-обёртка (tools → src);
* ``src.backend.dsl.cli.linter.DSLLinter`` — отдельный линтер для
  ``route.toml``/``*.dsl.yaml`` (используется LSP-сервером и ``dsl debug``).

Запуск::

    python tools/dsl_lint.py routes/ --strict
    python tools/dsl_lint.py routes/x.dsl.yaml --json
"""

from __future__ import annotations

import sys

from src.backend.dsl.cli.lint import Finding, lint_file, lint_paths, lint_yaml, main

__all__ = ("Finding", "lint_file", "lint_paths", "lint_yaml", "main")

if __name__ == "__main__":
    sys.exit(main())
