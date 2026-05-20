# ruff: noqa: S101
"""Sprint 14 W3 — unit-тесты ``tools.publish_plugin``.

Покрывает:

* zip-bundle fallback (когда нет pyproject.toml);
* SBOM skip при отсутствии cyclonedx-py;
* cosign skip при отсутствии ключа;
* no-op upload без MARKETPLACE_URL.

External tools (cosign, cyclonedx-py, uv) замокаем через monkeypatch
:func:`shutil.which`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import publish_plugin as pp  # noqa: E402


@pytest.fixture()
def plugin_dir(tmp_path: Path) -> Path:
    """Создаёт минимальный extensions/<plugin>/."""
    root = tmp_path / "extensions" / "demo"
    root.mkdir(parents=True)
    (root / "plugin.toml").write_text(
        "name = \"demo\"\n"
        "version = \"1.0.0\"\n"
        "requires_core = \">=0.2,<1.0\"\n"
        "entry_class = \"extensions.demo.plugin.Demo\"\n"
    )
    return root


def test_bundle_zip_fallback(
    plugin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Когда нет pyproject.toml и uv → zip-archive."""
    monkeypatch.setattr(pp, "_ensure_tool", lambda name: False)  # noqa: ARG005
    cfg = pp.PublishConfig(
        plugin="demo",
        version="1.0.0",
        plugin_dir=plugin_dir,
        dist_dir=tmp_path / "dist",
        skip_sbom=True,
        skip_cosign=True,
        skip_upload=True,
    )
    bundle = pp._bundle_plugin(cfg)
    assert bundle.exists()
    assert bundle.suffix == ".zip"
    assert "demo-1.0.0" in bundle.name


def test_full_pipeline_dry_run(
    plugin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--dry-run` не вызывает реальных утилит и не упирается в их отсутствие."""
    monkeypatch.setattr(pp, "_ensure_tool", lambda name: name == "uv")
    cfg = pp.PublishConfig(
        plugin="demo",
        version="1.0.0",
        plugin_dir=plugin_dir,
        dist_dir=tmp_path / "dist",
        cosign_key=tmp_path / "fake.key",
        marketplace_url=None,
        dry_run=True,
    )
    result = pp.run(cfg)
    assert result.bundle_path is not None
    # upload disabled because MARKETPLACE_URL is None
    assert result.uploaded is False


def test_sbom_skipped_when_disabled(
    plugin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pp, "_ensure_tool", lambda name: False)  # noqa: ARG005
    cfg = pp.PublishConfig(
        plugin="demo",
        version="1.0.0",
        plugin_dir=plugin_dir,
        dist_dir=tmp_path / "dist",
        skip_sbom=True,
        skip_cosign=True,
        skip_upload=True,
    )
    result = pp.run(cfg)
    assert result.sbom_path is None


def test_cosign_skipped_when_key_missing(
    plugin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pp, "_ensure_tool", lambda name: True)  # noqa: ARG005
    cfg = pp.PublishConfig(
        plugin="demo",
        version="1.0.0",
        plugin_dir=plugin_dir,
        dist_dir=tmp_path / "dist",
        cosign_key=None,
        skip_sbom=True,
        skip_upload=True,
    )
    result = pp.run(cfg)
    assert result.signature_path is None


def test_upload_noop_without_url(
    plugin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pp, "_ensure_tool", lambda name: False)  # noqa: ARG005
    cfg = pp.PublishConfig(
        plugin="demo",
        version="1.0.0",
        plugin_dir=plugin_dir,
        dist_dir=tmp_path / "dist",
        marketplace_url=None,
        skip_sbom=True,
        skip_cosign=True,
    )
    result = pp.run(cfg)
    assert result.uploaded is False


def test_main_returns_zero(
    plugin_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pp, "_ensure_tool", lambda name: False)  # noqa: ARG005
    exit_code = pp.main(
        [
            "--plugin",
            "demo",
            "--version",
            "1.0.0",
            "--plugins-dir",
            str(plugin_dir.parent),
            "--dist-dir",
            str(tmp_path / "dist"),
            "--skip-sbom",
            "--skip-cosign",
            "--skip-upload",
        ]
    )
    assert exit_code == 0
