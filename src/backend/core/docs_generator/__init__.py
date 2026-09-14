"""Docs Generator — auto-Markdown docs from registry (Wave 2 DX #60).

Проблема:
    Документация устаревает:
    - Routes добавляются → README не обновляется.
    - Connectors меняются → ADRs не обновляются.
    - Actions появляются → reference docs не обновляются.

Решение:
    ``DocsGenerator`` — pure-Python Markdown generator from registry:

    1. ``generate_routes_md(routes)`` → routes/index.md.
    2. ``generate_connectors_md(connectors)`` → connectors/index.md.
    3. ``generate_actions_md(actions)`` → actions/index.md.
    4. ``generate_index(sections)`` → top-level index.md.
    5. ``export_docs(generator, target_dir)`` — write all files.

Использование::

    from src.backend.core.registry_explorer import get_registry_explorer
    from src.backend.core.docs_generator import DocsGenerator

    explorer = get_registry_explorer()
    # ... populate explorer ...

    gen = DocsGenerator()
    sections = {
        "routes": gen.generate_routes_md(explorer),
        "connectors": gen.generate_connectors_md(explorer),
        "actions": gen.generate_actions_md(explorer),
    }
    gen.export_docs(sections, "docs/generated")
"""

from __future__ import annotations

from src.backend.core.docs_generator.generator import (
    DocsGenerator,
    get_docs_generator,
)

__all__ = ("DocsGenerator", "get_docs_generator")
