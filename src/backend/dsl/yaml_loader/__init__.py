"""YAML loader package (S62 W4 decomp from yaml_loader.py 495 LOC).

10 top-level funcs decomposed в 4 files (per concern):
- ``resolve.py`` (2): _is_route_composition_include_enabled, _resolve_include_extends (153 LOC BIG)
- ``loaders.py`` (3): load_pipeline_from_yaml, load_pipeline_from_file, load_all_from_directory
- ``build.py`` (4): _build_pipeline, _is_allowed_processor, _build_sub, _apply_processor
- ``control_flow.py`` (1): _materialize_control_flow_params

Backward-compat: ``from src.backend.dsl.yaml_loader import load_pipeline_from_yaml`` works.
"""

from __future__ import annotations

from src.backend.dsl.yaml_loader.build import (
    _apply_processor,  # S62 W4: re-export
    _build_pipeline,  # S62 W4: re-export
    _build_sub,  # S62 W4: re-export
    _is_allowed_processor,  # S62 W4: re-export
)
from src.backend.dsl.yaml_loader.control_flow import (
    _materialize_control_flow_params,  # S62 W4: re-export
)
from src.backend.dsl.yaml_loader.loaders import (
    load_all_from_directory,  # S62 W4: re-export
    load_pipeline_from_file,  # S62 W4: re-export
    load_pipeline_from_yaml,  # S62 W4: re-export
)
from src.backend.dsl.yaml_loader.resolve import (
    _is_route_composition_include_enabled,  # S62 W4: re-export
    _resolve_include_extends,  # S62 W4: re-export
)

__all__ = (
    "_is_route_composition_include_enabled",
    "_resolve_include_extends",
    "load_pipeline_from_yaml",
    "load_pipeline_from_file",
    "load_all_from_directory",
    "_build_pipeline",
    "_is_allowed_processor",
    "_build_sub",
    "_apply_processor",
    "_materialize_control_flow_params",
)
