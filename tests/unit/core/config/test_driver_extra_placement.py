"""ADR-0402 — размещение драйверов БД по extras (``pyproject.toml``).

Контракт:

* дефолтный sync-драйвер PostgreSQL (``psycopg``) обязан быть объявлен в
  extra ``db_drivers`` — иначе образ, собранный без extra ``sources-cdc``,
  деградирует sync-движок в ``None`` + warning
  (``infrastructure/database/database/initializer.py``: ``ModuleNotFoundError``
  → ``sync_engine=None``), а durable jobstore APScheduler молча заменяется
  на memory;
* каждый драйвер, объявленный в реестре ``DB_DRIVER_DECLARATIONS`` под extra
  ``db_drivers``, реально присутствует в этом extra в манифесте — реестр и
  ``pyproject.toml`` не расходятся.

Прецедент: ADR-0363 (реестр объявлений драйверов), ADR-0381 (матрица
driver/БД), ADR-0402 (перенос ``psycopg[binary]`` в ``db_drivers``).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.db_drivers import DB_DRIVER_DECLARATIONS

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

_REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _extra_distributions(extra: str) -> set[str]:
    """Имена дистрибутивов, объявленных в extra ``extra`` манифеста.

    Args:
        extra: Имя extra из ``[project.optional-dependencies]``.

    Returns:
        Нормализованные имена дистрибутивов (без версий и extras).

    """
    manifest = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    requirements: list[str] = manifest["project"]["optional-dependencies"][extra]
    names: set[str] = set()
    for requirement in requirements:
        match = _REQUIREMENT_NAME_RE.match(requirement)
        if match is not None:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


@pytest.mark.unit
class TestSyncPostgresDriverPlacement:
    """Sync-PG драйвер обязан быть в extra ``db_drivers`` (ADR-0402)."""

    def test_default_sync_pg_driver_is_declared_in_db_drivers_extra(self) -> None:
        """Дефолтный sync-драйвер PG объявлен в ``db_drivers``.

        До правки ``psycopg[binary]`` жил только в ``sources-cdc`` → образ
        без этого extra деградировал sync-движок в ``None`` + warning.
        """
        default_sync_driver = DatabaseConnectionSettings.model_fields[
            "sync_driver"
        ].default
        assert default_sync_driver == "psycopg"

        declaration = DB_DRIVER_DECLARATIONS[default_sync_driver]
        assert declaration.distribution.lower() in _extra_distributions("db_drivers"), (
            f"sync-драйвер PG '{default_sync_driver}' "
            f"(дистрибутив '{declaration.distribution}') не объявлен в extra "
            "'db_drivers': prod-образ без 'sources-cdc' деградирует "
            "sync-движок в None + warning"
        )

    def test_psycopg_binary_is_in_db_drivers_extra(self) -> None:
        """``psycopg[binary]>=3.1,<4.0.0`` — в extra ``db_drivers``."""
        assert "psycopg" in _extra_distributions("db_drivers")

    def test_db_drivers_extra_covers_all_registered_drivers(self) -> None:
        """Реестр и манифест согласованы: всё из ``db_drivers`` — в реестре.

        Защищает от «висячей» записи в extra: дистрибутив из манифеста обязан
        быть известен реестру ``DB_DRIVER_DECLARATIONS`` (иначе рантайм-guard
        не сможет выдать подсказку «какой extra доустановить»).
        """
        known = {
            declaration.distribution.lower().replace("_", "-")
            for declaration in DB_DRIVER_DECLARATIONS.values()
        }
        for distribution in sorted(_extra_distributions("db_drivers")):
            assert distribution in known, (
                f"дистрибутив '{distribution}' объявлен в extra 'db_drivers', "
                "но отсутствует в реестре DB_DRIVER_DECLARATIONS"
            )
