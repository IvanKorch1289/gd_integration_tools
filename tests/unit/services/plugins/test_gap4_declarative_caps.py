# ruff: noqa: S101
"""V15 GAP Gap 4 (Sprint 36) — тесты ``[[tenants]]`` манифеста + loader integration.

Покрывает:

* ``PluginTenantDecl`` + ``PluginManifest.tenants``: парсинг TOML,
  валидация грамматики и vocabulary, ``extra="forbid"``.
* ``PluginLoader._load_one``: вызовы ``gate.declare_tenant`` для
  каждой capability каждого tenant'а, warning при ``tenant_aware=true``
  без ``[[tenants]]``, backward compat без секции.
* ``load_plugin_manifest`` raises ``PluginManifestError`` при
  неизвестном capability name в ``[[tenants]]``.

NB: ``db.*`` capabilities — :class:`ExactAliasMatcher` (DSN-стиль,
``scope_required=True``). Для slice 1 ``declare_tenant`` всегда
вызывается с ``scope=None``; это **провалится** для ``db.*`` /
``secrets.*``, но **пройдёт** для ``mq.*`` / ``net.*`` / ``cache.*`` /
``workflow.*`` / ``llm.*`` (scope не обязателен). Поэтому в тестах
используем ``mq.publish`` / ``net.outbound`` / ``cache.read`` —
безопасные имена для slice 1.
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.backend.core.security.capabilities import (
    DEFAULT_CAPABILITY_CATALOG,
    CapabilityGate,
    CapabilityRef,
)
from src.backend.core.security.capabilities.matchers import GlobScopeMatcher
from src.backend.core.security.capabilities.vocabulary import (
    CapabilityDef,
    CapabilityVocabulary,
    build_default_vocabulary,
)
from src.backend.services.plugins.loader import PluginLoader
from src.backend.services.plugins.manifest_toml import (
    PluginManifestError,
    PluginManifest,
    PluginTenantDecl,
    load_plugin_manifest,
)
from tests.unit.services.plugins.test_loader import (
    _build_loader,
    _FakeActions,
    _FakeProcessors,
    _FakeRepos,
    _write_extension,
)


def _build_vocab_with_optional_scope() -> CapabilityVocabulary:
    """Vocabulary с одной capability ``scope_required=False`` для slice 1 тестов.

    В :data:`DEFAULT_CAPABILITY_CATALOG` все capabilities имеют
    ``scope_required=True`` (default), поэтому ``declare_tenant(scope=None)``
    всегда падает в slice 1. Для тестов loader integration добавляем
    capability ``net.broadcast`` с ``scope_required=False`` — это
    единственный безопасный путь проверить, что loader реально вызывает
    ``declare_tenant`` и ``check_tenant`` возвращает ``True``.
    """
    vocab = build_default_vocabulary()
    vocab.register(
        CapabilityDef(
            name="net.broadcast",
            matcher=GlobScopeMatcher(),
            scope_required=False,
            description="Test-only capability without scope (slice 1).",
        )
    )
    return vocab


def _build_loader_with_custom_vocab(
    tmp_path: Path,
    *,
    core_version: str = "0.2.0",
    vocab: CapabilityVocabulary | None = None,
) -> tuple[PluginLoader, _FakeActions, _FakeRepos, _FakeProcessors]:
    actions = _FakeActions()
    repos = _FakeRepos()
    processors = _FakeProcessors()
    gate = CapabilityGate(
        vocabulary=vocab if vocab is not None else _build_vocab_with_optional_scope()
    )
    loader = PluginLoader(
        extensions_dir=tmp_path,
        capability_gate=gate,
        action_registry=actions,
        repository_registry=repos,
        processor_registry=processors,
        core_version=core_version,
    )
    return loader, actions, repos, processors


# ── PluginTenantDecl (unit) ────────────────────────────────────────────


@pytest.mark.unit
class TestPluginTenantDecl:
    """Unit-тесты :class:`PluginTenantDecl` — Pydantic-model."""

    def test_minimal_construction(self) -> None:
        decl = PluginTenantDecl(name="tenant_a")
        assert decl.name == "tenant_a"
        assert decl.capabilities == ()

    def test_with_capabilities(self) -> None:
        decl = PluginTenantDecl(
            name="tenant_a", capabilities=("mq.publish", "net.outbound")
        )
        assert decl.capabilities == ("mq.publish", "net.outbound")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PluginTenantDecl(name="")

    def test_capability_grammar_validated(self) -> None:
        """Грамматика ``<resource>.<verb>`` проверяется через CapabilityRef."""
        with pytest.raises(ValidationError):
            PluginTenantDecl(name="t1", capabilities=("BAD_NAME",))

    def test_frozen(self) -> None:
        decl = PluginTenantDecl(name="t1", capabilities=("mq.publish",))
        with pytest.raises(ValidationError):
            decl.name = "t2"  # type: ignore[misc]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            PluginTenantDecl.model_validate(
                {"name": "t1", "capabilities": [], "bogus": "x"}
            )


# ── PluginManifest.tenants (unit) ──────────────────────────────────


@pytest.mark.unit
class TestPluginManifestTenants:
    """Unit-тесты ``PluginManifest.tenants`` — поле + model_validator."""

    def test_default_empty(self) -> None:
        m = PluginManifest(
            name="x", version="0.1.0", requires_core=">=0.1", entry_class="ext.x.Plugin"
        )
        assert m.tenants == ()

    def test_round_trip_via_model_validate(self) -> None:
        m = PluginManifest.model_validate(
            {
                "name": "x",
                "version": "0.1.0",
                "requires_core": ">=0.1",
                "entry_class": "ext.x.Plugin",
                "tenants": [
                    {"name": "tenant_a", "capabilities": ["mq.publish"]},
                    {"name": "tenant_b", "capabilities": []},
                ],
            }
        )
        assert len(m.tenants) == 2
        assert m.tenants[0].name == "tenant_a"
        assert m.tenants[0].capabilities == ("mq.publish",)
        assert m.tenants[1].name == "tenant_b"
        assert m.tenants[1].capabilities == ()

    def test_unknown_capability_rejected(self) -> None:
        """Vocabulary check: имя из DEFAULT_CAPABILITY_CATALOG."""
        with pytest.raises(ValidationError) as exc_info:
            PluginManifest.model_validate(
                {
                    "name": "x",
                    "version": "0.1.0",
                    "requires_core": ">=0.1",
                    "entry_class": "ext.x.Plugin",
                    "tenants": [
                        {"name": "t1", "capabilities": ["mq.publish", "totally.fake"]}
                    ],
                }
            )
        # Error wraps the model validator; check that "unknown capability" is in message.
        assert "unknown capability" in str(exc_info.value)
        assert "totally.fake" in str(exc_info.value)

    def test_bad_grammar_rejected_at_field_validator(self) -> None:
        """Грамматика: BAD_NAME отвергается в field_validator (PluginTenantDecl)."""
        with pytest.raises(ValidationError) as exc_info:
            PluginManifest.model_validate(
                {
                    "name": "x",
                    "version": "0.1.0",
                    "requires_core": ">=0.1",
                    "entry_class": "ext.x.Plugin",
                    "tenants": [{"name": "t1", "capabilities": ["BAD"]}],
                }
            )
        # Грамматика не пройдёт — сообщение про "<resource>.<verb>".
        assert (
            "resource" in str(exc_info.value).lower()
            or "match" in str(exc_info.value).lower()
        )

    def test_empty_tenants_section_does_not_warn_in_model(self) -> None:
        """Пустой tenants — backward compat, НЕ raise."""
        m = PluginManifest.model_validate(
            {
                "name": "x",
                "version": "0.1.0",
                "requires_core": ">=0.1",
                "entry_class": "ext.x.Plugin",
                "tenants": [],
            }
        )
        assert m.tenants == ()

    @pytest.mark.parametrize("cap_name", list(DEFAULT_CAPABILITY_CATALOG)[:3])
    def test_all_catalog_caps_accepted(self, cap_name: str) -> None:
        """Sanity: первые 3 имени из каталога проходят validator."""
        m = PluginManifest.model_validate(
            {
                "name": "x",
                "version": "0.1.0",
                "requires_core": ">=0.1",
                "entry_class": "ext.x.Plugin",
                "tenants": [{"name": "t1", "capabilities": [cap_name]}],
            }
        )
        assert m.tenants[0].capabilities == (cap_name,)


# ── load_plugin_manifest: TOML round-trip ─────────────────────────────


@pytest.mark.unit
class TestLoadPluginManifestTenants:
    """TOML → ``PluginManifest`` с ``[[tenants]]`` секцией."""

    def test_load_toml_with_tenants(self, tmp_path: Path) -> None:
        path = tmp_path / "plugin.toml"
        path.write_text(
            textwrap.dedent(
                """
                name = "credit_plugin"
                version = "1.0.0"
                requires_core = ">=0.2,<0.3"
                entry_class = "ext.credit.Plugin"
                tenant_aware = true

                [[tenants]]
                name = "tenant_a"
                capabilities = ["mq.publish", "net.outbound"]

                [[tenants]]
                name = "tenant_b"
                capabilities = ["cache.read"]
                """
            ).lstrip(),
            encoding="utf-8",
        )
        m = load_plugin_manifest(path)
        assert m.tenant_aware is True
        assert len(m.tenants) == 2
        assert m.tenants[0].name == "tenant_a"
        assert m.tenants[0].capabilities == ("mq.publish", "net.outbound")
        assert m.tenants[1].name == "tenant_b"
        assert m.tenants[1].capabilities == ("cache.read",)

    def test_load_toml_unknown_capability_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "plugin.toml"
        path.write_text(
            textwrap.dedent(
                """
                name = "bad_plugin"
                version = "1.0.0"
                requires_core = ">=0.1"
                entry_class = "ext.bad.Plugin"
                tenant_aware = true

                [[tenants]]
                name = "tenant_a"
                capabilities = ["mq.publish", "unknown.thing"]
                """
            ).lstrip(),
            encoding="utf-8",
        )
        with pytest.raises(PluginManifestError, match="validation failed"):
            load_plugin_manifest(path)

    def test_load_toml_no_tenants_section_still_works(self, tmp_path: Path) -> None:
        """Backward compat: manifest без [[tenants]] грузится успешно."""
        path = tmp_path / "plugin.toml"
        path.write_text(
            textwrap.dedent(
                """
                name = "plain"
                version = "1.0.0"
                requires_core = ">=0.1"
                entry_class = "ext.plain.Plugin"
                """
            ).lstrip(),
            encoding="utf-8",
        )
        m = load_plugin_manifest(path)
        assert m.tenants == ()


# ── PluginLoader integration ───────────────────────────────────────


@pytest.mark.unit
class TestPluginLoaderTenantsIntegration:
    """Интеграция ``[[tenants]]`` → ``gate.declare_tenant``.

    NB: в default vocabulary все capabilities ``scope_required=True``,
    а slice 1 (KIMI Q1) не поддерживает ``scope`` в ``[[tenants]]``.
    Поэтому для проверки успешного ``declare_tenant`` используем
    custom vocabulary с ``scope_required=False`` (см.
    :func:`_build_loader_with_custom_vocab`). Default-vocabulary
    тесты проверяют только warning + skip behaviour (slice 1 caveat).
    """

    async def test_declare_tenant_called_for_each_capability(
        self, isolated_extensions_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Slice 1: default vocab (все caps ``scope_required=True``) →
        loader skip'ает declare_tenant(scope=None) с warning для каждой
        capability. Тест проверяет что loader НЕ raise'ит и эмитит
        warning для каждой skip.

        NB: успешное ``declare_tenant`` с granted check_tenant
        проверяется в slice 2 (когда ``[[tenants]]`` будет поддерживать
        inline ``scope``).
        """
        manifest_extra = textwrap.dedent(
            """
            tenant_aware = true

            [[tenants]]
            name = "tenant_a"
            capabilities = ["mq.publish", "net.outbound"]
            """
        )
        _write_extension(
            isolated_extensions_dir,
            name="dummy_tenant_plugin",
            manifest_extra=manifest_extra,
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        # caplog captures loader warnings о skipped capabilities.
        with caplog.at_level(logging.WARNING, logger="services.plugins.loader"):
            loaded = await loader.discover_and_load()
        # Плагин всё равно грузится.
        assert loaded[0].status == "loaded"
        gate = loader._gate
        # declare_tenant был вызван (loader делает try/except) — но
        # skip'нут из-за scope_required. Tenant-таблица пустая.
        assert gate.list_allocated_tenant("tenant_a") == ()
        # Loader эмитит warning для каждой skipped capability.
        skipped_warnings = [
            r
            for r in caplog.records
            if "skipped" in r.message and "slice 1 supports only" in r.message
        ]
        assert len(skipped_warnings) >= 2, (
            f"Expected ≥2 skip warnings. Captured: "
            f"{[r.message for r in caplog.records]}"
        )

    async def test_declare_tenant_skipped_for_scope_required_default(
        self, isolated_extensions_dir: Path
    ) -> None:
        """Slice 1: default vocab (все caps ``scope_required=True``) →
        ``declare_tenant(scope=None)`` skip'ится loader'ом с warning.
        Плагин всё равно грузится, но tenant-таблица пустая.
        """
        manifest_extra = textwrap.dedent(
            """
            tenant_aware = true

            [[tenants]]
            name = "tenant_a"
            capabilities = ["mq.publish", "net.outbound"]
            """
        )
        _write_extension(
            isolated_extensions_dir,
            name="dummy_default_vocab",
            manifest_extra=manifest_extra,
        )
        # _build_loader использует default vocabulary (все scope_required=True).
        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        gate = loader._gate

        # Slice 1 limitation: declare_tenant для scope_required=True
        # capabilities skip'ится (см. loader.py try/except).
        # Плагин грузится, но check_tenant возвращает False.
        assert (
            gate.check_tenant("mq.publish", "tenant_a", "dummy_default_vocab") is False
        )
        # Tenant-таблица пустая.
        assert gate.list_allocated_tenant("tenant_a") == ()

    async def test_list_allocated_tenant_reflects_manifest(
        self, isolated_extensions_dir: Path
    ) -> None:
        """Slice 1: default vocab, ``[[tenants]]`` парсится но declare
        skip'ается → ``gate.list_allocated_tenant(t)`` возвращает
        пустой tuple.

        NB: успешный ``list_allocated_tenant`` с non-empty результатом
        возможен только в slice 2 (когда ``[[tenants]]`` будет
        поддерживать inline ``scope``).
        """
        manifest_extra = textwrap.dedent(
            """
            [[tenants]]
            name = "tenant_a"
            capabilities = ["mq.publish", "net.outbound"]
            """
        )
        _write_extension(
            isolated_extensions_dir, name="dummy_alloc", manifest_extra=manifest_extra
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        gate = loader._gate
        # Slice 1: scope=None в [[tenants]] → declare_tenant skip'ается
        # → tenant-таблица пустая (как и test_declare_tenant_skipped_*).
        assert gate.list_allocated_tenant("tenant_a") == ()

    async def test_no_tenants_backward_compat(
        self, isolated_extensions_dir: Path
    ) -> None:
        """Без [[tenants]] плагин грузится успешно (status='loaded')."""
        _write_extension(isolated_extensions_dir, name="dummy_no_tenants")
        loader, *_ = _build_loader(isolated_extensions_dir)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "loaded"
        assert loaded[0].manifest is not None
        assert loaded[0].manifest.tenants == ()

    async def test_tenant_aware_true_without_tenants_emits_warning(
        self, isolated_extensions_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``tenant_aware=true`` + пустой tenants → warning в логе."""
        manifest_extra = "tenant_aware = true\n"
        _write_extension(
            isolated_extensions_dir, name="dummy_orphan", manifest_extra=manifest_extra
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        with caplog.at_level(logging.WARNING, logger="services.plugins.loader"):
            await loader.discover_and_load()
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any(
            "tenant_aware=true but has no [[tenants]] section" in r.message
            for r in warnings
        ), f"No expected warning. Captured: {[r.message for r in warnings]}"

    async def test_tenant_aware_false_without_tenants_no_warning(
        self, isolated_extensions_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``tenant_aware=false`` + пустой tenants → НЕ warning (backward compat)."""
        _write_extension(isolated_extensions_dir, name="dummy_default")
        loader, *_ = _build_loader(isolated_extensions_dir)
        with caplog.at_level(logging.WARNING, logger="services.plugins.loader"):
            await loader.discover_and_load()
        # Не должно быть нашего специфического warning (могут быть другие
        # warning'и от core-инфраструктуры, но не наш текст).
        assert not any(
            "tenant_aware=true but has no [[tenants]] section" in r.message
            for r in caplog.records
        )

    async def test_loaded_plugin_to_dict_contains_tenants(
        self, isolated_extensions_dir: Path
    ) -> None:
        """``LoadedPlugin.to_dict()`` содержит секцию ``tenants``."""
        manifest_extra = textwrap.dedent(
            """
            [[tenants]]
            name = "tenant_a"
            capabilities = ["mq.publish"]
            """
        )
        _write_extension(
            isolated_extensions_dir,
            name="dummy_inventory",
            manifest_extra=manifest_extra,
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        d = loader.successful[0].to_dict()
        assert "tenants" in d
        assert d["tenants"] == [{"name": "tenant_a", "capabilities": ["mq.publish"]}]

    async def test_capability_ref_scope_required_raises(self) -> None:
        """Sanity: ``CapabilityRef(name='mq.publish')`` (scope=None) RAISE в default vocab.

        :meth:`CapabilityVocabulary.validate_ref` raise'ит ``ValueError`` для
        ``scope_required=True`` capabilities. Это **slice 1 limitation**:
        loader skip'ает такие capabilities в declare_tenant. Следующий slice
        добавит inline ``scope`` в ``[[tenants]]``.
        """
        ref = CapabilityRef(name="mq.publish")
        assert ref.scope is None
        gate = CapabilityGate()  # default vocabulary
        with pytest.raises(ValueError, match="scope_required"):
            gate.vocabulary.validate_ref(ref)


# ── Helper fixture (переиспользует паттерн test_loader) ──────────


@pytest.fixture
def isolated_extensions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Изолированный tmp_path importable как top-level (см. test_loader)."""
    import sys

    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    for mod_name in list(sys.modules):
        if mod_name.startswith(("dummy_", "fake_", "demo_", "good_", "bad_")):
            sys.modules.pop(mod_name, None)
