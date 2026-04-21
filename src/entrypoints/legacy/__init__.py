"""Legacy-коннекторы (opt-in `gdi[legacy]`) — C10.

* TN3270 — через `py3270` (мейнфрейм-эмуляция).
* TN5250 — через `pytn5250`.
* ISO8583 — используется codec (C9 / gdi[banking]).
"""

__all__ = ("is_legacy_available",)


def is_legacy_available() -> bool:
    try:
        import py3270  # noqa: F401

        return True
    except ImportError:
        return False
