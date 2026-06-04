"""Sprint 3 — unit-тесты frontend pages auto-discovery в PluginLoaderV11.

Проверяют:

* при ``streamlit_pages_dir=None`` функционал не активируется;
* при наличии ``extensions/<name>/frontend/pages/*.py`` — symlinks
  создаются с префиксом ``plugin_<name>_``;
* при unmount (``shutdown_all``) — symlinks удаляются;
* идемпотентность: повторный mount того же source не дублирует.
"""

# ruff: noqa: S101

from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from src.backend.core.security.capabilities import CapabilityGate
from src.backend.services.plugins.loader_v11 import PluginLoaderV11


class _FakeActions:
    def register(
        self, action_id: str, handler: Any, *, spec: Any | None = None
    ) -> None:
        return None


class _FakeRepos:
    def register_hook(self, repo_name: str, event: str, callback: Any) -> None:
        return None

    def override_method(self, repo_name: str, method: str, replacement: Any) -> None:
        return None


class _FakeProcessors:
    def register_class(self, name: str, cls: type) -> None:
        return None


def _write_plugin(extensions_dir: Path, *, name: str, with_pages: bool = True) -> Path:
    plugin_dir = extensions_dir / name
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        textwrap.dedent(
            f"""
            from src.backend.core.interfaces.plugin import BasePlugin

            class Plugin(BasePlugin):
                name = "{name}"
                version = "1.0.0"
            """
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.toml").write_text(
        textwrap.dedent(
            f"""
            name = "{name}"
            version = "1.0.0"
            requires_core = ">=0.2,<0.3"
            entry_class = "{name}.plugin.Plugin"
            """
        ).lstrip(),
        encoding="utf-8",
    )
    if with_pages:
        pages = plugin_dir / "frontend" / "pages"
        pages.mkdir(parents=True)
        (pages / "01_dashboard.py").write_text(
            "import streamlit as st\nst.write('hello')\n", encoding="utf-8"
        )
        (pages / "02_admin.py").write_text(
            "import streamlit as st\nst.write('admin')\n", encoding="utf-8"
        )
    return plugin_dir


def _build_loader(
    extensions_dir: Path, streamlit_pages_dir: Path | None = None
) -> PluginLoaderV11:
    return PluginLoaderV11(
        extensions_dir=extensions_dir,
        capability_gate=CapabilityGate(),
        action_registry=_FakeActions(),
        repository_registry=_FakeRepos(),
        processor_registry=_FakeProcessors(),
        core_version="0.2.0",
        streamlit_pages_dir=streamlit_pages_dir,
    )


@pytest.fixture
def isolated_extensions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    extensions_dir = tmp_path / "extensions"
    extensions_dir.mkdir()
    monkeypatch.syspath_prepend(str(extensions_dir))
    yield extensions_dir
    for mod in list(sys.modules):
        if mod.startswith(("page_plugin",)):
            sys.modules.pop(mod, None)


@pytest.mark.asyncio
async def test_pages_mounted_after_load(
    isolated_extensions: Path, tmp_path: Path
) -> None:
    """При load — symlinks появляются в streamlit_pages_dir."""
    pages_dst = tmp_path / "streamlit_pages"
    _write_plugin(isolated_extensions, name="page_plugin")
    loader = _build_loader(isolated_extensions, streamlit_pages_dir=pages_dst)
    await loader.discover_and_load()

    assert (pages_dst / "plugin_page_plugin_01_dashboard.py").is_symlink()
    assert (pages_dst / "plugin_page_plugin_02_admin.py").is_symlink()
    entry = loader.loaded[0]
    assert entry.status == "loaded"
    assert entry.pages_count == 2


@pytest.mark.asyncio
async def test_pages_unmounted_on_shutdown(
    isolated_extensions: Path, tmp_path: Path
) -> None:
    pages_dst = tmp_path / "streamlit_pages"
    _write_plugin(isolated_extensions, name="page_plugin_off")
    loader = _build_loader(isolated_extensions, streamlit_pages_dir=pages_dst)
    await loader.discover_and_load()
    assert any(pages_dst.iterdir())
    await loader.shutdown_all()
    remaining = [
        p for p in pages_dst.iterdir() if p.name.startswith("plugin_page_plugin_off_")
    ]
    assert remaining == []


@pytest.mark.asyncio
async def test_no_pages_dir_when_streamlit_arg_none(isolated_extensions: Path) -> None:
    """Без streamlit_pages_dir функционал не активируется."""
    _write_plugin(isolated_extensions, name="page_plugin_skip")
    loader = _build_loader(isolated_extensions, streamlit_pages_dir=None)
    await loader.discover_and_load()
    assert loader.loaded[0].pages_count == 0


@pytest.mark.asyncio
async def test_no_pages_dir_inside_plugin_returns_zero(
    isolated_extensions: Path, tmp_path: Path
) -> None:
    """Плагин без frontend/pages — pages_count=0, без ошибок."""
    pages_dst = tmp_path / "streamlit_pages"
    _write_plugin(isolated_extensions, name="page_plugin_empty", with_pages=False)
    loader = _build_loader(isolated_extensions, streamlit_pages_dir=pages_dst)
    await loader.discover_and_load()
    assert loader.loaded[0].pages_count == 0


@pytest.mark.asyncio
async def test_idempotent_remount_same_source(
    isolated_extensions: Path, tmp_path: Path
) -> None:
    """Повторный mount того же source не падает и не дублирует."""
    pages_dst = tmp_path / "streamlit_pages"
    plugin_dir = _write_plugin(isolated_extensions, name="page_plugin_idem")
    loader = _build_loader(isolated_extensions, streamlit_pages_dir=pages_dst)
    await loader.discover_and_load()
    # вызвать повторно напрямую — должен дать тот же результат
    again = loader._mount_frontend_pages("page_plugin_idem", plugin_dir)
    assert again == 2
    files = sorted(p.name for p in pages_dst.iterdir())
    assert files == [
        "plugin_page_plugin_idem_01_dashboard.py",
        "plugin_page_plugin_idem_02_admin.py",
    ]


@pytest.mark.asyncio
async def test_unmount_without_mount_is_noop(
    isolated_extensions: Path, tmp_path: Path
) -> None:
    pages_dst = tmp_path / "streamlit_pages"
    pages_dst.mkdir()
    _write_plugin(isolated_extensions, name="page_plugin_noop", with_pages=False)
    loader = _build_loader(isolated_extensions, streamlit_pages_dir=pages_dst)
    await loader.discover_and_load()
    removed = loader._unmount_frontend_pages("page_plugin_noop")
    assert removed == 0
