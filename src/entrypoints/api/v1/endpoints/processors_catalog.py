"""DX-3: Processor introspection API.

Возвращает JSON-каталог всех DSL-процессоров с signatures и docstrings.
Используется:
- Streamlit UI для auto-complete
- AI агентами для route-building
- Developer docs

Endpoint: GET /api/v1/dsl/processors/catalog
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

__all__ = ("router",)

router = APIRouter(prefix="/dsl", tags=["DSL Catalog"])


def _collect_processors() -> list[dict[str, Any]]:
    """Scan all DSL processor modules + collect metadata."""
    from src.dsl.engine.processors import base

    results: list[dict[str, Any]] = []
    visited: set[str] = set()

    module_paths = [
        "src.dsl.engine.processors.core",
        "src.dsl.engine.processors.control_flow",
        "src.dsl.engine.processors.eip.routing",
        "src.dsl.engine.processors.eip.transformation",
        "src.dsl.engine.processors.eip.resilience",
        "src.dsl.engine.processors.eip.flow_control",
        "src.dsl.engine.processors.eip.idempotency",
        "src.dsl.engine.processors.eip.sequencing",
        "src.dsl.engine.processors.components",
        "src.dsl.engine.processors.converters",
        "src.dsl.engine.processors.patterns",
        "src.dsl.engine.processors.scraping",
        "src.dsl.engine.processors.ai",
        "src.dsl.engine.processors.rpa",
        "src.dsl.engine.processors.web",
        "src.dsl.engine.processors.external",
        "src.dsl.engine.processors.integration",
        "src.dsl.engine.processors.export",
        "src.dsl.engine.processors.dq_check",
    ]

    import importlib

    for path in module_paths:
        try:
            mod = importlib.import_module(path)
        except ImportError:
            continue

        category = path.rsplit(".", 1)[-1]

        for name in dir(mod):
            if not name.endswith("Processor") or name in visited:
                continue
            obj = getattr(mod, name, None)
            if not inspect.isclass(obj):
                continue
            if not issubclass(obj, base.BaseProcessor):
                continue
            if obj is base.BaseProcessor or obj is base.CallableProcessor:
                continue
            visited.add(name)

            try:
                init_sig = inspect.signature(obj.__init__)
                params = [
                    {
                        "name": p.name,
                        "kind": p.kind.name,
                        "default": (
                            None
                            if p.default is inspect.Parameter.empty
                            else repr(p.default)
                        ),
                        "annotation": (
                            None
                            if p.annotation is inspect.Parameter.empty
                            else str(p.annotation)
                        ),
                    }
                    for p in init_sig.parameters.values()
                    if p.name not in ("self", "name")
                ]
            except ValueError, TypeError:
                params = []

            doc = (inspect.getdoc(obj) or "").strip()
            short_doc = doc.split("\n", 1)[0][:200] if doc else ""

            results.append(
                {
                    "name": name,
                    "category": category,
                    "module": path,
                    "description": short_doc,
                    "docstring": doc,
                    "parameters": params,
                }
            )

    return sorted(results, key=lambda x: (x["category"], x["name"]))


def _collect_builder_methods() -> list[dict[str, Any]]:
    """Scan RouteBuilder methods + collect signatures."""
    from src.dsl.builder import RouteBuilder

    results: list[dict[str, Any]] = []

    for name in dir(RouteBuilder):
        if name.startswith("_"):
            continue
        method = getattr(RouteBuilder, name, None)
        if not callable(method):
            continue

        try:
            sig = inspect.signature(method)
            params = [
                {
                    "name": p.name,
                    "default": (
                        None
                        if p.default is inspect.Parameter.empty
                        else repr(p.default)
                    ),
                    "annotation": (
                        None
                        if p.annotation is inspect.Parameter.empty
                        else str(p.annotation)
                    ),
                }
                for p in sig.parameters.values()
                if p.name != "self"
            ]
        except ValueError, TypeError:
            params = []

        doc = (inspect.getdoc(method) or "").strip()
        results.append(
            {
                "name": name,
                "description": doc.split("\n", 1)[0][:200] if doc else "",
                "parameters": params,
            }
        )

    return sorted(results, key=lambda x: x["name"])


@router.get("/processors/catalog", summary="DSL processor catalog (introspection)")
async def processors_catalog() -> JSONResponse:
    """Возвращает полный каталог DSL-процессоров с metadata.

    Response:
    {
        "processors": [{name, category, module, description, docstring, parameters}, ...],
        "builder_methods": [{name, description, parameters}, ...],
        "total": {"processors": N, "builder_methods": M}
    }
    """
    processors = _collect_processors()
    builder_methods = _collect_builder_methods()
    return JSONResponse(
        content={
            "processors": processors,
            "builder_methods": builder_methods,
            "total": {
                "processors": len(processors),
                "builder_methods": len(builder_methods),
            },
        }
    )


@router.get("/processors/{name}", summary="Details for single processor")
async def processor_details(name: str) -> JSONResponse:
    """Details одного процессора по имени (exact match)."""
    processors = _collect_processors()
    for p in processors:
        if p["name"] == name:
            return JSONResponse(content=p)
    return JSONResponse(
        status_code=404, content={"error": f"Processor '{name}' not found"}
    )
