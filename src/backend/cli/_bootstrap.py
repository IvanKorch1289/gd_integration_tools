"""Минимальная инициализация для introspection manage.py команд.

P1 CLI decomposition (v4 §10 P1, 2026-09-24): извлечено из ``manage.py``
для sharing между корневыми командами и будущими sub-app Typer группами
(``info``, ``migrate``, ``health``). Pure side-effect function — вызывается
на старте каждой introspection-команды.

Re-exports:
- ``_bootstrap()`` — единая init function.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("manage.bootstrap")


def bootstrap() -> None:
    """Регистрирует services + action handlers + DSL routes для introspection.

    Per v4 §10 P1 «CLI decomposition»: extracted из ``manage.py:_bootstrap``
    для sharing между top-level командами и sub-app группами (Typer
    ``add_typer``). Naming: ``bootstrap`` (public) вместо ``_bootstrap``
    (private) для cross-module use — manage.py теперь re-exports.

    Side effects:
    - ``register_all_services()`` — DI service registry.
    - ``register_action_handlers()`` — action_handler_registry.
    - ``register_dsl_routes()`` — DSL route_registry.
    - ``get_v1_routers()`` — Tier 1 CRUD-actions через ActionRouterBuilder.

    Failures в опциональных зависимостях (vault/graypy/мини-профили) —
    logged на DEBUG, НЕ raise (introspection должен работать в degraded env).
    """
    from src.backend.dsl.commands.setup import register_action_handlers
    from src.backend.dsl.routes import register_dsl_routes
    from src.backend.plugins.composition.service_setup import register_all_services

    register_all_services()
    register_action_handlers()
    register_dsl_routes()

    # Wave 1.1 (Roadmap V10): импорт v1 routers триггерит регистрацию
    # Tier 1 CRUD-actions через ``ActionRouterBuilder`` (в дополнение к
    # ручным action handlers выше). Без этого ``manage.py actions`` не
    # отображал бы CRUD-action_id (``orders.list``/``orders.create`` и т.п.).
    try:
        from src.backend.entrypoints.api.v1.routers import get_v1_routers

        get_v1_routers()
    except Exception as exc:  # noqa: BLE001, S110
        logger.debug("get_v1_routers пропущен в bootstrap: %s", exc)


# Public alias for backwards-compat (manage.py used to define ``_bootstrap``).
_bootstrap = bootstrap
