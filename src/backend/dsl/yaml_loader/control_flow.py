"""S62 W4 — control_flow.py part of yaml_loader decomp.

Funcs: _materialize_control_flow_params.

control flow params materialization.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.builder import RouteBuilder

# Sentinel for "not set" to distinguish from None
_MISSING = object()


def _materialize_control_flow_params(
    builder: RouteBuilder, proc_name: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Рекурсивно превращает nested-spec'и в готовые объекты для builder.

    Args:
        builder: Родительский RouteBuilder (для context route_id/source).
        proc_name: Имя control-flow процессора.
        params: Сырые kwargs из YAML.

    Returns:
        Новый dict kwargs с подставленными ``BaseProcessor`` / ``ChoiceBranch``
        / ``SagaStep`` объектами.
    """
    from src.backend.dsl.engine.processors import ChoiceBranch, SagaStep
    from src.backend.dsl.yaml_loader.build import _build_sub

    materialized = dict(params)

    match proc_name:
        case "do_try":
            for key in ("try_processors", "catch_processors", "finally_processors"):
                if key in materialized and isinstance(materialized[key], list):
                    materialized[key] = _build_sub(builder, materialized[key])
        case "retry":
            if "processors" in materialized and isinstance(
                materialized["processors"], list
            ):
                materialized["processors"] = _build_sub(
                    builder, materialized["processors"]
                )
        case "parallel":
            branches = materialized.get("branches")
            if isinstance(branches, dict):
                materialized["branches"] = {
                    name: _build_sub(builder, sub_specs)
                    for name, sub_specs in branches.items()
                }
        case "saga":
            steps = materialized.get("steps")
            if isinstance(steps, list):
                saga_steps: list[SagaStep] = []
                for entry in steps:
                    if not isinstance(entry, dict):
                        raise ValueError(f"Saga step must be a mapping, got: {entry!r}")
                    forward_spec = entry.get("forward")
                    if forward_spec is None:
                        raise ValueError("Saga step missing 'forward'")
                    forward = _build_sub(builder, [forward_spec])[0]
                    compensate = None
                    if entry.get("compensate") is not None:
                        compensate = _build_sub(builder, [entry["compensate"]])[0]
                    saga_steps.append(SagaStep(forward=forward, compensate=compensate))
                materialized["steps"] = saga_steps
        case "choice":
            when = materialized.get("when")
            if isinstance(when, list):
                branches_obj: list[ChoiceBranch] = []
                for entry in when:
                    if not isinstance(entry, dict) or "expr" not in entry:
                        raise ValueError(
                            "Choice branch must be a mapping with 'expr' (JMESPath)"
                        )
                    sub_specs = entry.get("processors", []) or []
                    branches_obj.append(
                        ChoiceBranch(
                            expr=entry["expr"],
                            processors=_build_sub(builder, sub_specs),
                        )
                    )
                materialized["when"] = branches_obj
            otherwise = materialized.get("otherwise")
            if isinstance(otherwise, list):
                materialized["otherwise"] = _build_sub(builder, otherwise)

    return materialized
