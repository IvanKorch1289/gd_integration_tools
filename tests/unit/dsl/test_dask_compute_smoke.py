"""Wave 7-tail smoke: DaskComputeProcessor — конструктор + валидация ввода.

Не запускаем dask compute (LocalCluster — heavy), проверяем только
контракт конструктора и предусловий валидации.
"""

from __future__ import annotations

import pytest

from src.dsl.engine.processors.dask_compute import (
    DaskComputeProcessor,
    _resolve_callable,
)


def test_dask_compute_minimal_graph_constructs() -> None:
    """Минимальный валидный graph принимается конструктором."""
    proc = DaskComputeProcessor(
        graph=[{"op": "map", "fn": "json:dumps"}], output_to="body"
    )
    assert proc.name == "dask_compute"


def test_dask_compute_empty_graph_rejected() -> None:
    """Пустой graph → ValueError ('пустой graph')."""
    with pytest.raises(ValueError, match="пустой graph"):
        DaskComputeProcessor(graph=[])


def test_dask_compute_step_without_op_rejected() -> None:
    """Step без 'op' → ValueError."""
    with pytest.raises(ValueError, match="без 'op'"):
        DaskComputeProcessor(graph=[{"fn": "json:dumps"}])


def test_resolve_callable_invalid_path_rejected() -> None:
    """Невалидный dotted path (без `:` или `.`) → ValueError."""
    with pytest.raises(ValueError, match="невалидный путь"):
        _resolve_callable("just_name")
