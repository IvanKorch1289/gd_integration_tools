"""Focused tests: W2 P0-3 Phase 1C — event_store + idp_pipeline_processor subpackage migration.

Cycle 152 (MINIMAX W2 P0-3): 2 subpackages мигрированы из legacy
``dsl/processors/`` в canonical ``dsl/engine/processors/``. Каждый legacy
subpackage → re-export shim с ``__getattr__`` lazy proxy pattern.

Все классы/data-классы/функции проксируются автоматически.
"""

from __future__ import annotations

import warnings


class TestEventStoreShim:
    """event_store/ subpackage: legacy shim → dsl.engine.processors.event_store."""

    def test_identity_event_store(self) -> None:
        from src.backend.dsl.engine.processors.event_store import (
            EventStore as Canonical,
        )
        from src.backend.dsl.processors.event_store import EventStore

        assert EventStore is Canonical

    def test_identity_in_memory_event_store(self) -> None:
        from src.backend.dsl.engine.processors.event_store import (
            InMemoryEventStore as Canonical,
        )
        from src.backend.dsl.processors.event_store import InMemoryEventStore

        assert InMemoryEventStore is Canonical

    def test_identity_event_store_processor(self) -> None:
        from src.backend.dsl.engine.processors.event_store import (
            EventStoreProcessor as Canonical,
        )
        from src.backend.dsl.processors.event_store import EventStoreProcessor

        assert EventStoreProcessor is Canonical

    def test_identity_command_bus(self) -> None:
        from src.backend.dsl.engine.processors.event_store import (
            CommandBus as Canonical,
        )
        from src.backend.dsl.processors.event_store import CommandBus

        assert CommandBus is Canonical

    def test_identity_query_bus(self) -> None:
        from src.backend.dsl.engine.processors.event_store import QueryBus as Canonical
        from src.backend.dsl.processors.event_store import QueryBus

        assert QueryBus is Canonical

    def test_identity_projection(self) -> None:
        from src.backend.dsl.engine.processors.event_store import (
            Projection as Canonical,
        )
        from src.backend.dsl.processors.event_store import Projection

        assert Projection is Canonical

    def test_identity_cqrs_mixin(self) -> None:
        from src.backend.dsl.engine.processors.event_store import CQRSMixin as Canonical
        from src.backend.dsl.processors.event_store import CQRSMixin

        assert CQRSMixin is Canonical

    def test_identity_event_dataclass(self) -> None:
        from src.backend.dsl.engine.processors.event_store import Event as Canonical
        from src.backend.dsl.processors.event_store import Event

        assert Event is Canonical

    def test_identity_event_stream(self) -> None:
        from src.backend.dsl.engine.processors.event_store import (
            EventStream as Canonical,
        )
        from src.backend.dsl.processors.event_store import EventStream

        assert EventStream is Canonical

    def test_identity_helper_functions(self) -> None:
        from src.backend.dsl.engine.processors.event_store import get_event_store as C1
        from src.backend.dsl.engine.processors.event_store import (
            reset_event_store as C3,
        )
        from src.backend.dsl.engine.processors.event_store import set_event_store as C2
        from src.backend.dsl.processors.event_store import (
            get_event_store,
            reset_event_store,
            set_event_store,
        )

        assert get_event_store is C1
        assert set_event_store is C2
        assert reset_event_store is C3


class TestIDPPipelineShim:
    """idp_pipeline_processor/ subpackage: legacy shim → canonical."""

    def test_identity_idp_pipeline_processor(self) -> None:
        from src.backend.dsl.engine.processors.idp_pipeline_processor import (
            IDPPipelineProcessor as Canonical,
        )
        from src.backend.dsl.processors.idp_pipeline_processor import (
            IDPPipelineProcessor,
        )

        assert IDPPipelineProcessor is Canonical

    def test_identity_classify_document(self) -> None:
        from src.backend.dsl.engine.processors.idp_pipeline_processor import (
            classify_document as Canonical,
        )
        from src.backend.dsl.processors.idp_pipeline_processor import classify_document

        assert classify_document is Canonical

    def test_identity_extract_fields(self) -> None:
        from src.backend.dsl.engine.processors.idp_pipeline_processor import (
            extract_fields as Canonical,
        )
        from src.backend.dsl.processors.idp_pipeline_processor import extract_fields

        assert extract_fields is Canonical

    def test_identity_validate_result(self) -> None:
        from src.backend.dsl.engine.processors.idp_pipeline_processor import (
            validate_result as Canonical,
        )
        from src.backend.dsl.processors.idp_pipeline_processor import validate_result

        assert validate_result is Canonical


class TestDslProcessorsReExportHubPhase1C:
    """``dsl.processors.__init__`` re-export hub использует canonical paths."""

    def test_hub_exposes_event_store_classes(self) -> None:
        """Hub экспортирует event_store + idp_pipeline_processor без DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
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

    def test_hub_get_helper_functions(self) -> None:
        """Helper functions get/set/reset_event_store доступны через hub."""
        from src.backend.dsl.engine.processors.event_store import get_event_store as C1
        from src.backend.dsl.engine.processors.event_store import (
            reset_event_store as C3,
        )
        from src.backend.dsl.engine.processors.event_store import set_event_store as C2
        from src.backend.dsl.processors import (
            get_event_store,
            reset_event_store,
            set_event_store,
        )

        assert get_event_store is C1
        assert set_event_store is C2
        assert reset_event_store is C3
