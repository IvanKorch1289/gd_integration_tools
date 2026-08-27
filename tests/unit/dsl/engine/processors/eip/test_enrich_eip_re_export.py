"""P4-C regression test (Cycle 20, production-grade plan).

EnrichProcessor теперь доступен в eip/ namespace (Camel Content Enricher
EIP discoverability parity).

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/dsl/engine/processors/eip/test_enrich_eip_re_export.py -v
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.core import (
    EnrichProcessor as CoreEnrichProcessor,
)
from src.backend.dsl.engine.processors.eip import EnrichProcessor as EipEnrichProcessor
from src.backend.dsl.engine.processors.eip.content_enricher import (
    EnrichProcessor as ContentEnricherProcessor,
)


class TestEnrichProcessorEipReExport:
    """Cycle 20: EnrichProcessor re-export из eip/ namespace."""

    def test_eip_re_export_is_canonical_class(self) -> None:
        """``eip.EnrichProcessor is core.EnrichProcessor``."""
        assert EipEnrichProcessor is CoreEnrichProcessor, (
            "eip.EnrichProcessor должен быть тем же классом, что "
            "core.EnrichProcessor (re-export без subclass)."
        )

    def test_eip_content_enricher_module_reexport(self) -> None:
        """``eip.content_enricher.EnrichProcessor`` доступен."""
        assert ContentEnricherProcessor is CoreEnrichProcessor

    def test_eip_enrich_in_all(self) -> None:
        """``EnrichProcessor`` в eip/__init__.py __all__."""
        from src.backend.dsl.engine.processors import eip as eip_pkg

        assert "EnrichProcessor" in eip_pkg.__all__, (
            "EnrichProcessor НЕ в eip/__init__.py __all__ — discovery gap"
        )

    def test_enrich_eip_parity_with_aggregator(self) -> None:
        """Parity с Aggregator EIP — оба discoverable в eip/ namespace."""
        from src.backend.dsl.engine.processors.eip import AggregatorProcessor

        assert AggregatorProcessor.__module__.startswith("src.backend.dsl.engine.processors.eip")
        assert EipEnrichProcessor.__module__.startswith("src.backend.dsl.engine.processors.")
