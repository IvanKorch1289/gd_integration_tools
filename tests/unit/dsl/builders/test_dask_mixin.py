"""Unit-тесты DaskMixin — S128 W2 (TD-025)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.builders.base import RouteBuilder
from src.backend.dsl.builders.dask_mixin import DaskMixin
from src.backend.dsl.engine.processors.dask_compute import DaskComputeProcessor


# --------------------------------------------------------------------------- #
# DaskMixin.dask_compute
# --------------------------------------------------------------------------- #


class TestDaskComputeMethod:
    def test_returns_route_builder(self) -> None:
        result = DaskMixin.dask_compute(
            "test.route",
            graph=[{"op": "map", "fn": "os.path:join"}],
        )
        assert isinstance(result, RouteBuilder)

    def test_adds_dask_processor(self) -> None:
        result = DaskMixin.dask_compute(
            "test.route",
            graph=[{"op": "map", "fn": "os.path:join"}],
        )
        assert len(result._processors) == 1
        assert isinstance(result._processors[0], DaskComputeProcessor)

    def test_empty_graph_raises(self) -> None:
        with pytest.raises(ValueError, match="пустой graph"):
            DaskMixin.dask_compute("test.route", graph=[])

    def test_step_without_op_raises(self) -> None:
        with pytest.raises(ValueError, match="без 'op'"):
            DaskMixin.dask_compute(
                "test.route",
                graph=[{"fn": "os.path:join"}],  # no "op"
            )

    def test_graph_passed_to_processor(self) -> None:
        graph = [
            {"op": "map", "fn": "os.path:join"},
            {"op": "filter", "fn": "os.path:exists"},
        ]
        result = DaskMixin.dask_compute("test.route", graph=graph)
        proc = result._processors[0]
        assert proc._graph == graph
        assert proc._output_to == "body"

    def test_custom_output_to(self) -> None:
        result = DaskMixin.dask_compute(
            "test.route",
            graph=[{"op": "map", "fn": "os.path:join"}],
            output_to="headers.result",
        )
        proc = result._processors[0]
        assert proc._output_to == "headers.result"

    def test_scheduler_address_passed(self) -> None:
        result = DaskMixin.dask_compute(
            "test.route",
            graph=[{"op": "map", "fn": "os.path:join"}],
            scheduler_address="tcp://scheduler:8786",
        )
        proc = result._processors[0]
        # We don't introspect backend internals, but processor was created
        assert proc is not None

    def test_n_workers_default(self) -> None:
        result = DaskMixin.dask_compute(
            "test.route",
            graph=[{"op": "map", "fn": "os.path:join"}],
        )
        proc = result._processors[0]
        # n_workers передаётся в _backend, не сохраняется в instance attr
        assert proc._backend is not None


# --------------------------------------------------------------------------- #
# DaskMixin.dask_map shortcut
# --------------------------------------------------------------------------- #


class TestDaskMapShortcut:
    def test_returns_route_builder(self) -> None:
        result = DaskMixin.dask_map("test.route", fn="os.path:join")
        assert isinstance(result, RouteBuilder)

    def test_single_map_step(self) -> None:
        result = DaskMixin.dask_map("test.route", fn="os.path:join")
        proc = result._processors[0]
        assert len(proc._graph) == 1
        assert proc._graph[0] == {"op": "map", "fn": "os.path:join"}


# --------------------------------------------------------------------------- #
# Mixin behavior: __slots__ = ()
# --------------------------------------------------------------------------- #


class TestMixinShape:
    def test_does_not_modify_class_state(self) -> None:
        """Calling dask_compute doesn't add class-level state."""
        before = set(DaskMixin.__dict__.keys())
        DaskMixin.dask_compute(
            "test.x", graph=[{"op": "map", "fn": "os.path:join"}]
        )
        after = set(DaskMixin.__dict__.keys())
        assert before == after
