"""Registry Explorer — unified view для routes/connectors/agents (Wave 2 DX #54).

Проблема:
    Разработчику нужно найти:
    - Какие routes есть в проекте?
    - Какие connectors доступны?
    - Где искать owner / tests / traces / DLQ?
    - Какие routes вызывают какие actions?

Решение:
    ``RegistryExplorer`` — централизованный query layer:

    1. ``RouteEntry`` — route metadata (id, source, contract, owner).
    2. ``ConnectorEntry`` — connector metadata (name, category, auth, operations).
    3. ``ActionEntry`` — action metadata (name, params, side effect).
    4. ``RouteExplorer`` — register/lookup/filter.
    5. ``find_route(id)`` / ``find_connector(name)`` — direct lookups.
    6. ``search(filters)`` — multi-criteria search.

Использование::

    from src.backend.core.registry_explorer import (
        RegistryExplorer, RouteEntry, get_registry_explorer,
    )

    explorer = get_registry_explorer()
    explorer.register_route(RouteEntry(
        id="order-create", source="timer:60s", owner="team-payments",
    ))
    explorer.register_connector(ConnectorEntry(
        name="skb", category="external", auth="oauth2",
    ))

    routes = explorer.list_routes_by_owner("team-payments")
    print(routes[0].id)  # order-create
"""

from __future__ import annotations

from src.backend.core.registry_explorer.auto_seed import (
    StreamlitPageRegistry,
    auto_seed_from_project,
    get_page_registry,
    reset_page_registry,
)
from src.backend.core.registry_explorer.explorer import (
    ActionEntry,
    ConnectorEntry,
    RegistryExplorer,
    RouteEntry,
    get_registry_explorer,
)

__all__ = (
    "ActionEntry",
    "ConnectorEntry",
    "RegistryExplorer",
    "RouteEntry",
    "StreamlitPageRegistry",
    "auto_seed_from_project",
    "get_page_registry",
    "get_registry_explorer",
    "reset_page_registry",
)
