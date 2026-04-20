"""Sphinx configuration for gd_integration_tools.

Собирает документацию из:

* ``docs/*.md`` — через ``myst-parser``;
* docstrings в ``src/`` — через ``sphinx-autoapi``.

Билд::

    cd docs && make html
    # → docs/_build/html/index.html
"""

from __future__ import annotations

import sys
from pathlib import Path

# Делаем пакет app импортируемым для autoapi.
_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_root / "src"))

# ──────────────────── Project info ────────────────────

project = "gd_integration_tools"
author = "Korch Ivan"
release = "0.1.0"
language = "ru"

# ──────────────────── General config ────────────────────

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "autoapi.extension",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "**/__pycache__"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# ──────────────────── MyST ────────────────────

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
    "fieldlist",
    "attrs_inline",
]

# ──────────────────── AutoAPI ────────────────────

autoapi_type = "python"
autoapi_dirs = [str(_root / "src")]
autoapi_root = "api"
autoapi_keep_files = False
autoapi_add_toctree_entry = True
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
    "special-members",
]

# ──────────────────── HTML output ────────────────────

html_theme = "alabaster"
html_title = "gd_integration_tools"
html_static_path = ["_static"]

# ──────────────────── Intersphinx ────────────────────

intersphinx_mapping = {
    "python": ("https://docs.python.org/3.14/", None),
    "fastapi": ("https://fastapi.tiangolo.com/", None),
    "sqlalchemy": ("https://docs.sqlalchemy.org/en/20/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}
