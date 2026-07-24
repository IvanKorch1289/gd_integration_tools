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

# Cycle 29 (M9): autodoc_mock_imports для protobuf auto-generated модулей.
# autoapi следует по импортам из documented scope и при попытке резолвить
# ``auto.files_pb2.DESCRIPTOR`` падает с KeyError (DESCRIPTOR — runtime attr,
# не AST attribute, autoapi его не видит). Mock-импорт делает модули
# "виртуальными" — autoapi видит имя, но не пытается парсить тело.
autodoc_mock_imports = [
    "grpc",
    "google.protobuf",
    "google.protobuf.descriptor",
    "src.backend.entrypoints.grpc.protobuf",
    "src.backend.entrypoints.grpc.protobuf.auto",
    "src.backend.entrypoints.grpc.protobuf.files_pb2",
    "src.backend.entrypoints.grpc.protobuf.files_pb2_grpc",
    "src.backend.entrypoints.grpc.protobuf.orders_pb2",
    "src.backend.entrypoints.grpc.protobuf.orders_pb2_grpc",
    "src.backend.entrypoints.grpc.protobuf.orderkinds_pb2",
    "src.backend.entrypoints.grpc.protobuf.orderkinds_pb2_grpc",
    "src.backend.entrypoints.grpc.protobuf.users_pb2",
    "src.backend.entrypoints.grpc.protobuf.users_pb2_grpc",
    "src.backend.entrypoints.grpc.protobuf.invoker_pb2",
    "src.backend.entrypoints.grpc.protobuf.invoker_pb2_grpc",
]


# Cycle 29 (M9): workaround для autoapi KeyError на protobuf DESCRIPTOR.
# autodoc_mock_imports не помогает — autoapi имеет собственный discovery,
# который игнорирует autodoc-моки. Патчим ``AutoapiSummary.get_items``
# чтобы пропускал KeyError при lookup runtime-attrs (DESCRIPTOR, _descriptor,
# __doc__ extensions и т.п.). Это runtime-only fix в conf.py, не меняет
# исходный код autoapi.
def _patch_autoapi_directive_get_items() -> None:
    """Skip KeyError для runtime-only attrs в autoapi get_items lookup."""
    try:
        from autoapi.directives import AutoapiSummary
    except ImportError:
        return

    _original_get_items = AutoapiSummary.get_items

    def _safe_get_items(  # type: ignore[no-untyped-def]
        self, names
    ) -> list:
        """get_items с защитой от KeyError на runtime-only attrs."""
        items: list = []
        for name in names:
            try:
                obj = self.env.autoapi_all_objects[name]
            except KeyError:
                # DESCRIPTOR / _builder / __getstate__ — runtime attrs,
                # не AST-detected. Skip без прерывания build.
                continue
            # Delegate the rest к оригинальному loop'у через вызов с одним name
            items.extend(_original_get_items(self, [name]))
        return items

    AutoapiSummary.get_items = _safe_get_items


_patch_autoapi_directive_get_items()

# Тема: pydata-sphinx-theme (уже в [dev] dependency-group, ADR совместима с 3.14)
html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]

# Русскоязычная документация согласно V15 docstring policy
language = "ru"

# Diátaxis 4-quadrant structure — главный индекс
master_doc = "index"

# MyST позволяет .md рядом с .rst (Diátaxis-контент в Markdown)
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}

# Napoleon: только Google-style (V15 docstring policy)
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# intersphinx: cross-reference Python stdlib
intersphinx_mapping = {"python": ("https://docs.python.org/3/", None)}

# MyST: разрешить заголовки в Markdown для корректного toctree
myst_heading_anchors = 3

# pydata-sphinx-theme: минимальная настройка
html_theme_options = {"navigation_with_keys": True}

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
    # Cycle 29 (M9): protobuf auto-generated модули (pb2/pb2_grpc) содержат
    # ``DESCRIPTOR`` attribute, который autoapi пытается резолвить через
    # ``all_objects`` lookup → KeyError ломает весь build. Exclude полностью —
    # protobuf docstring'и бесполезны (генерируются из .proto, не из Python).
    "*_pb2.py",
    "*_pb2_grpc.py",
]
autoapi_member_order = "bysource"
autoapi_python_use_imodule_names = True

# S34 W1: Suppress expected warnings for narrow-scope autoapi.
# Import resolution warnings: we document core/dsl/engine/interfaces but some modules
# import from infrastructure/ which is outside scope.
# ref.python: duplicate cross-ref targets (type/AuditCallback/RetryPolicy) - unavoidable.
# ref.doc: ADR cross-references to non-existent documents.
# KNOWN LIMITATION: 418 "duplicate object description" warnings from autoapi-generated
# RST for protobuf classes (ProtoField/ProtoMessage/ProtoFile etc.) cannot be suppressed
# via Sphinx suppress_warnings — caused by autoapi documenting same objects from
# multiple locations. Does not affect build or published output.
suppress_warnings = [
    "autoapi.python_import_resolution",
    "docutils",
    "myst.directive_unknown",
    "myst.xref_unknown",
    "toc.not_included",
    "ref.python",
    "ref.doc",
]
