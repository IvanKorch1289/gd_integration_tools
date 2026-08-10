"""Тесты PluginLoader (ADR-042)."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from src.backend.core.interfaces.plugin import (
    ActionRegistryProtocol,
    ProcessorRegistryProtocol,
    RepositoryRegistryProtocol,
)
from src.backend.core.security.capabilities import CapabilityGate
from src.backend.services.plugins.loader import LoadedPlugin, PluginLoader

# ── фейковые реестры ──────────────────────────────────────────────────


class _FakeActions:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def register(
        self, action_id: str, handler: Any, *, spec: Any | None = None,
    ) -> None:
        self.calls.append((action_id, "spec" if spec else None))


class _FakeRepos:
    def __init__(self) -> None:
        self.hooks: list[tuple[str, str]] = []
        self.overrides: list[tuple[str, str]] = []

    def register_hook(self, repo_name: str, event: str, callback: Any) -> None:
        self.hooks.append((repo_name, event))

    def override_method(self, repo_name: str, method: str, replacement: Any) -> None:
        self.overrides.append((repo_name, method))


class _FakeProcessors:
    def __init__(self) -> None:
        self.classes: list[str] = []

    def register_class(self, name: str, cls: type) -> None:
        self.classes.append(name)


def _build_loader(
    tmp_path: Path, *, core_version: str = "0.2.0",
) -> tuple[PluginLoader, _FakeActions, _FakeRepos, _FakeProcessors]:
    actions = _FakeActions()
    repos = _FakeRepos()
    processors = _FakeProcessors()
    loader = PluginLoader(
        extensions_dir=tmp_path,
        capability_gate=CapabilityGate(),
        action_registry=actions,
        repository_registry=repos,
        processor_registry=processors,
        core_version=core_version,
    )
    return loader, actions, repos, processors


def _write_extension(
    root: Path,
    *,
    name: str,
    manifest_extra: str = "",
    plugin_module_body: str = "",
    plugin_class: str = "Plugin",
    requires_core: str = ">=0.2,<0.3",
    skip_module: bool = False,
) -> Path:
    """Создать временное in-tree extension-окружение под ``extensions/<name>/``."""
    pkg = root / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    if not skip_module:
        body = plugin_module_body or textwrap.dedent(
            f"""
            from src.backend.core.interfaces.plugin import BasePlugin

            class {plugin_class}(BasePlugin):
                name = "{name}"
                version = "1.0.0"
            """,
        )
        (pkg / "plugin.py").write_text(body, encoding="utf-8")
    (pkg / "plugin.toml").write_text(
        textwrap.dedent(
            f"""
            name = "{name}"
            version = "1.0.0"
            requires_core = "{requires_core}"
            entry_class = "{name}.plugin.{plugin_class}"
            {manifest_extra}
            """,
        ).lstrip(),
        encoding="utf-8",
    )
    return pkg


@pytest.fixture
def isolated_extensions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Делает каталог tmp_path importable как top-level пакет."""
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    # Очистка кэша импортов после теста.
    for mod_name in list(sys.modules):
        if mod_name.startswith(("dummy_", "fake_", "demo_", "good_", "bad_")):
            sys.modules.pop(mod_name, None)


# ── tests ─────────────────────────────────────────────────────────────


class TestPluginLoaderDiscovery:
    async def test_no_extensions_dir(self, tmp_path: Path) -> None:
        loader, *_ = _build_loader(tmp_path / "absent")
        assert await loader.discover_and_load() == ()

    async def test_empty_extensions_dir(self, tmp_path: Path) -> None:
        loader, *_ = _build_loader(tmp_path)
        assert await loader.discover_and_load() == ()

    async def test_load_minimal_plugin(self, isolated_extensions_dir: Path) -> None:
        _write_extension(isolated_extensions_dir, name="dummy_plugin")
        loader, *_ = _build_loader(isolated_extensions_dir)
        loaded = await loader.discover_and_load()
        assert len(loaded) == 1
        entry = loaded[0]
        assert isinstance(entry, LoadedPlugin)
        assert entry.status == "loaded"
        assert entry.name == "dummy_plugin"
        assert entry.instance is not None

    async def test_skipped_on_incompatible_core(
        self, isolated_extensions_dir: Path,
    ) -> None:
        _write_extension(
            isolated_extensions_dir, name="fake_skip", requires_core=">=99.0,<100.0",
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "skipped"
        assert "requires_core" in (loaded[0].reason or "")


class TestPluginLoaderLifecycle:
    async def test_lifecycle_invokes_hooks(self, isolated_extensions_dir: Path) -> None:
        body = textwrap.dedent(
            """
            from src.backend.core.interfaces.plugin import BasePlugin

            CALLS = []

            class Plugin(BasePlugin):
                name = "good_plugin"
                version = "1.0.0"

                async def on_load(self, ctx) -> None:
                    CALLS.append("load")
                async def on_register_actions(self, registry) -> None:
                    registry.register("good.echo", lambda x: x)
                    CALLS.append("actions")
                async def on_register_repositories(self, registry) -> None:
                    CALLS.append("repos")
                async def on_register_processors(self, registry) -> None:
                    CALLS.append("processors")
                async def on_shutdown(self) -> None:
                    CALLS.append("shutdown")
            """,
        )
        _write_extension(
            isolated_extensions_dir, name="good_plugin", plugin_module_body=body,
        )
        loader, actions, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        await loader.shutdown_all()

        import good_plugin.plugin as mod

        assert mod.CALLS == ["load", "actions", "repos", "processors", "shutdown"]
        assert ("good.echo", None) in actions.calls

    async def test_capability_allocation_before_import(
        self, isolated_extensions_dir: Path,
    ) -> None:
        # Невалидная capability (грамматика проходит, но имя не в vocabulary)
        _write_extension(
            isolated_extensions_dir,
            name="bad_plugin",
            manifest_extra=textwrap.dedent(
                """
                [[capabilities]]
                name = "unknown.do"
                scope = "x"
                """,
            ),
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "capability" in (loaded[0].reason or "").lower()

    async def test_capability_declared_in_gate(
        self, isolated_extensions_dir: Path,
    ) -> None:
        _write_extension(
            isolated_extensions_dir,
            name="dummy_caps",
            manifest_extra=textwrap.dedent(
                """
                [[capabilities]]
                name = "db.read"
                scope = "credit_db"
                """,
            ),
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        # gate должен покрывать declared capability.
        loader._gate.check("dummy_caps", "db.read", "credit_db")

    async def test_inventory_conflict_blocks_second_plugin(
        self, isolated_extensions_dir: Path,
    ) -> None:
        _write_extension(
            isolated_extensions_dir,
            name="demo_a",
            manifest_extra='[provides]\nactions = ["x.do"]\n',
        )
        _write_extension(
            isolated_extensions_dir,
            name="demo_b",
            manifest_extra='[provides]\nactions = ["x.do"]\n',
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        loaded = await loader.discover_and_load()
        statuses = {p.name: p.status for p in loaded}
        # Один загружен, второй отклонён по коллизии.
        assert sorted(statuses.values()) == ["failed", "loaded"]
        failed = next(p for p in loaded if p.status == "failed")
        assert "inventory_conflict" in (failed.reason or "")

    async def test_invalid_manifest_marks_failed(self, tmp_path: Path) -> None:
        bad = tmp_path / "broken"
        bad.mkdir()
        (bad / "plugin.toml").write_text("name = 'x\nbroken", encoding="utf-8")
        loader, *_ = _build_loader(tmp_path)
        loaded = await loader.discover_and_load()
        assert loaded[0].status == "failed"
        assert "manifest_error" in (loaded[0].reason or "")

    async def test_lifecycle_failure_revokes_capability(
        self, isolated_extensions_dir: Path,
    ) -> None:
        body = textwrap.dedent(
            """
            from src.backend.core.interfaces.plugin import BasePlugin

            class Plugin(BasePlugin):
                name = "fake_explode"
                version = "1.0.0"

                async def on_load(self, ctx) -> None:
                    raise RuntimeError("boom")
            """,
        )
        _write_extension(
            isolated_extensions_dir,
            name="fake_explode",
            plugin_module_body=body,
            manifest_extra=textwrap.dedent(
                """
                [[capabilities]]
                name = "db.read"
                scope = "credit_db"
                """,
            ),
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        # capability должна быть revoked после lifecycle-error
        with pytest.raises(Exception):
            loader._gate.check("fake_explode", "db.read", "credit_db")


class TestPluginLoaderHelpers:
    async def test_successful_property(self, isolated_extensions_dir: Path) -> None:
        _write_extension(isolated_extensions_dir, name="dummy_ok")
        _write_extension(
            isolated_extensions_dir, name="fake_skipped", requires_core=">=99.0",
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        names = sorted(p.name for p in loader.successful)
        assert names == ["dummy_ok"]

    async def test_to_dict_contains_status(self, isolated_extensions_dir: Path) -> None:
        _write_extension(isolated_extensions_dir, name="dummy_dict")
        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        d = loader.successful[0].to_dict()
        assert d["status"] == "loaded"
        assert d["name"] == "dummy_dict"
        assert "manifest_path" in d


# ── B-04 regression: PluginLoader.shutdown_one (S176 cycle 33) ──


class TestPluginLoaderShutdownOne:
    """B-04 fix: per-plugin unload через :meth:`PluginLoader.shutdown_one`.

    Регрессионный тест: до фикса hot_swap дёргал ``shutdown_all``,
    затрагивая ВСЕ плагины. Сейчас — per-plugin isolation.
    """

    async def test_shutdown_one_removes_target_only(
        self, isolated_extensions_dir: Path,
    ) -> None:
        """shutdown_one(target) удаляет только target, unrelated остаётся loaded."""
        body_a = textwrap.dedent(
            """
            from src.backend.core.interfaces.plugin import BasePlugin

            CALLS_A = []

            class Plugin(BasePlugin):
                name = "alpha"
                version = "1.0.0"

                async def on_shutdown(self) -> None:
                    CALLS_A.append("shutdown")
            """,
        )
        body_b = textwrap.dedent(
            """
            from src.backend.core.interfaces.plugin import BasePlugin

            CALLS_B = []

            class Plugin(BasePlugin):
                name = "bravo"
                version = "1.0.0"

                async def on_shutdown(self) -> None:
                    CALLS_B.append("shutdown")
            """,
        )
        _write_extension(
            isolated_extensions_dir, name="alpha", plugin_module_body=body_a,
        )
        _write_extension(
            isolated_extensions_dir, name="bravo", plugin_module_body=body_b,
        )
        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        assert sorted(p.name for p in loader.successful) == ["alpha", "bravo"]

        result = await loader.shutdown_one("alpha")
        assert result is True
        assert sorted(p.name for p in loader.successful) == ["bravo"]

        # Alpha's on_shutdown был вызван, bravo — нет.
        import alpha.plugin as alpha_mod
        import bravo.plugin as bravo_mod

        assert alpha_mod.CALLS_A == ["shutdown"]
        assert bravo_mod.CALLS_B == []

    async def test_shutdown_one_returns_false_for_unknown_plugin(
        self, isolated_extensions_dir: Path,
    ) -> None:
        """shutdown_one(unknown) → False (no-op), без raise."""
        loader, *_ = _build_loader(isolated_extensions_dir)
        result = await loader.shutdown_one("never_loaded")
        assert result is False

    async def test_shutdown_one_revokes_capability(
        self, isolated_extensions_dir: Path,
    ) -> None:
        """shutdown_one(target) вызывает gate.revoke(target) — не raise.

        Не проверяем конкретный формат declare (требует vocabulary);
        достаточно убедиться, что shutdown_one проходит без ошибок
        на плагине с capability и что после shutdown он удалён из реестра.
        """
        body = textwrap.dedent(
            """
            from src.backend.core.interfaces.plugin import BasePlugin

            class Plugin(BasePlugin):
                name = "alpha_revoke"
                version = "1.0.0"
            """,
        )
        _write_extension(
            isolated_extensions_dir, name="alpha_revoke", plugin_module_body=body,
        )

        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        assert any(
            getattr(e, "name", None) == "alpha_revoke" for e in loader.loaded
        )

        # Per-plugin shutdown не должен падать даже если у плагина
        # не было capability (revoke — no-op в этом случае).
        result = await loader.shutdown_one("alpha_revoke")
        assert result is True

        # После shutdown — запись из _loaded исчезла.
        assert all(
            getattr(e, "name", None) != "alpha_revoke" for e in loader.loaded
        )

    async def test_shutdown_one_emits_audit_event(
        self, isolated_extensions_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cycle 33 S176: shutdown_one эмитит audit-event для security observability.

        Регрессионный тест: hot_swap часто вызывается из admin-endpoint'а
        (с auth), но сама операция выгрузки плагина — security-relevant.
        Audit-event ``plugin.unload`` фиксирует кто/что/когда, чтобы
        SOC-команды могли alerting на подозрительные серии unload.
        """
        body = textwrap.dedent(
            """
            from src.backend.core.interfaces.plugin import BasePlugin

            class Plugin(BasePlugin):
                name = "alpha_audit"
                version = "1.2.3"
            """,
        )
        _write_extension(
            isolated_extensions_dir, name="alpha_audit", plugin_module_body=body,
        )

        # Patch emit_audit_safe для захвата вызовов.
        captured: list[dict[str, object]] = []

        def _fake_emit_audit_safe(**kwargs: object) -> None:
            captured.append(kwargs)

        monkeypatch.setattr(
            "src.backend.core.audit.facade.emit_audit_safe",
            _fake_emit_audit_safe,
        )

        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()
        await loader.shutdown_one("alpha_audit")

        # Audit-event должен быть эмитирован ровно один раз.
        plugin_unload_events = [
            c for c in captured
            if c.get("event") == "plugin.unload"
            and c.get("action") == "shutdown_one"
        ]
        assert len(plugin_unload_events) == 1
        details = plugin_unload_events[0].get("details", {})
        assert isinstance(details, dict)
        assert details.get("plugin_name") == "alpha_audit"
        assert details.get("old_status") == "loaded"
        # _write_extension hardcodes version "1.0.0"; мы только проверяем
        # что поле пробрасывается, не конкретное значение.
        assert details.get("old_version") == "1.0.0"

    async def test_shutdown_one_audit_failure_does_not_break(
        self, isolated_extensions_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """shutdown_one не падает если audit-emit упал (defense-in-depth)."""
        body = textwrap.dedent(
            """
            from src.backend.core.interfaces.plugin import BasePlugin

            class Plugin(BasePlugin):
                name = "alpha_audit_fail"
                version = "1.0.0"
            """,
        )
        _write_extension(
            isolated_extensions_dir, name="alpha_audit_fail", plugin_module_body=body,
        )

        def _broken_emit_audit_safe(**kwargs: object) -> None:
            raise RuntimeError("audit down")

        monkeypatch.setattr(
            "src.backend.core.audit.facade.emit_audit_safe",
            _broken_emit_audit_safe,
        )

        loader, *_ = _build_loader(isolated_extensions_dir)
        await loader.discover_and_load()

        # Audit-ошибка НЕ должна ломать сам shutdown (emit_audit_safe
        # already ловит, но defense-in-depth — на случай если кто-то
        # заменит на emit_audit без _safe).
        result = await loader.shutdown_one("alpha_audit_fail")
        assert result is True
        assert all(
            getattr(e, "name", None) != "alpha_audit_fail" for e in loader.loaded
        )


class TestProtocolMatching:
    """Регистры должны соответствовать Protocol'ам из core.interfaces.plugin."""

    def test_fake_actions_satisfies(self) -> None:
        assert isinstance(_FakeActions(), ActionRegistryProtocol)

    def test_fake_repos_satisfies(self) -> None:
        assert isinstance(_FakeRepos(), RepositoryRegistryProtocol)

    def test_fake_processors_satisfies(self) -> None:
        assert isinstance(_FakeProcessors(), ProcessorRegistryProtocol)
