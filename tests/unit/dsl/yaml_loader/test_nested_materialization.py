"""Регрессии материализации вложенных списков YAML-DSL (ADR-0397, кластер D).

Дефект 4: вложенные списки процессоров материализовались только для
``do_try``/``retry``/``parallel``/``saga``/``choice``. Для ``for_each``,
``fork_join``, ``switch``, ``timeout`` в YAML оставался raw-dict →
в runtime ``failed: 'dict' object has no attribute 'process'``.

Плюс: ``for_each`` с невалидным JMESPath-выражением падал тихо
(0 итераций) — теперь load-time fail-fast.
"""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.yaml_loader.loaders import load_pipeline_from_yaml


def _load(step_yaml: str):
    """Собрать pipeline из одного шага."""
    return load_pipeline_from_yaml(
        "route_id: nested_test\nsource: http:/nested\nsteps:\n" + step_yaml
    )


def test_for_each_processors_materialized() -> None:
    """for_each: список processors → готовые BaseProcessor."""
    pipeline = _load(
        "- for_each:\n"
        "    items_path: body.items\n"
        "    processors:\n"
        "    - log:\n"
        "        level: info\n"
        "        message: nested\n"
    )
    nested = pipeline.processors[0]._processors  # type: ignore[attr-defined]
    assert nested
    assert all(isinstance(p, BaseProcessor) for p in nested)


def test_fork_join_branches_materialized() -> None:
    """fork_join: branches (dict → list processors) материализуются."""
    pipeline = _load(
        "- fork_join:\n"
        "    branches:\n"
        "      left:\n"
        "      - log:\n"
        "          level: info\n"
        "          message: l\n"
        "      right:\n"
        "      - log:\n"
        "          level: info\n"
        "          message: r\n"
    )
    branches = pipeline.processors[0]._branches  # type: ignore[attr-defined]
    assert set(branches) == {"left", "right"}
    assert all(
        isinstance(p, BaseProcessor) for procs in branches.values() for p in procs
    )


def test_switch_cases_materialized() -> None:
    """switch: cases (dict → list processors) + default материализуются."""
    pipeline = _load(
        "- switch:\n"
        "    field: body.kind\n"
        "    cases:\n"
        "      a:\n"
        "      - log:\n"
        "          level: info\n"
        "          message: a\n"
        "    default:\n"
        "    - log:\n"
        "        level: info\n"
        "        message: d\n"
    )
    processor = pipeline.processors[0]
    cases = processor._cases  # type: ignore[attr-defined]
    default = processor._default  # type: ignore[attr-defined]
    assert all(
        isinstance(p, BaseProcessor) for procs in cases.values() for p in procs
    )
    assert default is None or all(isinstance(p, BaseProcessor) for p in default)


def test_timeout_processors_materialized() -> None:
    """timeout: processors + fallback_processors материализуются."""
    pipeline = _load(
        "- timeout:\n"
        "    seconds: 1.0\n"
        "    processors:\n"
        "    - log:\n"
        "        level: info\n"
        "        message: t\n"
        "    fallback_processors:\n"
        "    - log:\n"
        "        level: warn\n"
        "        message: fb\n"
    )
    processor = pipeline.processors[0]
    nested = processor._processors  # type: ignore[attr-defined]
    fallback = processor._fallback  # type: ignore[attr-defined]
    assert all(isinstance(p, BaseProcessor) for p in nested)
    assert fallback is None or all(isinstance(p, BaseProcessor) for p in fallback)


def test_for_each_invalid_jmespath_fails_at_load() -> None:
    """Невалидный JMESPath в for_each → fail-fast на этапе load, а не тихий 0-итерацийный прогон."""
    with pytest.raises(ValueError, match="items_path"):
        _load(
            "- for_each:\n"
            "    items_path: body.items[?\n"
            "    processors:\n"
            "    - log:\n"
            "        level: info\n"
            "        message: t\n"
        )


def test_choice_keeps_bespoke_structure() -> None:
    """choice.when остаётся списком ChoiceBranch ( bespoke control-flow ).

    Регрессия: общий разбор аннотаций builder'а не должен применяться к
    control-flow-шагам со своей структурой (choice.when / saga.steps).
    """
    from src.backend.dsl.engine.processors import ChoiceBranch

    pipeline = _load(
        "- choice:\n"
        "    when:\n"
        "    - expr: body.kind == 'a'\n"
        "      processors:\n"
        "      - log:\n"
        "          level: info\n"
        "          message: a\n"
    )
    branches = pipeline.processors[0]._branches  # type: ignore[attr-defined]
    assert branches
    assert all(isinstance(b, ChoiceBranch) for b in branches)
    assert all(isinstance(p, BaseProcessor) for b in branches for p in b.processors)
