"""Sprint 14 K3 W2 — генератор ``.pyi`` stub'ов для RouteBuilder/WorkflowBuilder.

Назначение:
    Runtime-introspection всех public-методов RouteBuilder и
    WorkflowBuilder + рендер ``.pyi`` файла через Jinja2. IDE-аль
    autocomplete + mypy получают полный type-coverage без вручную
    поддерживаемых stub'ов.

Использование:
    python -m tools.gen_dsl_stubs
    python -m tools.gen_dsl_stubs --check  # CI gate — нет ли drift

Output:
    src/backend/dsl/builders/base.pyi
    src/backend/dsl/workflow/builder.pyi

Принципы:
    - Берём ``inspect.signature`` + ``typing.get_type_hints`` для каждого
      public-метода (без префикса ``_``);
    - Собираем все импорты из исходного модуля, резолвим типы через namespace модуля;
    - Генерируем ``from x import Y`` для всех внешних типов;
    - Короткие имена в stub'ах через replacement table (fq_to_short).
    - 100% coverage public methods требование DoD §S14.9.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import logging
import re
import sys
import types
import typing
from collections.abc import Callable as ABCCallable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ForwardRef, get_args, get_origin

from jinja2 import Environment, FileSystemLoader, StrictUndefined

if TYPE_CHECKING:
    from jinja2 import Template

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_NAME = "dsl_stub.pyi.j2"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_TARGETS = (
    (
        "src.backend.dsl.builders.base",
        "RouteBuilder",
        _PROJECT_ROOT / "src/backend/dsl/builders/base.pyi",
    ),
    (
        "src.backend.dsl.workflow.builder",
        "WorkflowBuilder",
        _PROJECT_ROOT / "src/backend/dsl/workflow/builder.pyi",
    ),
)

_logger = logging.getLogger("tools.gen_dsl_stubs")


# -------------------------------------------------------------------
# Global state: FQ → short-name mapping (populated per-module)
# -------------------------------------------------------------------
_fq_to_short: dict[str, str] = {}


# Types that are always available from `typing` and don't need explicit import
_TYPING_REEXPORTS: frozenset[str] = frozenset(
    {
        "Any",
        "Callable",
        "Optional",
        "Union",
        "List",
        "Dict",
        "Set",
        "Tuple",
        "Type",
        "Iterable",
        "Iterator",
        "Sequence",
        "Mapping",
        "MutableMapping",
        "Awaitable",
        "Coroutine",
        "ContextManager",
        "AsyncIterator",
        "AsyncIterable",
        "AsyncContextManager",
        "AsyncGenerator",
    }
)


# -------------------------------------------------------------------
# Dataclasses
# -------------------------------------------------------------------
@dataclass(slots=True)
class StubMethod:
    """Описание одного public-метода для шаблона."""

    name: str
    signature: str
    return_type: str
    docstring: str


# -------------------------------------------------------------------
# Forward reference resolution helpers
# -------------------------------------------------------------------
def _get_module_namespace(module_name: str) -> dict[str, Any]:
    """Load module's full namespace: globals + imported names.

    Also parses ``if TYPE_CHECKING:`` blocks in the source file and injects
    those imports into the namespace (with ``TYPE_CHECKING = True``) so that
    ``get_type_hints`` can resolve ForwardRef annotations that use them.
    """
    import importlib
    import pathlib

    mod = importlib.import_module(module_name)
    ns = dict(vars(mod))
    # Remove the module object itself to avoid self-references
    ns.pop(module_name.split(".")[-1], None)
    ns.pop("__builtins__", None)

    # Inject TYPE_CHECKING = True so that get_type_hints can resolve
    # imports inside `if TYPE_CHECKING:` blocks (common pattern for avoiding
    # circular imports in type annotations).
    ns["TYPE_CHECKING"] = True

    # Resolve string placeholders from TYPE_CHECKING blocks to actual type objects.
    # e.g. ns['BranchSpec'] = 'BranchSpec' (string) → actual BranchSpec class.
    # We do this by scanning the source file for `from X import Y` inside
    # `if TYPE_CHECKING:` blocks and trying to import them.
    try:
        src_path = getattr(mod, "__file__", None)
        if src_path and src_path.endswith(".py"):
            import re

            src = pathlib.Path(src_path).read_text()
            lines = src.splitlines()
            i = 0
            while i < len(lines):
                stripped = lines[i].strip()
                if stripped.startswith("if TYPE_CHECKING"):
                    # Found the block, collect all indented lines that follow
                    i += 1
                    while i < len(lines):
                        line = lines[i]
                        stripped_i = line.strip()
                        # Unindented line = block ended
                        if stripped_i and not line[0].isspace():
                            break
                        # Inside the block — look for `from X import Y, Z` lines
                        m = re.match(r"from\s+(\S+)\s+import\s+(.+)", stripped_i)
                        if m:
                            from_module, imports_str = m.group(1), m.group(2)
                            # Handle parentheses: `from x import (Y, Z)` or `from x import Y, Z)`
                            imports_str = imports_str.strip().strip("()")
                            for imp in re.split(r",\s*", imports_str):
                                imp = imp.strip().split(" as ")[0].strip()
                                if imp and imp.isidentifier():
                                    try:
                                        ns[imp] = importlib.import_module(
                                            from_module
                                        ).__dict__[imp]
                                    except (KeyError, ImportError):
                                        pass
                        i += 1
                    break  # Only handle first TYPE_CHECKING block
                i += 1
    except Exception:
        pass

    ns.pop("TYPE_CHECKING", None)
    return ns


# -------------------------------------------------------------------
# Annotation → string formatting
# -------------------------------------------------------------------
def _shorten_annotation(annotation_str: str) -> str:
    """Replace FQ type references with short names.

    Handles:
    - 'src.backend.X.ClassName' → 'ClassName'
    - 'list[src.backend.X.ClassName]' → 'list[ClassName]'
    - 'src.backend.X.Exchange[Any]' → 'Exchange[Any]'
    """
    if not _fq_to_short:
        return annotation_str

    result = annotation_str

    # Replace all occurrences of fq_type[optional_generic] with short_name[optional_generic]
    # Pattern breakdown:
    #   module_path.ClassName[generic]   or   module_path.ClassName
    # Module path: a.b.c (lowercase segments)
    # Class name: starts with uppercase, may have [generic] suffix
    def replace_fq_generic(m: re.Match) -> str:
        module_prefix = m.group(1)  # e.g. 'src.backend.dsl.engine.exchange'
        rest = m.group(2)  # e.g. 'Exchange[Any]' or 'BaseProcessor'
        # Strip any generic suffix to get the bare class name
        class_name = re.sub(r"\[.*\]$", "", rest)
        generic_suffix = rest[len(class_name) :]  # '' or '[...]'
        short = _fq_to_short.get(f"{module_prefix}.{class_name}", class_name)
        return f"{short}{generic_suffix}"

    result = re.sub(
        # group(1): module prefix  group(2): ClassName[generic]
        r"((?:[a-z][a-zA-Z0-9_]*(?:\.[a-z][a-zA-Z0-9_]*)*)\.([A-Z][a-zA-Z0-9_]*(?:\[[^\]]+\])?))",
        replace_fq_generic,
        result,
    )
    return result


def _format_type_str(annotation: Any) -> str:
    """Format a resolved type annotation as a clean type expression string.

    Handles:
    - GenericAlias (list[X], dict[K,V]) → 'list[X]'
    - types.UnionType (X | Y) → 'X | Y'
    - typing generics (Callable[[X], Y]) → 'Callable[[X], Y]'
    - regular classes → short qualname
    - typing.ClassVar, typing.Final → short name
    """
    if annotation is None or annotation is type(None):
        return "None"
    if annotation is inspect.Parameter.empty:
        return "Any"

    origin = get_origin(annotation)
    args = get_args(annotation)

    # typing generics (list[int], Callable[[X], Y], Union[X, Y], etc.)
    if origin is not None:
        qualname = getattr(origin, "__qualname__", None) or str(origin)

        if qualname == "Callable" and args:
            inner = ", ".join(_format_type_str(a) for a in args[0]) if args[0] else ""
            ret = _format_type_str(args[1]) if len(args) > 1 else "Any"
            return f"Callable[[{inner}], {ret}]"

        # GenericAlias: list[int], dict[str, Any], etc.
        if args:
            if isinstance(args, tuple):
                inner = ", ".join(_format_type_str(a) for a in args)
            else:
                inner = _format_type_str(args)
            qualname = _shorten_annotation(qualname)
            return f"{qualname}[{inner}]"

        qualname = _shorten_annotation(qualname)
        return qualname

    # UnionType (int | str in Python 3.10+)
    if isinstance(annotation, types.UnionType):
        return " | ".join(_format_type_str(a) for a in annotation.__args__)

    # Regular class or typing alias
    qualname = getattr(annotation, "__qualname__", None)
    module = getattr(annotation, "__module__", None)

    if qualname and module:
        return _shorten_annotation(qualname)

    # Fallback
    result = repr(annotation)
    if result.startswith("<class ") and result.endswith(">"):
        return result[8:-1].strip("'\"")
    if result.startswith("<"):
        return str(annotation)
    return result


def _resolve_annotation(
    annotation: Any, module_ns: dict[str, Any] | None = None
) -> str:
    """Безопасный перевод annotation в строку (для шаблона).

    Best-effort: пытаемся зарезолвить ForwardRef и строковые аннотации
    через namespace модуля, затем форматируем через _format_type_str.
    """
    if annotation is inspect.Parameter.empty:
        return "Any"
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, str):
        if module_ns:
            try:
                resolved = eval(annotation, module_ns)  # noqa: S307 — controlled namespace
                if isinstance(resolved, str):
                    resolved = resolved.strip("'\"")
                return _format_type_str(resolved)
            except Exception:
                pass
        return annotation
    if isinstance(annotation, ForwardRef):
        if module_ns:
            try:
                resolved = annotation.evaluate(  # type: ignore[reportCallIssue]
                    globalns=module_ns, localns=module_ns
                )
                return _format_type_str(resolved)
            except Exception:
                pass
        return annotation.__forward_arg__
    return _format_type_str(annotation)


# -------------------------------------------------------------------
# Signature building
# -------------------------------------------------------------------
def _format_param(p: inspect.Parameter, module_ns: dict[str, Any] | None = None) -> str:
    """Воспроизводит параметр в формате pyi-сигнатуры."""
    kind = p.kind
    name = p.name
    if kind == inspect.Parameter.VAR_POSITIONAL:
        return f"*{name}: {_resolve_annotation(p.annotation, module_ns)}"
    if kind == inspect.Parameter.VAR_KEYWORD:
        return f"**{name}: {_resolve_annotation(p.annotation, module_ns)}"
    annotation = _resolve_annotation(p.annotation, module_ns)
    if p.default is not inspect.Parameter.empty:
        return f"{name}: {annotation} = ..."
    return f"{name}: {annotation}"


def _build_signature(
    method: Any, module_ns: dict[str, Any] | None = None
) -> tuple[str, str]:
    """Вернуть ``(formatted_signature, return_type)``."""
    try:
        sig = inspect.signature(method)
    except (ValueError, TypeError):
        return "(*args: Any, **kwargs: Any)", "Any"
    parts: list[str] = []
    has_self = False
    for p in sig.parameters.values():
        if p.name == "self" and not has_self:
            parts.append("self")
            has_self = True
            continue
        parts.append(_format_param(p, module_ns))
    return_type = _resolve_annotation(sig.return_annotation, module_ns)
    return f"({', '.join(parts)})", return_type


# -------------------------------------------------------------------
# Method collection
# -------------------------------------------------------------------
def _collect_public_methods(
    cls: type, module_ns: dict[str, Any] | None = None
) -> list[StubMethod]:
    """Все public-callable методы класса (без приватных и dunders)."""
    methods: list[StubMethod] = []
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        attr = inspect.getattr_static(cls, name, None)
        if attr is None:
            continue
        if isinstance(attr, (staticmethod, classmethod)):
            target = attr.__func__
        else:
            target = attr
        if not callable(target):
            continue
        if not inspect.isfunction(target) and not inspect.ismethod(target):
            continue
        signature, return_type = _build_signature(target, module_ns)
        docstring = (inspect.getdoc(target) or "").strip().split("\n", 1)[0]
        methods.append(
            StubMethod(
                name=name,
                signature=signature,
                return_type=return_type or "Any",
                docstring=docstring or f"Auto-stub for {cls.__name__}.{name}.",
            )
        )
    return methods


# -------------------------------------------------------------------
# Import collection
# -------------------------------------------------------------------
def _format_import_line(fq_name: str) -> str | None:
    """Convert fq_name like 'src.backend.dsl.engine.processors.base.BaseProcessor'
    → 'from src.backend.dsl.engine.processors.base import BaseProcessor'.

    Returns None for:
      - names starting with __same_module__: (handled by _collect_all_imports)
      - typing re-exports (already available via `from typing import ...`)
    """
    if fq_name.startswith("__same_module__:"):
        return None
    parts = fq_name.rsplit(".", 1)
    if len(parts) != 2:
        return None  # no dot → can't form 'from x import y'
    module, name = parts
    # Skip typing re-exports
    if name in _TYPING_REEXPORTS and module.startswith("typing"):
        return None
    return f"from {module} import {name}"


def _build_method_imports(
    cls: type, method_name: str, module_ns: dict[str, Any] | None = None
) -> set[str]:
    """Extract all FQ type names referenced in a method's annotations.

    Uses get_type_hints to resolve forward references before extracting names.
    Resolves types against the method's *defining class* module namespace,
    not the target class's namespace (important for inherited mixin methods).
    """
    names: set[str] = set()
    attr = inspect.getattr_static(cls, method_name, None)
    if attr is None:
        return names
    if isinstance(attr, (staticmethod, classmethod)):
        target = attr.__func__
    else:
        target = attr
    if not inspect.isfunction(target) and not inspect.ismethod(target):
        return names

    # Find the class that actually defines this method (for inherited mixin methods)
    defining_class = None
    for parent in cls.__mro__:
        if method_name in parent.__dict__:
            defining_class = parent
            break

    # Build namespace: start with defining class's module, then overlay cls's module
    # This ensures RouteBuilder (from base.py) is available when resolving mixin methods
    ns_to_use = module_ns
    if defining_class and defining_class is not cls:
        defining_module = getattr(defining_class, "__module__", None)
        if defining_module:
            mixin_ns = _get_module_namespace(defining_module)
            # Overlay: mixin_ns values take precedence (mixin types), but cls's
            # types (like RouteBuilder) are also available
            merged_ns = dict(module_ns) if module_ns else {}
            merged_ns.update(mixin_ns)
            ns_to_use = merged_ns

    # Try to get resolved hints
    if ns_to_use:
        try:
            hints = typing.get_type_hints(
                target, include_extras=True, globalns=ns_to_use, localns=ns_to_use
            )
            for ann in hints.values():
                names.update(_extract_fq_names_from_annotation(ann))
            return names
        except Exception:
            pass

    # Fallback: use raw string annotations
    for ann in getattr(target, "__annotations__", {}).values():
        names.update(_extract_fq_names_from_annotation(ann))
    return names


def _extract_fq_names_from_annotation(ann: Any) -> set[str]:
    """Recursively collect FQ type names from an annotation tree.

    Adds the bare class FQ (e.g. 'src.m.Exchange') to the names set, so that
    ``_fq_to_short`` mapping can shorten it regardless of generic arguments.
    """
    names: set[str] = set()
    if isinstance(ann, str):
        names.update(_fq_names_from_string(ann))
        return names
    if isinstance(ann, ForwardRef):
        names.update(_fq_names_from_string(ann.__forward_arg__))
        return names

    # Generic type: list[X], Callable[[X], Y], Union[X, Y], etc.
    origin = get_origin(ann)
    args = get_args(ann)

    if origin is not None:
        # Callable special handling
        qualname = getattr(origin, "__qualname__", None) or str(origin)
        if qualname == "Callable" and args:
            # args[0]: list of param types (or single type in some Python versions)
            param_types = args[0]
            if not isinstance(param_types, (list, tuple)):
                param_types = [param_types]
            for p in param_types:
                names.update(_extract_fq_names_from_annotation(p))
            # return type
            if len(args) > 1:
                names.update(_extract_fq_names_from_annotation(args[1]))
            return names

        # Add the bare origin type (e.g. 'list', 'dict', 'Union')
        origin_module = getattr(origin, "__module__", None)
        origin_qualname = getattr(origin, "__qualname__", None)
        if (
            origin_module
            and origin_qualname
            and origin_qualname not in _TYPING_REEXPORTS
            and origin_module
            not in ("builtins", "typing", "collections.abc", "collections")
        ):
            names.add(f"{origin_module}.{origin_qualname}")

        # Recurse into generic arguments
        for arg in args if isinstance(args, (list, tuple)) else [args]:
            names.update(_extract_fq_names_from_annotation(arg))
        return names

    # UnionType (int | str)
    if isinstance(ann, types.UnionType):
        for a in ann.__args__:
            names.update(_extract_fq_names_from_annotation(a))
        return names

    # Regular class (including Pydantic models)
    if isinstance(ann, type) and not isinstance(ann, types.UnionType):
        module = getattr(ann, "__module__", None)
        qualname = getattr(ann, "__qualname__", None)
        if qualname and module and qualname not in _TYPING_REEXPORTS:
            if module not in ("builtins", "typing", "collections.abc", "collections"):
                # Strip generic suffix for the FQ key
                bare = re.sub(r"\[.*\]$", "", f"{module}.{qualname}")
                names.add(bare)
        return names

    # Fallback: try string representation
    result = repr(ann)
    if "." in result and not result.startswith("<"):
        names.update(_fq_names_from_string(result))
    return names


def _fq_names_from_string(s: str) -> set[str]:
    """Extract FQ class names from a string annotation like 'list[src.m.X] | None'.

    Also captures bare class names (e.g. 'ChoiceBranch') that appear in
    raw annotations when get_type_hints fails due to circular refs.
    These are returned with a special "same_module:" prefix so the caller
    knows to import them from the current module.
    """
    names: set[str] = set()
    # Match 'src.a.b.ClassName' or 'src.a.b.ClassName[anything]'
    for m in re.finditer(
        r"([a-z][a-zA-Z0-9_]*(?:\.[a-z][a-zA-Z0-9_]*)*)\.([A-Z][a-zA-Z0-9_]*)", s
    ):
        module, class_name = m.group(1), m.group(2)
        if module not in ("builtins", "typing", "collections.abc", "collections"):
            names.add(f"{module}.{class_name}")

    # Capture bare class names (uppercase identifier, not in typing/builtins)
    # These typically appear in raw annotations when get_type_hints fails.
    for m in re.finditer(
        r"(?<![a-zA-Z0-9_.])[A-Z][a-zA-Z0-9_]{2,}(?![a-zA-Z0-9_.\[])", s
    ):
        bare = m.group(0)
        if bare not in _TYPING_REEXPORTS:
            names.add(f"__same_module__:{bare}")

    return names


def _collect_all_imports(
    cls: type, module_name: str, module_ns: dict[str, Any] | None = None
) -> list[str]:
    """Collect all unique import lines needed for a class's public methods."""
    all_names: set[str] = set()
    for method_name in dir(cls):
        if method_name.startswith("_"):
            continue
        all_names |= _build_method_imports(cls, method_name, module_ns)

    # Separate same-module types from external imports
    same_module_types: set[str] = set()
    external_fq_names: set[str] = set()
    for name in all_names:
        if name.startswith("__same_module__:"):
            same_module_types.add(name.split(":", 1)[1])
        else:
            external_fq_names.add(name)

    import_lines = sorted({_format_import_line(n) for n in external_fq_names})
    # Remove empty/None (from _TYPING_REEXPORTS)
    import_lines = [l for l in import_lines if l]

    # Deduplicate: merge 'from x import A' and 'from x import B' → 'from x import A, B'
    module_imports: dict[str, list[str]] = {}
    for line in import_lines:
        if line.startswith("from "):
            after_from = line[5:]  # strip 'from '
            parts = after_from.split(" import ", 1)
            if len(parts) == 2:
                module_imports.setdefault(parts[0], []).append(parts[1])

    deduped: list[str] = []
    for module, names in sorted(module_imports.items()):
        deduped.append(f"from {module} import {', '.join(sorted(set(names)))}")

    # Add same-module types from the stub's own module
    # Filter out: None, builtins, and names already imported externally
    if same_module_types and module_ns:
        already_imported_fq: set[str] = set()
        for line in import_lines:
            if " import " in line:
                # 'from src.backend.dsl.engine.exchange import Exchange'
                # → extract 'Exchange', 'src.backend.dsl.engine.exchange'
                parts = line.split(" import ", 1)
                imported_names = [n.strip() for n in parts[1].split(",")]
                for n in imported_names:
                    already_imported_fq.add(n)

        same_module_filtered: list[str] = []
        same_module_fq: list[tuple[str, str]] = []  # (fq_name, short_name)
        for name in sorted(same_module_types):
            if name in ("None", "True", "False") or name in already_imported_fq:
                continue
            # Resolve: is it a class/type imported from another module?
            if name in module_ns:
                obj = module_ns[name]
                if isinstance(obj, type):
                    obj_module = getattr(obj, "__module__", None)
                    if obj_module and obj_module != module_name:
                        same_module_fq.append((f"{obj_module}.{name}", name))
                        continue
                    # Same module class
                    same_module_filtered.append(name)
                    continue

        # Add external imports for types from other modules
        # same_module_fq entries are (fq_name, short_name) where fq_name is 'module.ClassName'
        if same_module_fq:
            for fq, short in sorted(set(same_module_fq)):
                deduped.append(f"from {fq.rsplit('.', 1)[0]} import {short}")

        if same_module_filtered:
            deduped.append(
                f"from {module_name} import {', '.join(sorted(set(same_module_filtered)))}"
            )

    return deduped


# -------------------------------------------------------------------
# Rendering
# -------------------------------------------------------------------
def render_stub(
    module_name: str,
    class_name: str,
    methods: list[StubMethod],
    extra_imports: list[str],
) -> str:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 — pyi-output не HTML
        keep_trailing_newline=True,
    )
    template = env.get_template(_TEMPLATE_NAME)
    return template.render(
        module_name=module_name,
        class_name=class_name,
        methods=methods,
        extra_imports=extra_imports,
    )


def generate_stub(module_name: str, class_name: str, output_path: Path) -> str:
    """Полный pipeline для одного target'а."""
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    module_ns = _get_module_namespace(module_name)
    methods = _collect_public_methods(cls, module_ns)
    extra_imports = _collect_all_imports(cls, module_name, module_ns)

    # Remove self-import: if the target class itself is in extra_imports as a
    # "from {module_name} import {class_name}", drop it — the stub IS the definition.
    self_import = f"from {module_name} import {class_name}"
    if self_import in extra_imports:
        extra_imports.remove(self_import)

    # Build fq_to_short mapping before rendering so annotations are shortened
    global _fq_to_short
    _fq_to_short = _build_fq_to_short(extra_imports)

    return render_stub(module_name, class_name, methods, extra_imports)


def _build_fq_to_short(import_lines: list[str]) -> dict[str, str]:
    """Build mapping from fq_name → short-name from the import lines list."""
    mapping = {}
    for line in import_lines:
        if not line.startswith("from "):
            continue
        # 'from src.backend.dsl.engine.exchange import Exchange'
        # → module='src.backend.dsl.engine.exchange', names=['Exchange']
        after_from = line[5:]  # strip 'from '
        parts = after_from.split(" import ", 1)
        if len(parts) != 2:
            continue
        module = parts[0].strip()  # 'src.backend.dsl.engine.exchange'
        for name in parts[1].split(", "):
            name = name.strip()
            mapping[f"{module}.{name}"] = name
    return mapping


# -------------------------------------------------------------------
# CLI entrypoint
# -------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate .pyi stubs for RouteBuilder/WorkflowBuilder."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI gate — exit 1 если содержимое stub отличается от файла.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    drift_detected = False
    for module_name, class_name, output_path in _DEFAULT_TARGETS:
        content = generate_stub(module_name, class_name, output_path)
        if args.check:
            existing = (
                output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
            )
            if existing != content:
                drift_detected = True
                _logger.warning("Stub drift detected: %s", output_path)
            continue
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        _logger.info("Wrote stub %s (%d methods)", output_path, content.count("def "))
    return 1 if drift_detected else 0


if __name__ == "__main__":
    sys.exit(main())
