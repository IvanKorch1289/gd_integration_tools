"""DX-3: Processor introspection API.

W26.5: маршруты регистрируются декларативно через ActionSpec.

Возвращает JSON-каталог всех DSL-процессоров с signatures и docstrings.
Используется:
- Streamlit UI для auto-complete
- AI агентами для route-building
- Developer docs

Endpoints:
  * GET /api/v1/dsl/processors/catalog
  * GET /api/v1/dsl/processors/{name}
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)

__all__ = ("router",)


class ProcessorNamePath(BaseModel):
    """Path-параметр имени процессора."""

    name: str = Field(..., description="Имя процессора (exact match).")


def _collect_processors() -> list[dict[str, Any]]:
    """Scan all DSL processor modules + collect metadata."""
    from src.backend.dsl.engine.processors import base

    results: list[dict[str, Any]] = []
    visited: set[str] = set()

    module_paths = [
        "src.backend.dsl.engine.processors.core",
        "src.backend.dsl.engine.processors.control_flow",
        "src.backend.dsl.engine.processors.eip.routing",
        "src.backend.dsl.engine.processors.eip.transformation",
        "src.backend.dsl.engine.processors.eip.resilience",
        "src.backend.dsl.engine.processors.eip.flow_control",
        "src.backend.dsl.engine.processors.eip.idempotency",
        "src.backend.dsl.engine.processors.eip.sequencing",
        "src.backend.dsl.engine.processors.components",
        "src.backend.dsl.engine.processors.converters",
        "src.backend.dsl.engine.processors.patterns",
        "src.backend.dsl.engine.processors.scraping",
        "src.backend.dsl.engine.processors.ai",
        "src.backend.dsl.engine.processors.rpa",
        "src.backend.dsl.engine.processors.web",
        "src.backend.dsl.engine.processors.external",
        "src.backend.dsl.engine.processors.integration",
        "src.backend.dsl.engine.processors.export",
        "src.backend.dsl.engine.processors.dq_check",
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
    from src.backend.dsl.builder import RouteBuilder

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


class _ProcessorsCatalogFacade:
    """Адаптер для introspection-эндпоинтов DSL-процессоров."""

    async def catalog(self) -> dict[str, Any]:
        processors = _collect_processors()
        builder_methods = _collect_builder_methods()
        return {
            "processors": processors,
            "builder_methods": builder_methods,
            "total": {
                "processors": len(processors),
                "builder_methods": len(builder_methods),
            },
        }

    async def details(self, *, name: str) -> dict[str, Any]:
        for p in _collect_processors():
            if p["name"] == name:
                return p
        raise HTTPException(status_code=404, detail=f"Processor '{name}' not found")


_FACADE = _ProcessorsCatalogFacade()


def _get_facade() -> _ProcessorsCatalogFacade:
    return _FACADE


router = APIRouter(prefix="/dsl", tags=["DSL Catalog"])
builder = ActionRouterBuilder(router)


builder.add_actions(
    [
        ActionSpec(
            name="processors_catalog",
            method="GET",
            path="/processors/catalog",
            summary="DSL processor catalog (introspection)",
            service_getter=_get_facade,
            service_method="catalog",
            tags=("DSL Catalog",),
        ),
        ActionSpec(
            name="processor_details",
            method="GET",
            path="/processors/{name}",
            summary="Details for single processor",
            service_getter=_get_facade,
            service_method="details",
            path_model=ProcessorNamePath,
            tags=("DSL Catalog",),
        ),
    ]
)
