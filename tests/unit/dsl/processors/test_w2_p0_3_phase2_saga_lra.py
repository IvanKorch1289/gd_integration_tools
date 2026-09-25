"""Focused tests: W2 P0-3 Phase 2 — SagaLRAProcessor migration (mixin-based).

Cycle 152 (MINIMAX W2 P0-3 Phase 2): SagaLRA — **другая реализация**,
не дубликат. ADR-0316 (Variant A) — migrate legacy subpackage
(4 mixins + state + _protocol) в canonical `engine.processors.saga_lra_processor`,
превратить legacy в re-export shim.
"""

from __future__ import annotations

import warnings


class TestSagaLRACanonicalMigration:
    """Все SagaLRA классы/константы/exceptions доступны через canonical."""

    def test_saga_lra_processor_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            SagaLRAProcessor as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import (
            SagaLRAProcessor as Legacy,
        )

        assert Legacy is Canonical

    def test_saga_lra_error_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            SagaLRAError as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import SagaLRAError

        assert SagaLRAError is Canonical

    def test_saga_compensation_error_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            SagaCompensationError as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import SagaCompensationError

        assert SagaCompensationError is Canonical

    def test_saga_step_timeout_error_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            SagaStepTimeoutError as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import SagaStepTimeoutError

        assert SagaStepTimeoutError is Canonical

    def test_state_running_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            STATE_RUNNING as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import STATE_RUNNING

        assert STATE_RUNNING == Canonical == "running"

    def test_state_failed_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            STATE_FAILED as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import STATE_FAILED

        assert STATE_FAILED == Canonical == "failed"

    def test_state_completed_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            STATE_COMPLETED as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import STATE_COMPLETED

        assert STATE_COMPLETED == Canonical == "completed"

    def test_state_compensating_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            STATE_COMPENSATING as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import STATE_COMPENSATING

        assert STATE_COMPENSATING == Canonical == "compensating"

    def test_state_compensated_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            STATE_COMPENSATED as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import STATE_COMPENSATED

        assert STATE_COMPENSATED == Canonical == "compensated"

    def test_saga_state_identity(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            SagaState as Canonical,
        )
        from src.backend.dsl.processors.saga_lra_processor import SagaState

        assert SagaState is Canonical


class TestSagaLRAMixinArchitecture:
    """SagaLRAProcessor — mixin-based (CoreMixin + LifecycleMixin + etc.)."""

    def test_mro_includes_all_mixins(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            SagaLRAProcessor,
        )

        mro_names = [c.__name__ for c in SagaLRAProcessor.__mro__]
        assert "SagaLRAProcessor" in mro_names
        assert "CoreMixin" in mro_names
        assert "LifecycleMixin" in mro_names
        assert "SerializationMixin" in mro_names
        assert "ExecutionMixin" in mro_names


class TestSagaLRADistinctFromCurrentSagaLRA:
    """Legacy SagaLRA — другая реализация, не дубликат current saga_lra.py.

    Current saga_lra.py: single-file, BaseProcessor, simple state.
    Legacy saga_lra_processor: mixin-based, state machine, persistent.
    """

    def test_distinct_class_objects(self_legacy) -> None:
        from src.backend.dsl.engine.processors.saga_lra import (
            SagaLRAProcessor as CurrentSaga,
        )
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            SagaLRAProcessor as LegacySaga,
        )

        # Current и legacy — РАЗНЫЕ классы (по решению ADR-0316).
        assert CurrentSaga is not LegacySaga


class TestDslProcessorsReExportHubSagaLRA:
    """Hub экспортирует SagaLRAProcessor через canonical path."""

    def test_hub_exposes_saga_lra_via_canonical(self_legacy) -> None:
        """Hub re-exports SagaLRA через canonical, не через shim.

        Hub импортирует напрямую из canonical location, поэтому
        DeprecationWarning не эмитится (важно для downstream tooling,
        который импортирует :mod:`dsl.processors` напрямую).
        """
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from src.backend.dsl.processors import SagaLRAProcessor as HubSaga
        deprecations = [
            x
            for x in w
            if issubclass(x.category, DeprecationWarning)
            and "W2 P0-3 SagaLRA Phase 2" in str(x.message)
        ]
        assert len(deprecations) == 0, (
            f"Hub should not emit Phase 2 deprecation warnings, got: "
            f"{[str(x.message) for x in deprecations]}"
        )
        # Identity: hub SagaLRAProcessor == canonical
        from src.backend.dsl.engine.processors.saga_lra_processor import (
            SagaLRAProcessor as Canonical,
        )

        assert HubSaga is Canonical
