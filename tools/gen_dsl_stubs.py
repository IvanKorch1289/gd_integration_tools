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
    - Если annotation не разрешается — fallback на ``Any``;
    - 100% coverage public methods требование DoD §S14.9.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_NAME = "dsl_stub.pyi.j2"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

_DEFAULT_TARGETS = (
    ("src.backend.dsl.builders.base", "RouteBuilder", _PROJECT_ROOT / "src/backend/dsl/builders/base.pyi"),
    ("src.backend.dsl.workflow.builder", "WorkflowBuilder", _PROJECT_ROOT / "src/backend/dsl/workflow/builder.pyi"),
)

_logger = logging.getLogger("tools.gen_dsl_stubs")


@dataclass(slots=True)
class StubMethod:
    """Описание одного public-метода для шаблона."""

    name: str
    signature: str
    return_type: str
    docstring: str


def _resolve_annotation(annotation: Any) -> str:
    """Безопасный перевод annotation в строку (для шаблона).

    Best-effort fallback на ``str(annotation)`` — не использует
    ``typing.get_type_hints``/``get_origin``, поэтому качество stub'ов
    для PEP-695 type-parameters и ``TypeAlias`` ограничено. См.
    ``.claude/KNOWN_ISSUES.md`` (S14 carryover F-5).
    """
    if annotation is inspect.Parameter.empty:
        return "Any"
    if annotation is None or annotation is type(None):
        return "None"
    if isinstance(annotation, str):
        return annotation
    return str(annotation)


def _format_param(p: inspect.Parameter) -> str:
    """Воспроизводит параметр в формате pyi-сигнатуры."""
    kind = p.kind
    name = p.name
    if kind == inspect.Parameter.VAR_POSITIONAL:
        return f"*{name}: {_resolve_annotation(p.annotation)}"
    if kind == inspect.Parameter.VAR_KEYWORD:
        return f"**{name}: {_resolve_annotation(p.annotation)}"
    annotation = _resolve_annotation(p.annotation)
    if p.default is not inspect.Parameter.empty:
        return f"{name}: {annotation} = ..."
    return f"{name}: {annotation}"


def _build_signature(method: Any) -> tuple[str, str]:
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
        parts.append(_format_param(p))
    return_type = _resolve_annotation(sig.return_annotation)
    return f"({', '.join(parts)})", return_type


def _collect_public_methods(cls: type) -> list[StubMethod]:
    """Все public-callable методы класса (без приватных и dunders)."""
    methods: list[StubMethod] = []
    for name in sorted(dir(cls)):
        if name.startswith("_"):
            continue
        attr = inspect.getattr_static(cls, name, None)
        if attr is None or not callable(attr):
            continue
        if isinstance(attr, (staticmethod, classmethod)):
            target = attr.__func__
        else:
            target = attr
        if not inspect.isfunction(target) and not inspect.ismethod(target):
            continue
        signature, return_type = _build_signature(target)
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


def render_stub(module_name: str, class_name: str, methods: list[StubMethod]) -> str:
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
    )


def generate_stub(module_name: str, class_name: str, output_path: Path) -> str:
    """Полный pipeline для одного target'а."""
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    methods = _collect_public_methods(cls)
    return render_stub(module_name, class_name, methods)


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
            existing = output_path.read_text(encoding="utf-8") if output_path.is_file() else ""
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
