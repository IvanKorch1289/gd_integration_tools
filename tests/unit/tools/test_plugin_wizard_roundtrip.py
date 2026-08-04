"""Round-trip регрессии для plugin wizard (Sprint 8 Extensions 2).

Проверяют, что:

1. ``tools/wizards/plugin_wizard.py::_build_toml`` генерирует парсибельный
   ``plugin.toml`` с валидными SemVer ``version`` и PEP 440 ``requires_core``.
2. ``_write_scaffold`` пишет все три файла (``plugin.toml``/``__init__.py``/
   ``plugin.py``); записанный ``plugin.toml`` парсится обратно и остаётся
   валидным (semver + PEP 440 + ``provides`` inventory).
3. Канонический facade ``core.plugin_runtime.manifest.load_plugin_manifest``
   принимает wizard-вывод без исключений (используется как источник правды
   для runtime plugin loader).

Не делает cross-sprint правок (default ``requires_core`` остаётся как в
wizard S33 W2; mismatch с core 0.20.x — отдельный scope).
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]

# Round 8 fix: import default-constraint helper at module level для DRY
# (все тесты используют ``_default_requires_core()`` вместо хардкоженного
# ``">=22.0,<23"`` который не соответствует semver-схеме ``0.20.0``).
sys.path.insert(0, str(_ROOT))
from tools.wizards.plugin_wizard import _default_requires_core  # noqa: E402

# SemVer X.Y.Z с опциональным pre-release суффиксом — синхронизирован с
# ``src/backend/core/plugin_runtime/semver_checker._SEMVER_RE``.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*)?$")


def _load_wizard():
    """Загружает plugin wizard через importlib (tools/ не package).

    Returns:
        Модуль ``plugin_wizard_mod``.
    """
    src = _ROOT / "tools" / "wizards" / "plugin_wizard.py"
    spec = importlib.util.spec_from_file_location("plugin_wizard_mod", src)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["plugin_wizard_mod"] = module
    spec.loader.exec_module(module)
    return module


_wizard = _load_wizard()


@pytest.fixture
def isolated_extensions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Подменяет глобальный ``EXTENSIONS_DIR`` wizard на временную папку.

    Yields:
        Временная директория, в которую ``_write_scaffold`` пишет scaffold.
    """
    monkeypatch.setattr(_wizard, "EXTENSIONS_DIR", tmp_path)
    return tmp_path


# ─── 1. ``_build_toml`` ─ корректный TOML с валидными полями ──────────────


def test_build_toml_is_parseable_toml_with_valid_semver_and_pep440() -> None:
    """_build_toml → строка → tomllib.loads → version/requires_core валидны.

    version соответствует SemVer X.Y.Z(-pre)? и парсится ``packaging.version``.
    requires_core парсится ``packaging.specifiers.SpecifierSet`` (PEP 440).
    """
    raw = _wizard._build_toml(
        "credit_pipeline",
        description="Credit pipeline plugin",
        tenant_aware=True,
        trust_tier="A",
    )

    data = tomllib.loads(raw)
    assert data["name"] == "credit_pipeline"
    assert data["version"] == "0.1.0"
    assert data["requires_core"] == _default_requires_core()
    assert (
        data["entry_class"] == "extensions.credit_pipeline.plugin.CreditPipelinePlugin"
    )
    assert data["tenant_aware"] is True
    assert data["trust_tier"] == "A"
    assert data["description"] == "Credit pipeline plugin"
    assert data["provides"] == {
        "actions": [],
        "repositories": [],
        "processors": [],
        "sources": [],
        "sinks": [],
        "schemas": [],
    }

    # SemVer X.Y.Z(-pre)? — must match wizard-emitted "0.1.0".
    assert _SEMVER_RE.match(data["version"]), (
        f"version {data['version']!r} не соответствует SemVer X.Y.Z"
    )

    # packaging.version — strict PEP 440 parser.
    from packaging.version import Version

    Version(data["version"])  # raises InvalidVersion при некорректной строке

    # packaging.specifiers — PEP 440 specifier set.
    from packaging.specifiers import SpecifierSet

    SpecifierSet(data["requires_core"])  # raises InvalidSpecifier при мусоре


@pytest.mark.parametrize(
    ("name", "trust_tier"), [("foo", "A"), ("bar_baz", "B"), ("snake_case_name", "C")]
)
def test_build_toml_emits_snake_case_to_pascal_case_entry_class(
    name: str, trust_tier: str
) -> None:
    """entry_class формируется по snake_case → PascalCase через ``str.title()``."""
    raw = _wizard._build_toml(
        name, description="x", tenant_aware=False, trust_tier=trust_tier
    )
    data = tomllib.loads(raw)
    expected_class = "".join(part.title() for part in name.split("_")) + "Plugin"
    assert data["entry_class"] == f"extensions.{name}.plugin.{expected_class}"
    assert data["tenant_aware"] is False
    assert data["trust_tier"] == trust_tier


# ─── 2. Round-trip через ``_write_scaffold`` ──────────────────────────────


def test_write_scaffold_round_trip_plugin_toml_is_parseable(
    isolated_extensions_dir: Path,
) -> None:
    """Генерация → запись → чтение → tomllib → manifest корректный."""
    target = _wizard._write_scaffold(
        "round_trip_plugin",
        "Round-trip test plugin",
        tenant_aware=True,
        trust_tier="B",
        force=True,
    )

    toml_path = target / "plugin.toml"
    assert toml_path.exists()
    raw = toml_path.read_text(encoding="utf-8")

    data = tomllib.loads(raw)
    assert data["name"] == "round_trip_plugin"
    assert data["version"] == "0.1.0"
    assert data["requires_core"] == _default_requires_core()
    assert data["entry_class"] == (
        "extensions.round_trip_plugin.plugin.RoundTripPluginPlugin"
    )
    assert data["tenant_aware"] is True
    assert data["trust_tier"] == "B"
    assert data["description"] == "Round-trip test plugin"
    assert set(data["provides"]) == {
        "actions",
        "repositories",
        "processors",
        "sources",
        "sinks",
        "schemas",
    }

    # SemVer + PEP 440 — must round-trip без потери валидности.
    assert _SEMVER_RE.match(data["version"])
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    Version(data["version"])
    SpecifierSet(data["requires_core"])


def test_write_scaffold_creates_all_three_files(isolated_extensions_dir: Path) -> None:
    """_write_scaffold пишет ровно 3 файла: plugin.toml, __init__.py, plugin.py."""
    target = _wizard._write_scaffold(
        "three_files_plugin",
        "Three files",
        tenant_aware=False,
        trust_tier="C",
        force=True,
    )

    created = sorted(p.name for p in target.iterdir())
    assert created == ["__init__.py", "plugin.py", "plugin.toml"]

    # __init__.py — компилируется как Python-модуль.
    init_src = (target / "__init__.py").read_text(encoding="utf-8")
    compile(init_src, str(target / "__init__.py"), "exec")

    # plugin.py — компилируется; entry class наследует ``BasePlugin``.
    plugin_src = (target / "plugin.py").read_text(encoding="utf-8")
    compile(plugin_src, str(target / "plugin.py"), "exec")
    assert "BasePlugin" in plugin_src
    # Wizard S33 W2 добавляет суффикс ``Plugin`` к PascalCase-имени,
    # поэтому для ``three_files_plugin`` ожидаем ``ThreeFilesPluginPlugin``.
    assert "class ThreeFilesPluginPlugin(BasePlugin):" in plugin_src
    assert plugin_src.count("def healthcheck") == 1


def test_write_scaffold_default_requires_core_matches_wizard(
    isolated_extensions_dir: Path,
) -> None:
    """Default ``requires_core`` — синхронизировано с pyproject.toml::version.

    Round 8 fix: wizard читает ``[project].version`` из ``pyproject.toml``
    и формирует ``">=X.Y,<X.(Y+1)"``. Не хардкодим значение (был баг
    ``">=22.0,<23"`` не соответствующий semver-схеме ``0.20.0``).
    """
    expected = _default_requires_core()
    target = _wizard._write_scaffold(
        "default_requires",
        "Default requires",
        tenant_aware=True,
        trust_tier="B",
        force=True,
    )
    data = tomllib.loads((target / "plugin.toml").read_text(encoding="utf-8"))
    assert data["requires_core"] == expected

    from packaging.specifiers import SpecifierSet

    spec = SpecifierSet(data["requires_core"])
    # Дефолтный requires_core синтаксически валиден как PEP 440.
    assert spec is not None


def test_write_scaffold_refuses_overwrite_without_force(
    isolated_extensions_dir: Path,
) -> None:
    """Повторный вызов без ``force=True`` поднимает ``FileExistsError``."""
    _wizard._write_scaffold(
        "no_force_plugin", "No force", tenant_aware=True, trust_tier="B", force=True
    )

    with pytest.raises(FileExistsError):
        _wizard._write_scaffold(
            "no_force_plugin",
            "No force",
            tenant_aware=True,
            trust_tier="B",
            force=False,
        )


# ─── 3. Совместимость с каноническим facade ``load_plugin_manifest`` ──────


def test_wizard_output_is_accepted_by_canonical_manifest_facade(
    isolated_extensions_dir: Path,
) -> None:
    """``core.plugin_runtime.manifest.load_plugin_manifest`` парсит wizard TOML.

    Это runtime-фасад, который использует plugin loader (extensions / loader
    layer). Если wizard-output не проходит facade — runtime отклонит плагин.
    """
    from src.backend.core.plugin_runtime.manifest import load_plugin_manifest

    target = _wizard._write_scaffold(
        "facade_compat", "Facade compat", tenant_aware=True, trust_tier="A", force=True
    )

    manifest = load_plugin_manifest(target / "plugin.toml")

    assert manifest.name == "facade_compat"
    assert manifest.version == "0.1.0"
    assert manifest.requires_core == _default_requires_core()
    assert manifest.entry_class == (
        "extensions.facade_compat.plugin.FacadeCompatPlugin"
    )
    assert manifest.tenant_aware is True
    assert manifest.trust_tier == "A"
    assert manifest.description == "Facade compat"

    # is_compatible_with_core — facade-метод; PEP 440 specifier парсится.
    # Round 8 fix: default constraint теперь синхронизирован с core
    # ``0.20.x`` semver-схемой (а не хардкоженный ``">=22.0,<23"``).
    expected_constraint = _default_requires_core()
    # Извлекаем minor из constraint вида ">=X.Y,<X.(Y+1)".
    minor_match = re.search(r">=(\d+)\.(\d+),", expected_constraint)
    assert minor_match is not None, f"unexpected constraint: {expected_constraint}"
    base_minor = int(minor_match.group(2))
    next_minor = base_minor + 1
    assert manifest.is_compatible_with_core(f"0.{base_minor}.5") is True
    assert manifest.is_compatible_with_core(f"0.{base_minor - 1}.99") is False
    assert manifest.is_compatible_with_core(f"0.{next_minor}.0") is False


# ─── 4. Sanity: сырой TOML через ``tempfile`` (без ``_write_scaffold``) ──


def test_build_toml_round_trip_via_tempfile() -> None:
    """_build_toml → write_text → read_text → tomllib → SemVer/PEP 440 валидны.

    Это «чистый» round-trip без wizard-файловой системы, чтобы регрессия
    покрывала только контракт ``_build_toml``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "plugin.toml"
        raw = _wizard._build_toml(
            "alpha_beta", description="Alpha beta", tenant_aware=True, trust_tier="B"
        )
        path.write_text(raw, encoding="utf-8")
        data = tomllib.loads(path.read_text(encoding="utf-8"))

    assert data["name"] == "alpha_beta"
    assert data["entry_class"] == "extensions.alpha_beta.plugin.AlphaBetaPlugin"
    assert _SEMVER_RE.match(data["version"])

    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    Version(data["version"])
    SpecifierSet(data["requires_core"])
