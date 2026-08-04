"""Регрессии для plugin/route scaffold defaults (Scope 2, Cycle 50)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_test_plug_manifest_compatible_with_project_core() -> None:
    """test_plug/plugin.toml совместим с текущим core 0.20.x."""
    raw = tomllib.loads(
        (_PROJECT_ROOT / "extensions/test_plug/plugin.toml").read_text(
            encoding="utf-8"
        )
    )
    assert raw["requires_core"] == ">=0.20,<0.21"
    assert raw["entry_class"].endswith("TestPlugPlugin")
    # PEP 440 проверка, без импорта pydantic-моделей core.
    from packaging.specifiers import SpecifierSet

    spec = SpecifierSet(raw["requires_core"])
    assert "0.20.0" in spec
    assert "0.21.0" not in spec


def test_test_plug_plugin_module_resolves_base_plugin_via_core_interfaces() -> None:
    """extensions/test_plug/plugin.py использует канонический ``BasePlugin``."""
    source = (_PROJECT_ROOT / "extensions/test_plug/plugin.py").read_text(
        encoding="utf-8"
    )
    compile(source, "extensions/test_plug/plugin.py", "exec")
    assert (
        "from src.backend.core.interfaces.plugin import BasePlugin" in source
    )


def test_plugin_wizard_default_requires_core_matches_project() -> None:
    """plugin_wizard runtime output синхронизирован с pyproject.toml 0.20.x.

    Round 11 fix: проверяем RUNTIME output через ``_build_toml()``, а не
    исходник (потому что Round 8 ввёл ``_default_requires_core()`` helper,
    который динамически вычисляет constraint из ``pyproject.toml`` —
    literal string ``">=0.20,<0.21"`` в source не появляется, но runtime
    output его содержит).
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "plugin_wizard_mod", _PROJECT_ROOT / "tools/wizards/plugin_wizard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    raw = module._build_toml(
        "test_default", description="x", tenant_aware=True, trust_tier="B"
    )
    parsed = tomllib.loads(raw)
    assert parsed["requires_core"] == ">=0.20,<0.21"
    assert ">=22.0,<23" not in raw
    assert ">=0.2,<0.3" not in raw


def test_route_wizard_default_requires_core_matches_project() -> None:
    """route_wizard runtime output синхронизирован с pyproject.toml 0.20.x.

    Round 11 fix: проверяем RUNTIME output аналогично plugin_wizard
    (см. comment в ``test_plugin_wizard_default_requires_core_matches_project``).
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "route_wizard_mod", _PROJECT_ROOT / "tools/wizards/route_wizard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    raw = module._build_toml(
        "test_default",
        ai=False,
        retry=False,
        tenant_aware=True,
        p95_ms=200,
        timeout_ms=5000,
    )
    assert 'requires_core = ">=0.20,<0.21"' in raw
    assert ">=22.0,<23" not in raw
    assert ">=0.2,<0.3" not in raw


def test_plugin_template_default_matches_project_core_version() -> None:
    """tools/templates/plugin.toml.j2 синхронизирован с core 0.20.x."""
    template = (_PROJECT_ROOT / "tools/templates/plugin.toml.j2").read_text(
        encoding="utf-8"
    )
    match = re.search(r'requires_core\s*=\s*"([^"]+)"', template)
    assert match is not None
    assert match.group(1) == ">=0.20,<0.21"
