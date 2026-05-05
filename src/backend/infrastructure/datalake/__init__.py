"""Data lake + CDC (I2, ADR-016): Iceberg/Delta + CDC + Temporal + Beam.

Scaffold-уровень: публичные адаптеры. Конкретные driverы подключаются
через extras `gdi[datalake]`.
"""

from __future__ import annotations

__all__ = ("is_datalake_available",)


def is_datalake_available() -> bool:
    try:
        import pyiceberg  # noqa: F401

        return True
    except ImportError:
        return False
