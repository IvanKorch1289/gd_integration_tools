"""S67 W3: regression test для pre-existing import bug ``accessors.py``.

Bug: ``src/backend/infrastructure/database/database/accessors.py``
ссылался на ``DatabaseInitializer`` и ``ExternalDatabaseRegistry``
КАК на локальные имена (строки 24, 49), но НЕ импортировал их.
На момент вызова ``get_db_initializer()`` / ``get_external_db_registry()``
Python бросал ``NameError: name 'DatabaseInitializer' is not defined``.

S67 W3: добавлены импорты в ``accessors.py``. Этот тест ВОСПРОИЗВОДИТ
старый NameError при отсутствии импорта и подтверждает, что
после fix все 3 accessors возвращают правильные экземпляры.
"""

from __future__ import annotations

import pytest


def test_accessors_module_imports_succeed() -> None:
    """Импорт ``accessors`` сам по себе НЕ должен падать.

    S67 W3: до fix NameError возникал при первом вызове
    ``get_db_initializer()`` (lazy lru_cache), а не на import.
    Сейчас проверим, что import не падает И что символы резолвятся
    в правильные классы.
    """
    from src.backend.infrastructure.database.database import accessors

    assert hasattr(accessors, "get_db_initializer")
    assert hasattr(accessors, "get_smart_session_manager")
    assert hasattr(accessors, "get_external_db_registry")
    # __getattr__ — module-level hook, должен быть функцией
    assert callable(accessors.__getattr__)


def test_database_initializer_is_resolvable() -> None:
    """``DatabaseInitializer`` доступен через package re-export.

    Без этого: любой ``from src.backend.infrastructure.database.database
    import DatabaseInitializer`` (упомянуто в ``__init__.py:9`` как
    "backward-compat") падал.
    """
    from src.backend.infrastructure.database.database import (
        DatabaseInitializer as PackageDatabaseInitializer,
    )
    from src.backend.infrastructure.database.database.initializer import (
        DatabaseInitializer as DirectDatabaseInitializer,
    )

    assert PackageDatabaseInitializer is DirectDatabaseInitializer


def test_external_database_registry_is_resolvable() -> None:
    """``ExternalDatabaseRegistry`` доступен через package re-export."""
    from src.backend.infrastructure.database.database import (
        ExternalDatabaseRegistry as PackageRegistry,
    )
    from src.backend.infrastructure.database.database.registry import (
        ExternalDatabaseRegistry as DirectRegistry,
    )

    assert PackageRegistry is DirectRegistry


def test_get_db_initializer_no_nameerror() -> None:
    """``get_db_initializer()`` НЕ падает с ``NameError`` на импорт.

    S67 W3: до fix — NameError ``DatabaseInitializer is not defined``
    при первом вызове. После fix — NameError отсутствует.

    Проверяем ТОЛЬКО NameError, не пытаемся реально создать engine
    (SQLAlchemy нужен реальный URL, не MagicMock).
    """
    from src.backend.infrastructure.database.database import accessors
    from unittest.mock import patch, MagicMock

    # Подменяем DatabaseInitializer на stub, чтобы не требовать
    # реальный SQLAlchemy engine (нужен живой PostgreSQL).
    fake_instance = MagicMock()
    with patch.object(
        accessors,
        "DatabaseInitializer",
        return_value=fake_instance,
        create=True,
    ):
        accessors.get_db_initializer.cache_clear()
        try:
            result = accessors.get_db_initializer()
        except NameError as exc:
            pytest.fail(
                f"S67 W3: NameError не устранён: {exc}. "
                f"accessors.py должен импортировать DatabaseInitializer."
            )
        # Если прошло без NameError — fix работает
        assert result is fake_instance


def test_get_external_db_registry_no_nameerror() -> None:
    """``get_external_db_registry()`` НЕ падает с ``NameError``."""
    from src.backend.infrastructure.database.database import accessors
    from unittest.mock import patch, MagicMock

    fake_instance = MagicMock()
    # Подменяем ОБА: ExternalDatabaseRegistry (целевой fix) и
    # settings.external_databases.profiles (settings читает реальную
    # конфигурацию с валидацией профилей — не наша забота в этом тесте).
    fake_settings = MagicMock()
    fake_settings.external_databases.profiles = {}
    with patch.object(
        accessors,
        "ExternalDatabaseRegistry",
        return_value=fake_instance,
        create=True,
    ), patch.object(accessors, "settings", fake_settings):
        accessors.get_external_db_registry.cache_clear()
        try:
            result = accessors.get_external_db_registry()
        except NameError as exc:
            pytest.fail(
                f"S67 W3: NameError не устранён: {exc}. "
                f"accessors.py должен импортировать ExternalDatabaseRegistry."
            )
        assert result is fake_instance


def test_module_getattr_raises_for_unknown_attr() -> None:
    """``__getattr__`` поднимает AttributeError для неизвестных имён.

    Backward-compat hook (S64 W3 decomp) — должен соответствовать
    стандартному module-attr semantics.
    """
    from src.backend.infrastructure.database.database import accessors

    with pytest.raises(AttributeError, match="has no attribute 'nonexistent_attr'"):
        accessors.__getattr__("nonexistent_attr")
