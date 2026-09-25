"""Focused tests: W2 P0-3 Phase 1B — 5 single-file processors migration.

Cycle 152 (MINIMAX W2 P0-3): strangler_fig, data_lineage, plan_execute_processor,
reflection_loop_processor, router_specialist_processor — каждый мигрирован
в canonical location + legacy → re-export shim с DeprecationWarning.

Все shim'ы используют ``__getattr__`` lazy import для проксирования
любых классов (mixin, enum, dataclass) из canonical module.
"""

from __future__ import annotations

import warnings


class TestStranglerFigShim:
    """strangler_fig.py: legacy shim → dsl.engine.processors.strangler_fig."""

    def test_identity_for_strangler_fig_processor(self) -> None:
        from src.backend.dsl.engine.processors.strangler_fig import (
            StranglerFigProcessor as Canonical,
        )
        from src.backend.dsl.processors.strangler_fig import StranglerFigProcessor

        assert StranglerFigProcessor is Canonical

    def test_identity_for_route_target(self) -> None:
        from src.backend.dsl.engine.processors.strangler_fig import (
            RouteTarget as Canonical,
        )
        from src.backend.dsl.processors.strangler_fig import RouteTarget

        assert RouteTarget is Canonical

    def test_identity_for_strangler_fig_mixin(self) -> None:
        from src.backend.dsl.engine.processors.strangler_fig import (
            MigrationMixin as Canonical,
        )
        from src.backend.dsl.processors.strangler_fig import MigrationMixin

        assert MigrationMixin is Canonical


class TestDataLineageShim:
    """data_lineage.py: legacy shim → dsl.engine.processors.data_lineage."""

    def test_identity_for_data_lineage_processor(self) -> None:
        from src.backend.dsl.engine.processors.data_lineage import (
            DataLineageProcessor as Canonical,
        )
        from src.backend.dsl.processors.data_lineage import DataLineageProcessor

        assert DataLineageProcessor is Canonical

    def test_identity_for_lineage_node(self) -> None:
        from src.backend.dsl.engine.processors.data_lineage import (
            LineageNode as Canonical,
        )
        from src.backend.dsl.processors.data_lineage import LineageNode

        assert LineageNode is Canonical

    def test_identity_for_lineage_event(self) -> None:
        from src.backend.dsl.engine.processors.data_lineage import (
            LineageEvent as Canonical,
        )
        from src.backend.dsl.processors.data_lineage import LineageEvent

        assert LineageEvent is Canonical


class TestPlanExecuteShim:
    """plan_execute_processor.py: legacy shim → canonical."""

    def test_identity_for_plan_execute_processor(self) -> None:
        from src.backend.dsl.engine.processors.plan_execute_processor import (
            PlanExecuteProcessor as Canonical,
        )
        from src.backend.dsl.processors.plan_execute_processor import (
            PlanExecuteProcessor,
        )

        assert PlanExecuteProcessor is Canonical

    def test_identity_for_plan_step(self) -> None:
        from src.backend.dsl.engine.processors.plan_execute_processor import (
            PlanStep as Canonical,
        )
        from src.backend.dsl.processors.plan_execute_processor import PlanStep

        assert PlanStep is Canonical

    def test_identity_for_plan_result(self) -> None:
        from src.backend.dsl.engine.processors.plan_execute_processor import (
            PlanResult as Canonical,
        )
        from src.backend.dsl.processors.plan_execute_processor import PlanResult

        assert PlanResult is Canonical

    def test_identity_for_plan_execute_mixin(self) -> None:
        from src.backend.dsl.engine.processors.plan_execute_processor import (
            PlanExecuteMixin as Canonical,
        )
        from src.backend.dsl.processors.plan_execute_processor import PlanExecuteMixin

        assert PlanExecuteMixin is Canonical


class TestReflectionLoopShim:
    """reflection_loop_processor.py: legacy shim → canonical."""

    def test_identity_for_reflection_loop_processor(self) -> None:
        from src.backend.dsl.engine.processors.reflection_loop_processor import (
            ReflectionLoopProcessor as Canonical,
        )
        from src.backend.dsl.processors.reflection_loop_processor import (
            ReflectionLoopProcessor,
        )

        assert ReflectionLoopProcessor is Canonical

    def test_identity_for_reflection_result(self) -> None:
        from src.backend.dsl.engine.processors.reflection_loop_processor import (
            ReflectionResult as Canonical,
        )
        from src.backend.dsl.processors.reflection_loop_processor import (
            ReflectionResult,
        )

        assert ReflectionResult is Canonical

    def test_identity_for_reflection_loop_mixin(self) -> None:
        from src.backend.dsl.engine.processors.reflection_loop_processor import (
            ReflectionLoopMixin as Canonical,
        )
        from src.backend.dsl.processors.reflection_loop_processor import (
            ReflectionLoopMixin,
        )

        assert ReflectionLoopMixin is Canonical


class TestRouterSpecialistShim:
    """router_specialist_processor.py: legacy shim → canonical."""

    def test_identity_for_router_specialist_processor(self) -> None:
        from src.backend.dsl.engine.processors.router_specialist_processor import (
            RouterSpecialistProcessor as Canonical,
        )
        from src.backend.dsl.processors.router_specialist_processor import (
            RouterSpecialistProcessor,
        )

        assert RouterSpecialistProcessor is Canonical

    def test_identity_for_specialist_agent(self) -> None:
        from src.backend.dsl.engine.processors.router_specialist_processor import (
            SpecialistAgent as Canonical,
        )
        from src.backend.dsl.processors.router_specialist_processor import (
            SpecialistAgent,
        )

        assert SpecialistAgent is Canonical


class TestDslProcessorsReExportHub:
    """``dsl.processors.__init__`` re-export hub использует canonical paths."""

    def test_hub_exposes_all_6_consolidated_processors(self) -> None:
        """Hub должен экспортировать 6 мигрированных processors без DeprecationWarning.

        Hub импортирует напрямую из canonical location, поэтому
        DeprecationWarning не эмитится (важно для downstream tooling,
        который импортирует :mod:`dsl.processors` напрямую).
        """
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from src.backend.dsl.processors import (
                BatchProcessor,
                DataLineageProcessor,
                PlanExecuteProcessor,
                ReflectionLoopProcessor,
                RouterSpecialistProcessor,
                StranglerFigProcessor,
            )
        deprecations = [
            x
            for x in w
            if issubclass(x.category, DeprecationWarning)
            and "W2 P0-3 processor consolidation" in str(x.message)
        ]
        assert len(deprecations) == 0, (
            f"Hub should not emit W2 P0-3 deprecation warnings, got: "
            f"{[str(x.message) for x in deprecations]}"
        )
        # Sanity: все классы загружены.
        assert all(
            cls is not None
            for cls in [
                BatchProcessor,
                DataLineageProcessor,
                PlanExecuteProcessor,
                ReflectionLoopProcessor,
                RouterSpecialistProcessor,
                StranglerFigProcessor,
            ]
        )

    def test_hub_exposes_legacy_saga_lra_processor(self) -> None:
        """SagaLRA остаётся legacy (другая реализация) — Phase 2 ADR."""
        from src.backend.dsl.processors import SagaLRAProcessor
        from src.backend.dsl.processors.saga_lra_processor import (
            SagaLRAProcessor as Legacy,
        )

        assert SagaLRAProcessor is Legacy
