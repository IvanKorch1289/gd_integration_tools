"""D-AUDIT-FIX-184-5 regression test — plugin.toml trust_tier required.

Closes D-AUDIT-FIX-184-5 (S184 W4 #5): extensions/{core_admin,dadata,skb}
were missing trust_tier key. Pre-prod-check #33 requires it for
plugin trust-tier validation.

Strict-test policy per D-LESSON-11: NO lax assertions.
"""

from __future__ import annotations

import re
from pathlib import Path

EXTENSIONS = ["core_admin", "dadata", "skb"]
REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_plugin_toml(name: str) -> str:
    path = REPO_ROOT / "extensions" / name / "plugin.toml"
    return path.read_text(encoding="utf-8")


def test_core_admin_has_trust_tier() -> None:
    """core_admin plugin.toml MUST have trust_tier (was missing pre-fix)."""
    content = _read_plugin_toml("core_admin")
    match = re.search(r'trust_tier\s*=\s*"([ABC])"', content)
    assert match is not None, (
        "D-AUDIT-FIX-184-5: core_admin/plugin.toml missing trust_tier. "
        "Got:\n" + content
    )


def test_dadata_has_trust_tier() -> None:
    """dadata plugin.toml MUST have trust_tier."""
    content = _read_plugin_toml("dadata")
    match = re.search(r'trust_tier\s*=\s*"([ABC])"', content)
    assert match is not None, (
        "D-AUDIT-FIX-184-5: dadata/plugin.toml missing trust_tier. "
        "Got:\n" + content
    )


def test_skb_has_trust_tier() -> None:
    """skb plugin.toml MUST have trust_tier."""
    content = _read_plugin_toml("skb")
    match = re.search(r'trust_tier\s*=\s*"([ABC])"', content)
    assert match is not None, (
        "D-AUDIT-FIX-184-5: skb/plugin.toml missing trust_tier. "
        "Got:\n" + content
    )


def test_all_three_plugins_have_consistent_trust_tier() -> None:
    """All 3 plugins: trust_tier = 'A' (audited), consistent with credit_pipeline."""
    for name in EXTENSIONS:
        content = _read_plugin_toml(name)
        match = re.search(r'trust_tier\s*=\s*"([ABC])"', content)
        assert match is not None, (
            "D-AUDIT-FIX-184-5: " + name + " missing trust_tier key"
        )
        # Currently all set to "A" (audited). Re-test if tier changes.
        # (If changing to mixed tiers, update this assertion.)
        assert match.group(1) == "A", (
            "D-AUDIT-FIX-184-5: " + name + " trust_tier is "
            + match.group(1) + ", expected A. Update this test if intentional."
        )
