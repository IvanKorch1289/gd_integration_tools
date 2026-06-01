"""Unit-тесты для :mod:`tools.checks.cosign_sign_all` (S7 K1 finale).

Покрывают:
    - skip-пути при отсутствии артефактов;
    - успешную подпись (mock subprocess.run → returncode=0);
    - failure-путь (returncode≠0);
    - skip image при отсутствии docker;
    - main() возвращает 2 при отсутствии cosign.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _load_module():
    """Подгрузить tools/checks/cosign_sign_all.py через importlib."""
    path = Path(__file__).resolve().parents[3] / "tools" / "checks" / "cosign_sign_all.py"
    spec = importlib.util.spec_from_file_location("_cosign_sign_all_test", path)
    if spec is None or spec.loader is None:
        raise ImportError("Не удалось загрузить cosign_sign_all.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


@pytest.fixture
def fake_key(tmp_path: Path) -> Path:
    """Создаёт фейковый PEM-ключ для тестов."""
    key = tmp_path / "cosign.key"
    key.write_text("-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n")
    return key


@pytest.fixture
def cfg(tmp_path: Path, fake_key: Path) -> mod.SignerConfig:
    """Базовая конфигурация во временном каталоге."""
    return mod.SignerConfig(
        key_path=fake_key,
        output_dir=tmp_path / "out",
        sbom_dir=tmp_path / "sbom",
        wheels_dir=tmp_path / "wheels",
        extensions_dir=tmp_path / "extensions",
    )


def test_sign_blob_missing_artifact_skips(tmp_path: Path, fake_key: Path) -> None:
    """Если артефакт не существует — возвращается SKIP, без вызова subprocess."""
    out = tmp_path / "out"
    missing = tmp_path / "nope.whl"
    with patch.object(mod.subprocess, "run") as run_mock:
        result = mod._sign_blob(missing, fake_key, out)
    assert result.skipped is True
    assert result.ok is False
    run_mock.assert_not_called()


def test_sign_blob_success(tmp_path: Path, fake_key: Path) -> None:
    """Mock subprocess returncode=0 → SignResult.ok=True и .sig путь."""
    artifact = tmp_path / "thing.json"
    artifact.write_text("{}")
    out = tmp_path / "out"
    fake_result = MagicMock(spec=subprocess.CompletedProcess)
    fake_result.returncode = 0
    fake_result.stderr = ""
    with patch.object(mod.subprocess, "run", return_value=fake_result) as run_mock:
        result = mod._sign_blob(artifact, fake_key, out)
    assert result.ok is True
    assert result.skipped is False
    assert result.signature_path == out / "thing.json.sig"
    run_mock.assert_called_once()
    cmd = run_mock.call_args[0][0]
    assert cmd[0] == "cosign"
    assert cmd[1] == "sign-blob"


def test_sign_blob_failure(tmp_path: Path, fake_key: Path) -> None:
    """Mock returncode≠0 → SignResult.ok=False и не-skip."""
    artifact = tmp_path / "thing.whl"
    artifact.write_bytes(b"fake-wheel")
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stderr = "boom"
    with patch.object(mod.subprocess, "run", return_value=fake_result):
        result = mod._sign_blob(artifact, fake_key, tmp_path / "out")
    assert result.ok is False
    assert result.skipped is False
    assert "exit=1" in result.message


def test_sign_image_no_docker_skips(fake_key: Path) -> None:
    """Если docker отсутствует — image signing skipped без subprocess."""
    with patch.object(mod.shutil, "which", return_value=None):
        with patch.object(mod.subprocess, "run") as run_mock:
            result = mod._sign_image("ghcr.io/org/app:1.0.0", fake_key)
    assert result.skipped is True
    run_mock.assert_not_called()


def test_sign_wheels_no_wheels_returns_skip(cfg: mod.SignerConfig) -> None:
    """Пустой wheels_dir → один SKIP результат."""
    cfg.wheels_dir.mkdir(parents=True)
    results = mod.sign_wheels(cfg)
    assert len(results) == 1
    assert results[0].skipped is True
    assert "no *.whl" in results[0].message


def test_sign_plugin_manifests_finds_all(cfg: mod.SignerConfig) -> None:
    """Все extensions/<name>/plugin.toml подписываются по очереди (mock)."""
    cfg.extensions_dir.mkdir(parents=True)
    for name in ("alpha", "beta"):
        (cfg.extensions_dir / name).mkdir()
        (cfg.extensions_dir / name / "plugin.toml").write_text(f'name = "{name}"\n')
    fake_result = MagicMock(returncode=0, stderr="")
    with patch.object(mod.subprocess, "run", return_value=fake_result):
        results = mod.sign_plugin_manifests(cfg)
    assert len(results) == 2
    assert all(r.ok for r in results)
    assert {r.artifact.split("/")[-2] for r in results} == {"alpha", "beta"}


def test_run_aggregates_all_stages(cfg: mod.SignerConfig) -> None:
    """run() собирает результаты со всех включённых стадий."""
    cfg.sbom_dir.mkdir(parents=True)
    (cfg.sbom_dir / "sbom.cdx.json").write_text("{}")
    (cfg.sbom_dir / "sbom.cdx.xml").write_text("<sbom/>")
    cfg.wheels_dir.mkdir(parents=True)
    (cfg.wheels_dir / "pkg-1.0-py3-none-any.whl").write_bytes(b"wheel")
    cfg.extensions_dir.mkdir(parents=True)
    (cfg.extensions_dir / "p").mkdir()
    (cfg.extensions_dir / "p" / "plugin.toml").write_text("")
    cfg.container_image = None  # skip image (no docker нужно)
    fake_result = MagicMock(returncode=0, stderr="")
    with patch.object(mod.subprocess, "run", return_value=fake_result):
        results = mod.run(cfg)
    # 2 SBOM + 1 wheel + 1 plugin + 1 image-SKIP = 5
    assert len(results) == 5
    image_skips = [r for r in results if r.skipped and "CONTAINER_IMAGE" in r.message]
    assert len(image_skips) == 1


def test_main_returns_2_when_cosign_missing(tmp_path: Path, fake_key: Path) -> None:
    """main() → exit 2 при отсутствии cosign в PATH."""
    with patch.object(mod, "_check_tool_available", return_value=False):
        rc = mod.main(["--key", str(fake_key)])
    assert rc == 2


def test_main_returns_2_when_key_missing(tmp_path: Path) -> None:
    """main() → exit 2 при отсутствии файла ключа."""
    nonexistent = tmp_path / "missing.key"
    with patch.object(mod, "_check_tool_available", return_value=True):
        rc = mod.main(["--key", str(nonexistent)])
    assert rc == 2
