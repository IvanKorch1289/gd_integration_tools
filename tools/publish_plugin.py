"""Sprint 14 W3 — publish-plugin pipeline (bundle + SBOM + cosign + upload).

Назначение:
    Полный pipeline публикации in-tree плагина:

    1. ``bundle`` — собрать wheel из ``extensions/<plugin>/`` (через
       ``uv build --package <plugin>`` если есть pyproject.toml, иначе
       fallback на zip-архив каталога).
    2. ``sbom`` — сгенерировать CycloneDX SBOM через ``cyclonedx-py``.
    3. ``cosign`` — подписать wheel + SBOM (re-use
       :mod:`tools.checks.cosign_sign`).
    4. ``upload`` — REST PUT на ``MARKETPLACE_URL`` (no-op если переменная
       окружения пуста — локальная подпись остаётся в ``dist/``).

Использование:
    python -m tools.publish_plugin --plugin example_plugin --version 1.0.0
    python -m tools.publish_plugin --plugin example_plugin --version 1.0.0 --dry-run

CLI/Makefile:
    make publish-plugin PLUGIN=example_plugin VERSION=1.0.0
    python manage.py plugin publish --plugin example_plugin --version 1.0.0

Зависимости:
    - cosign (внешний бинарь, проверяется в runtime);
    - cyclonedx-py (опц., через `[security]` extra);
    - httpx (уже в стеке) для upload.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DIST_DIR = _PROJECT_ROOT / "dist" / "plugins"

_logger = logging.getLogger("tools.publish_plugin")


@dataclass(slots=True)
class PublishConfig:
    """Конфигурация одного запуска pipeline."""

    plugin: str
    version: str
    plugin_dir: Path
    dist_dir: Path = field(default_factory=lambda: _DIST_DIR)
    cosign_key: Path | None = None
    marketplace_url: str | None = None
    dry_run: bool = False
    skip_sbom: bool = False
    skip_cosign: bool = False
    skip_upload: bool = False


@dataclass(slots=True)
class PublishResult:
    """Сводный результат pipeline (per stage)."""

    bundle_path: Path | None = None
    sbom_path: Path | None = None
    signature_path: Path | None = None
    uploaded: bool = False
    messages: list[str] = field(default_factory=list)


def _ensure_tool(name: str) -> bool:
    """Безопасная проверка наличия CLI-утилиты в PATH."""
    return shutil.which(name) is not None


def _bundle_plugin(cfg: PublishConfig) -> Path:
    """Собрать архив плагина.

    Если в plugin_dir есть pyproject.toml — используем ``uv build``,
    иначе делаем zip-bundle всего каталога.
    """
    if not cfg.plugin_dir.is_dir():
        raise FileNotFoundError(f"plugin directory missing: {cfg.plugin_dir}")
    cfg.dist_dir.mkdir(parents=True, exist_ok=True)
    pyproject = cfg.plugin_dir / "pyproject.toml"

    if pyproject.is_file() and _ensure_tool("uv"):
        cmd = ["uv", "build", "--package", cfg.plugin, "--out-dir", str(cfg.dist_dir)]
        if cfg.dry_run:
            _logger.info("dry-run uv build: %s", " ".join(cmd))
        else:
            subprocess.run(cmd, check=True)  # noqa: S603 — args фиксированы

        wheels = sorted(cfg.dist_dir.glob(f"{cfg.plugin}-{cfg.version}*.whl"))
        if wheels:
            return wheels[-1]

    # Fallback: zip-архив каталога плагина.
    bundle = cfg.dist_dir / f"{cfg.plugin}-{cfg.version}.zip"
    if cfg.dry_run:
        _logger.info("dry-run zip bundle would create: %s", bundle)
        return bundle
    shutil.make_archive(
        base_name=str(bundle.with_suffix("")), format="zip", root_dir=cfg.plugin_dir
    )
    return bundle


def _generate_sbom(cfg: PublishConfig, bundle: Path) -> Path | None:
    """Сгенерировать CycloneDX SBOM для собранного bundle.

    cyclonedx-py — опциональная зависимость; если не установлена,
    возвращаем ``None`` и продолжаем без SBOM (с warning).
    """
    if cfg.skip_sbom:
        return None
    sbom_path = cfg.dist_dir / f"{cfg.plugin}-{cfg.version}.cdx.json"
    if cfg.dry_run:
        _logger.info("dry-run sbom would be created at: %s", sbom_path)
        return sbom_path
    if not _ensure_tool("cyclonedx-py"):
        _logger.warning("cyclonedx-py not in PATH — skipping SBOM generation")
        return None
    cmd = [
        "cyclonedx-py",
        "environment",
        "--output-format",
        "JSON",
        "--outfile",
        str(sbom_path),
    ]
    try:
        subprocess.run(cmd, check=True, cwd=cfg.plugin_dir)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        _logger.warning("cyclonedx-py failed: %s", exc)
        return None
    if not sbom_path.exists():
        return None
    _ = bundle  # bundle не используется напрямую — SBOM описывает окружение
    return sbom_path


def _sign(cfg: PublishConfig, artifact: Path) -> Path | None:
    """Подписать artifact через ``cosign sign-blob``.

    Returns:
        Путь к ``.sig`` или ``None`` если cosign недоступен / skip.
    """
    if cfg.skip_cosign or cfg.cosign_key is None:
        return None
    if cfg.dry_run:
        _logger.info("dry-run cosign would sign: %s", artifact)
        return artifact.with_suffix(artifact.suffix + ".sig")
    if not _ensure_tool("cosign"):
        _logger.warning("cosign not in PATH — skipping signing")
        return None

    sig_path = artifact.with_suffix(artifact.suffix + ".sig")
    cmd = [
        "cosign",
        "sign-blob",
        "--yes",
        "--key",
        str(cfg.cosign_key),
        "--output-signature",
        str(sig_path),
        str(artifact),
    ]
    try:
        subprocess.run(cmd, check=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        _logger.warning("cosign sign-blob failed: %s", exc)
        return None
    return sig_path if sig_path.exists() else None


def _upload(cfg: PublishConfig, bundle: Path) -> bool:
    """REST PUT bundle в marketplace.

    No-op если ``MARKETPLACE_URL`` пуст — pipeline остаётся локальным.
    """
    if cfg.skip_upload or not cfg.marketplace_url:
        return False
    if cfg.dry_run:
        _logger.info("dry-run upload would PUT %s to %s", bundle, cfg.marketplace_url)
        return False
    try:
        import httpx  # noqa: PLC0415
    except ImportError:
        _logger.warning("httpx unavailable — skipping upload")
        return False
    url = cfg.marketplace_url.rstrip("/") + f"/plugins/{cfg.plugin}/{cfg.version}"
    with bundle.open("rb") as fh:
        try:
            response = httpx.put(url, content=fh.read(), timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            _logger.warning("upload failed: %s", exc)
            return False
    return True


def run(cfg: PublishConfig) -> PublishResult:
    """Полный pipeline; собирает :class:`PublishResult` со всех стадий."""
    result = PublishResult()

    bundle = _bundle_plugin(cfg)
    result.bundle_path = bundle
    result.messages.append(f"bundle: {bundle}")

    sbom = _generate_sbom(cfg, bundle)
    result.sbom_path = sbom
    if sbom is not None:
        result.messages.append(f"sbom: {sbom}")

    if not cfg.skip_cosign and cfg.cosign_key is not None:
        sig = _sign(cfg, bundle)
        result.signature_path = sig
        if sig is not None:
            result.messages.append(f"signature: {sig}")

    if not cfg.skip_upload:
        result.uploaded = _upload(cfg, bundle)
        result.messages.append(
            f"upload: {'ok' if result.uploaded else 'skipped'} → {cfg.marketplace_url or '<no MARKETPLACE_URL>'}"
        )

    return result


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint — публикация одного плагина."""
    parser = argparse.ArgumentParser(
        description="Publish plugin: bundle → SBOM → cosign → upload (S14 W3)."
    )
    parser.add_argument(
        "--plugin", required=True, help="Имя плагина (extensions/<name>)"
    )
    parser.add_argument("--version", required=True, help="SemVer плагина")
    parser.add_argument(
        "--plugins-dir",
        type=Path,
        default=_PROJECT_ROOT / "extensions",
        help="Корневой каталог плагинов.",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=_DIST_DIR,
        help="Куда складывать собранные артефакты.",
    )
    parser.add_argument(
        "--cosign-key",
        type=Path,
        default=None,
        help="Путь к приватному ключу cosign (PEM).",
    )
    parser.add_argument(
        "--marketplace-url",
        default=os.environ.get("MARKETPLACE_URL"),
        help="REST endpoint marketplace (или ENV MARKETPLACE_URL).",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-sbom", action="store_true")
    parser.add_argument("--skip-cosign", action="store_true")
    parser.add_argument("--skip-upload", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    plugin_dir = args.plugins_dir / args.plugin
    cfg = PublishConfig(
        plugin=args.plugin,
        version=args.version,
        plugin_dir=plugin_dir,
        dist_dir=args.dist_dir,
        cosign_key=args.cosign_key,
        marketplace_url=args.marketplace_url,
        dry_run=args.dry_run,
        skip_sbom=args.skip_sbom,
        skip_cosign=args.skip_cosign,
        skip_upload=args.skip_upload,
    )
    result = run(cfg)
    for msg in result.messages:
        print(f"[publish-plugin] {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
