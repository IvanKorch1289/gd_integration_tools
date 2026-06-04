"""Sphinx-конфигурация для auto-generated API reference (S40 W4).

Sub-Sphinx-проект для автогенерации API reference из ``src/backend/dsl/``.
Запуск: ``./scripts/gen_api_docs.sh`` или ``make -C docs/api html``.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Project metadata
project = "GD Integration Tools API Reference"
author = "Internal Bank Team"
copyright = "2026, Internal Bank Team"
release = "0.0.0+unknown"  # переопределяется в _read_version()
version = "0.0.0"

# Читаем версию из pyproject.toml регекспом (без сторонних зависимостей).
import re
_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
if _PYPROJECT.is_file():
    m = re.search(r"""^version\s*=\s*["']([^"']+)["']""", _PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
    if m:
        release = m.group(1)
        version = release.split("+", 1)[0]

# Path setup: добавляем src/backend в sys.path для autodoc.
_SRC_BACKEND = Path(__file__).resolve().parents[2] / "src" / "backend"
for p in (str(_SRC_BACKEND), str(_SRC_BACKEND.parent)):
    if Path(p).is_dir() and p not in sys.path:
        sys.path.insert(0, p)

# General configuration
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosummary",
]

master_doc = "index"
templates_path = ["_templates"]
html_static_path = ["_static"]
exclude_patterns = ["_build", "_apidoc", "Thumbs.db", ".DS_Store"]
language = "ru"

rst_prolog = """
.. |project| replace:: GD Integration Tools
"""

# autodoc / napoleon
napoleon_google_docstring = True
napoleon_numpy_docstring = False
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}
# Sphinx 9+: unqualified имена типов (T вместо full.qual.name).
python_use_unqualified_type_names = True
autodoc_typehints = "description"
autodoc_typehints_format = "short"
autosummary_generate = False
nitpicky = False

suppress_warnings = ["ref.python", "ref.doc"]

# HTML — sphinx_rtd_theme (отличается от основного docs/, где pydata_sphinx_theme).
html_theme = "sphinx_rtd_theme"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
    "display_version": True,
}
html_title = f"{project} {version}"
html_short_title = "GD Integration API"
html_show_sourcelink = True

# Intersphinx: cross-refs на Python stdlib.
intersphinx_mapping = {"python": ("https://docs.python.org/3/", None)}
