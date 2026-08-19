"""Regression-блокировка для NEW-1b/NEW-2 fix: DI repos mapping.

Pre-NEW-1b: ``_MODULE_REGISTRY`` для ``repos.files`` /
``repos.orders`` указывал на ``src.backend.infrastructure.repositories.{files,orders}``
— НЕСУЩЕСТВУЮЩИЕ модули. Любой инжект через ``repos.files`` / ``repos.orders``
→ ``ModuleNotFoundError: No module named 'src.backend.infrastructure.repositories.files'``.

NEW-1b fix (2026-08-13): изменены маппинги:
- ``repos.files`` → ``extensions.core_entities.files.repositories.files``
- ``repos.orders`` → ``extensions.core_entities.orders.repositories.orders``

Эти extensions — actual implementations (per extensions/core_entities/*/repositories/*).

Тесты:

1. ``repos.files`` маппинг указывает на существующий extension module.
2. ``repos.orders`` маппинг указывает на существующий extension module.
3. ``repos.connector_configs`` НЕ затронут (был корректный с самого начала).
"""

from __future__ import annotations


def test_repos_files_mapping_points_to_extension() -> None:
    """``repos.files`` → ``extensions.core_entities.files.repositories.files``.

    Pre-NEW-1b указывало на несуществующий ``src.backend.infrastructure.repositories.files``
    (ModuleNotFoundError при resolve_module).
    """
    from src.backend.core.di import module_registry

    target = module_registry.INFRA_MODULES.get("repos.files")
    assert target == "extensions.core_entities.files.repositories.files", (
        f"NEW-1b fix regressed: repos.files → {target!r}, "
        f"expected 'extensions.core_entities.files.repositories.files'"
    )


def test_repos_orders_mapping_points_to_extension() -> None:
    """``repos.orders`` → ``extensions.core_entities.orders.repositories.orders``.

    Pre-NEW-1b указывало на несуществующий ``src.backend.infrastructure.repositories.orders``.
    """
    from src.backend.core.di import module_registry

    target = module_registry.INFRA_MODULES.get("repos.orders")
    assert target == "extensions.core_entities.orders.repositories.orders", (
        f"NEW-1b fix regressed: repos.orders → {target!r}, "
        f"expected 'extensions.core_entities.orders.repositories.orders'"
    )


def test_repos_connector_configs_unchanged() -> None:
    """``repos.connector_configs`` остался на _INFRA.repositories (был корректный).

    Sanity check — NEW-1b fix не должен сломать уже-работающие маппинги.
    """
    from src.backend.core.di import module_registry

    target = module_registry.INFRA_MODULES.get("repos.connector_configs")
    assert target is not None, "repos.connector_configs missing"
    assert "src.backend.infrastructure" in target, (
        f"repos.connector_configs should remain on _INFRA: got {target!r}"
    )
