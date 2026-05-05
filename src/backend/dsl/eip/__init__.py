"""EIP — каталог Enterprise Integration Patterns (Apache Camel).

Часть фазы C1. Реальные процессоры лежат в
``app.dsl.engine.processors``; этот пакет — curated public API с
человеко-читаемой документацией и маппингом на fluent API RouteBuilder.

Поддерживаемые паттерны:

* Wire Tap — `.wire_tap(target)`
* Dead Letter Channel — `.dead_letter_channel(queue)`
* Message History — автоматически через `.with_observability()`
* Dynamic Router — `.dynamic_router(expr)`
* Routing Slip — `.routing_slip(slip_expr)`
* Multicast — `.multicast([...])`
* Recipient List — `.recipient_list(expr)`
* Claim Check — `.claim_check(store)`
* Content Enricher — `.enrich(source)`
* Normalizer — `.normalizer(mapping)`
* Content Filter — `.content_filter(fields=[...])`
* Resequencer — `.resequencer(key=...)`

См. ``docs/DSL_COOKBOOK.md`` раздел «Camel EIP» для YAML-примеров.
"""

from src.dsl.engine.processors import (
    ClaimCheckProcessor,
    DeadLetterProcessor,
    EnrichProcessor,
    MessageTranslatorProcessor,
    MulticastProcessor,
    NormalizerProcessor,
    RecipientListProcessor,
    ResequencerProcessor,
    WireTapProcessor,
)

__all__ = (
    "WireTapProcessor",
    "DeadLetterProcessor",
    "MulticastProcessor",
    "RecipientListProcessor",
    "ClaimCheckProcessor",
    "EnrichProcessor",
    "NormalizerProcessor",
    "ResequencerProcessor",
    "MessageTranslatorProcessor",
)
