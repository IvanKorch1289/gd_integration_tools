"""D-AUDIT-FIX-184-2 regression test — openfeature_external default-OFF.

Closes D-AUDIT-FIX-184-2 (S184 W4 #2). Pre-fix drift:
``default=True`` paired with "default-OFF" string in description.
Post-fix: code matches docstring.
"""

from __future__ import annotations

from src.backend.core.config.features.experimental import ExperimentalFlags


def test_openfeature_external_default_is_false() -> None:
    """Per fix: code default matches docstring 'default-OFF'."""
    flags = ExperimentalFlags()
    assert flags.openfeature_external is False, (
        "D-AUDIT-FIX-184-2: code default=True contradicted docstring 'default-OFF'. "
        "Fix flipped to False to match documented intent."
    )
