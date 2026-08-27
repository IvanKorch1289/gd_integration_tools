"""Content Enricher EIP (Camel).

Re-export :class:`EnrichProcessor` из canonical location
(``dsl.engine.processors.core``) под eip/ namespace для discoverability
parity с Camel EIP catalog.

Camel Content Enricher (https://camel.apache.org/components/latest/eips/
enrich-message.html) — обогащение сообщения данными из внешнего action.
В gd_integration_tools реализован через ``action_registry.dispatch`` +
``result_property`` exchange pattern (см. ``core.py``).

P4-C (cycle 20, production-grade plan): discovery gap — ранее
``EnrichProcessor`` не был в ``dsl.engine.processors.eip`` namespace,
хотя Camel Content Enricher — стандартный EIP. Этот модуль закрывает
gap через thin re-export без перемещения класса (backward-compat).
"""

from src.backend.dsl.engine.processors.core import EnrichProcessor

__all__ = ("EnrichProcessor",)
