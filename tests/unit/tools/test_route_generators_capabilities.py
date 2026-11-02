"""ADR-0415 — гейт генераторов ``route.toml``: только каноничная форма.

Генераторы манифеста роута обязаны выдавать манифест, который:

* читается штатным ``load_route_manifest`` **без** legacy-предупреждения
  (ADR-0405 объявил плоскую форму ``capabilities = [...]`` deprecated);
* объявляет capability таблицами ``[[route.capabilities]]`` с отдельными
  ``name``/``scope``, где имя есть в vocabulary, а scope непустой;
* проходит capability-гейт: ``RouteLoader`` загружает роут, а не отклоняет
  его с ``capability_superset``.

Проверяются все три генератора репозитория: ``tools/scaffold_route.py``,
``tools/wizards/route_templates.py`` и ``tools/wizards/route_wizard.py``.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
import warnings
from pathlib import Path
from typing import Any

import pytest

from src.backend.core.security.capabilities import (
    CapabilityGate,
    build_default_vocabulary,
)
from src.backend.services.routes.loader import RouteLoader
from src.backend.services.routes.manifest_toml import load_route_manifest

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_VERSION = "0.20.0"

_MINIMAL_DSL = "route_id: demo_route\nsource:\n  http:\n    method: POST\n    path: /api/v1/demo\nsteps: []\n"


def _load_module(path: Path, name: str) -> Any:
    """Загрузить tools-модуль по пути (как это делают существующие тесты)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scaffold = _load_module(
    REPO_ROOT / "tools" / "scaffold_route.py", "_scaffold_route_gen"
)
templates = _load_module(
    REPO_ROOT / "tools" / "wizards" / "route_templates.py", "_route_templates_gen"
)
wizard = _load_module(
    REPO_ROOT / "tools" / "wizards" / "route_wizard.py", "_route_wizard_gen"
)


def _generators() -> list[tuple[str, str]]:
    """(имя генератора, TOML-текст) для всех вариантов конфигурации."""
    return [
        ("scaffold/http", scaffold.build_route_toml(name="demo_route", ai=False)),
        (
            "scaffold/db",
            scaffold.build_route_toml(name="demo_route", ai=False, sink="db"),
        ),
        (
            "scaffold/kafka",
            scaffold.build_route_toml(name="demo_route", ai=True, sink="kafka"),
        ),
        ("templates/http", templates.build_route_toml(name="demo_route", ai=False)),
        (
            "templates/db",
            templates.build_route_toml(name="demo_route", ai=True, sink="db"),
        ),
        (
            "wizard/http",
            wizard._build_toml(
                "demo_route",
                ai=False,
                retry=False,
                tenant_aware=True,
                p95_ms=500,
                timeout_ms=5000,
            ),
        ),
        (
            "wizard/db",
            wizard._build_toml(
                "demo_route",
                ai=True,
                retry=True,
                tenant_aware=True,
                p95_ms=500,
                timeout_ms=5000,
                sink="db",
            ),
        ),
    ]


class TestNoLegacyCapabilityForm:
    """Legacy-форма ``capabilities = [...]`` не генерируется."""

    @pytest.mark.parametrize(("label", "text"), _generators())
    def test_no_flat_capability_list(self, label: str, text: str) -> None:
        """В манифесте нет плоского списка строк-capability."""
        raw = tomllib.loads(text)
        assert "capabilities" not in raw, label
        envelope = raw["route"]
        assert isinstance(envelope["capabilities"], list), label
        assert all(isinstance(item, dict) for item in envelope["capabilities"]), label

    @pytest.mark.parametrize(("label", "text"), _generators())
    def test_no_legacy_string_capability(self, label: str, text: str) -> None:
        """Ни одна capability не объявлена строкой ``"name"`` / ``"name:scope"``."""
        raw = tomllib.loads(text)
        for entry in raw["route"]["capabilities"]:
            assert isinstance(entry, dict), label
            assert set(entry) == {"name", "scope"}, (label, entry)
            assert ":" not in entry["name"], (label, entry)

    @pytest.mark.parametrize(("label", "text"), _generators())
    def test_manifest_loads_without_legacy_warning(
        self, label: str, text: str, tmp_path: Path
    ) -> None:
        """Манифест читается штатным загрузчиком и не триггерит legacy-warning."""
        path = tmp_path / f"{label.replace('/', '_')}.toml"
        path.write_text(text, encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manifest = load_route_manifest(path)
        legacy = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert legacy == [], (label, [str(w.message) for w in legacy])
        assert manifest.name == "demo_route"


class TestCapabilitySemantics:
    """Capability генерируются по семантике vocabulary."""

    @pytest.mark.parametrize(("label", "text"), _generators())
    def test_names_in_vocabulary_and_scope_not_empty(
        self, label: str, text: str
    ) -> None:
        """Имя capability есть в vocabulary, scope — непустая строка."""
        vocabulary = build_default_vocabulary()
        raw = tomllib.loads(text)
        for entry in raw["route"]["capabilities"]:
            assert vocabulary.has(entry["name"]), (label, entry)
            assert entry["scope"].strip(), (label, entry)

    @pytest.mark.parametrize(("label", "text"), _generators())
    def test_audit_write_always_declared(self, label: str, text: str) -> None:
        """Шаг ``audit:`` есть в каждом pipeline → ``audit.write`` объявлена."""
        raw = tomllib.loads(text)
        names = {
            entry["name"]: entry["scope"] for entry in raw["route"]["capabilities"]
        }
        assert names.get("audit.write") == "audit:*", label

    def test_net_outbound_scope_is_host(self) -> None:
        """``net.outbound`` объявляется с host'ом, а не с glob'ом/пустым scope."""
        raw = tomllib.loads(scaffold.build_route_toml(name="demo_route", ai=False))
        names = {
            entry["name"]: entry["scope"] for entry in raw["route"]["capabilities"]
        }
        assert names["net.outbound"] == "api.test"

    def test_db_write_scope_is_resource_alias(self) -> None:
        """``db.write`` объявляется с алиасом ресурса (ExactAliasMatcher)."""
        raw = tomllib.loads(
            scaffold.build_route_toml(name="demo_route", ai=False, sink="db")
        )
        names = {
            entry["name"]: entry["scope"] for entry in raw["route"]["capabilities"]
        }
        assert names["db.write"] == "CHANGEME"

    @pytest.mark.parametrize(("label", "text"), _generators())
    def test_no_capability_outside_vocabulary(self, label: str, text: str) -> None:
        """Никаких «ai.llm» / «retry.enabled» — их нет в vocabulary."""
        raw = tomllib.loads(text)
        names = {entry["name"] for entry in raw["route"]["capabilities"]}
        assert "ai.llm" not in names, label
        assert "retry.enabled" not in names, label


class TestGeneratedRouteLoads:
    """Сгенерированный роут грузится ``RouteLoader``'ом."""

    @pytest.mark.parametrize(("label", "text"), _generators())
    async def test_route_loader_enables_generated_route(
        self, label: str, text: str, tmp_path: Path
    ) -> None:
        """Capability-гейт не отклоняет сгенерированный роут."""
        route_dir = tmp_path / label.replace("/", "_")
        route_dir.mkdir(parents=True)
        (route_dir / "route.toml").write_text(text, encoding="utf-8")
        (route_dir / "main.dsl.yaml").write_text(_MINIMAL_DSL, encoding="utf-8")

        loader = RouteLoader(
            routes_dir=tmp_path,
            capability_gate=CapabilityGate(),
            vocabulary=build_default_vocabulary(),
            core_version=CORE_VERSION,
            installed_plugins={},
            pipeline_registrar=lambda *_args, **_kwargs: None,
            feature_flag_resolver=lambda _flag: True,
            strict_capabilities=True,
        )
        await loader.discover_and_load()
        loaded = {route.name: route for route in loader.loaded}
        route = loaded["demo_route"]
        assert route.status == "enabled", (label, route.reason)
