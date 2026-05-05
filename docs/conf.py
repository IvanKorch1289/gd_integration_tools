"""Sphinx configuration for gd_integration_tools.

Источники:

* ``docs/source/*.md`` — корневой toctree (Wave 10.3);
* ``docs/{tutorials,runbooks,adr,phases,reference}/*.md`` — через myst;
* docstrings в ``src/{core,dsl,services,schemas}/`` — через
  ``sphinx-autoapi`` (узкий scope для скорости CI).

Билд:
    cd docs && make html  # → docs/_build/html/index.html

Wave 10.3:
    * pydata-sphinx-theme;
    * autoapi_dirs ограничен 4 корневыми пакетами;
    * nitpicky=True — CI -W блокирует warnings.
"""

from __future__ import annotations

import sys
from pathlib import Path

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
    "sphinx_design",
    "autoapi.extension",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "build", "**/__pycache__", ".cache"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

master_doc = "source/index"
nitpicky = True

# ──────────────────── MyST ────────────────────

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "tasklist",
    "fieldlist",
    "attrs_inline",
]

# ──────────────────── AutoAPI (Wave 10.3 — узкий scope) ────────────────────

autoapi_type = "python"
autoapi_dirs = [
    str(_root / "src" / "backend" / "core"),
    str(_root / "src" / "backend" / "dsl"),
    str(_root / "src" / "backend" / "services"),
    str(_root / "src" / "backend" / "schemas"),
]
autoapi_root = "api"
autoapi_keep_files = False
autoapi_add_toctree_entry = True
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
]

# ──────────────────── HTML output ────────────────────

html_theme = "pydata_sphinx_theme"
html_title = "gd_integration_tools"
html_static_path = ["_static"]

# ──────────────────── Intersphinx ────────────────────

intersphinx_mapping = {
    "python": ("https://docs.python.org/3.14/", None),
    "fastapi": ("https://fastapi.tiangolo.com/", None),
    "sqlalchemy": ("https://docs.sqlalchemy.org/en/20/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}
