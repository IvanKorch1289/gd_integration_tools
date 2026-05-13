"""Sphinx-конфигурация для gd_integration_tools.

К10 Sprint-2 Wave 5: Sphinx 9+ scaffold + Diátaxis structure.
conf.py размещён в docs/ (DOCS_SOURCE = docs) согласно Makefile.
autoapi — отдельная Wave (требует cleanup docstrings).
"""

project = "gd_integration_tools"
copyright = "2026, Internal Bank Team"
author = "Internal Bank Team"
release = "15.3.0"

# Sphinx-расширения:
# - autodoc / napoleon для Google-style docstrings (ru)
# - viewcode для ссылок на исходники
# - intersphinx для cross-references с Python stdlib
# - sphinx_copybutton для кнопки копирования кода
# - myst_parser для .md файлов рядом с .rst (Diátaxis-контент)
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_copybutton",
    "myst_parser",
]

templates_path = ["_templates"]
# Исключаем build-артефакты и системные файлы
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "**.ipynb_checkpoints"]

# Тема: pydata-sphinx-theme (уже в [dev] dependency-group, ADR совместима с 3.14)
html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]

# Русскоязычная документация согласно V15 docstring policy
language = "ru"

# Diátaxis 4-quadrant structure — главный индекс
master_doc = "index"

# MyST позволяет .md рядом с .rst (Diátaxis-контент в Markdown)
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# Napoleon: только Google-style (V15 docstring policy)
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# intersphinx: cross-reference Python stdlib
intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
}

# MyST: разрешить заголовки в Markdown для корректного toctree
myst_heading_anchors = 3

# pydata-sphinx-theme: минимальная настройка
html_theme_options = {
    "navigation_with_keys": True,
}
