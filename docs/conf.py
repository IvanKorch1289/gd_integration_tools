"""Sphinx-конфигурация для gd_integration_tools.

К10 Sprint-2 Wave 5: Sphinx 9+ scaffold + Diátaxis structure.
conf.py размещён в docs/ (DOCS_SOURCE = docs) согласно Makefile.
S34 W1: sphinx-autoapi добавлен (Narrow scope: core/, dsl/engine/, core/interfaces/).
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
    # S34 W1: auto-api для core/ + dsl/engine/ + core/interfaces/
    "autoapi.extension",
]

# K1 Sprint 8 [wave:s8/k1-sphinx-multiversion]: multi-version build.
# Подключаем sphinx-multiversion опционально: при отсутствии extras
# обычный single-version build не падает (dev без `pip install -e '.[docs]'`).
try:  # pragma: no cover — import-time опция
    import sphinx_multiversion  # noqa: F401

    extensions.append("sphinx_multiversion")
except ImportError:
    pass

# Whitelisting: master + долгоживущие release-ветки + tags v0.1+.
smv_branch_whitelist = r"^(master|release/.*)$"
smv_tag_whitelist = r"^v\d+\.\d+(\.\d+)?$"
smv_remote_whitelist = None  # build только из локальных refs (CI checkout-all)
smv_released_pattern = r"^tags/v.*$"
smv_outputdir_format = "{ref.name}"

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

# S34 W1: autoapi configuration (narrow scope: core/ + dsl/engine/ + core/interfaces/)
autoapi_type = "python"
autoapi_dirs = [
    "../src/backend/core",
    "../src/backend/dsl/engine",
    "../src/backend/core/interfaces",
]
autoapi_ignore = [
    "*/__pycache__/*",
    "*/tests/*",
    "*/migrations/*",
    "*/__init__.py",  # skip top-level init files unless they have docs
    "*/.venv/*",
]
autoapi_member_order = "bysource"
autoapi_python_use_imodule_names = True

# S34 W1: Suppress expected warnings for narrow-scope autoapi.
# Import resolution warnings are expected because we only document core/dsl/engine/interfaces
# but some modules import from infrastructure/ which is outside scope.
suppress_warnings = [
    "autoapi.python_import_resolution",
]
