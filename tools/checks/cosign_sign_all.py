"""Multi-artifact cosign signing pipeline (S7 K1 closure).

Назначение:
    Подписывает все release-артефакты единым проходом через ``cosign sign-blob``
    (для файловых артефактов) и ``cosign sign`` (для OCI container images).
    Используется в release-pipeline для финального supply-chain gate
    [wave:s7/k1-supply-chain-finale].

    Покрываемые артефакты:

    1. **SBOM** — ``dist/sbom/sbom.cdx.json`` + ``dist/sbom/sbom.cdx.xml``
       (генерируется через :mod:`tools.checks.generate_sbom`).
    2. **Wheels** — ``dist/*.whl`` (после ``uv build``).
    3. **Container image** — ``cosign sign <image:tag>`` (если в окружении
       присутствует ``docker`` и переменная ``CONTAINER_IMAGE``).
    4. **Plugin manifests** — ``extensions/<name>/plugin.toml`` (semver-stable
       контракт V11.1; ловит подмену capability-декларации).

    Подписи сохраняются в ``dist/cosign-signatures/<artifact-name>.sig``.

feature_flag:
    ``supply_chain_finale_strict`` (default-OFF до проверки cosign keypair и
    docker buildx readiness в CI/release pipeline).

Использование:
    python tools/checks/cosign_sign_all.py --key cosign.key
    python tools/checks/cosign_sign_all.py --key cosign.key --container-image ghcr.io/org/app:1.0.0
    python tools/checks/cosign_sign_all.py --key cosign.key --skip-image --skip-wheels

Зависимости:
    cosign — устанавливается отдельно
    (https://docs.sigstore.dev/cosign/system_config/installation/).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_TOOL = "cosign"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "dist" / "cosign-signatures"


@dataclass(slots=True)
class SignResult:
    """Результат подписания одного артефакта.

    Attributes:
        artifact: Путь или identifier подписанного объекта.
        signature_path: Путь к ``.sig`` (None для OCI image — подпись в registry).
        ok: True, если подпись успешна.
        skipped: True, если стадия пропущена (нет файла/инструмента).
        message: Сводное сообщение.
    """

    artifact: str
    signature_path: Path | None
    ok: bool
    skipped: bool
    message: str


@dataclass(slots=True)
class SignerConfig:
    """Конфигурация runner — пути, ключ, что подписывать.

    Attributes:
        key_path: Путь к приватному ключу cosign (PEM).
        output_dir: Каталог для ``.sig`` файлов.
        sbom_dir: Каталог с SBOM (default ``dist/sbom``).
        wheels_dir: Каталог с wheels (default ``dist``).
        extensions_dir: Каталог расширений с plugin.toml.
        container_image: OCI image:tag (опционально).
        skip_sbom: Пропустить SBOM подписание.
        skip_wheels: Пропустить wheels.
        skip_image: Пропустить контейнер.
        skip_plugins: Пропустить plugin.toml manifests.
    """

    key_path: Path
    output_dir: Path = _DEFAULT_OUTPUT_DIR
    sbom_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "dist" / "sbom")
    wheels_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "dist")
    extensions_dir: Path = field(default_factory=lambda: _PROJECT_ROOT / "extensions")
    container_image: str | None = None
    skip_sbom: bool = False
    skip_wheels: bool = False
    skip_image: bool = False
    skip_plugins: bool = False


def _check_tool_available() -> bool:
    """Проверяет наличие ``cosign`` в PATH (без SystemExit для тестируемости).

    Returns:
        True, если cosign доступен.
    """
    return shutil.which(_TOOL) is not None


def _sign_blob(artifact_path: Path, key_path: Path, output_dir: Path) -> SignResult:
    """Подписывает файловый артефакт через ``cosign sign-blob``.

    Args:
        artifact_path: Путь к подписываемому файлу.
        key_path: Путь к приватному ключу.
        output_dir: Каталог для ``.sig`` файлов.

    Returns:
        [SignResult] со статусом подписи.
    """
    if not artifact_path.exists():
        return SignResult(
            artifact=str(artifact_path),
            signature_path=None,
            ok=False,
            skipped=True,
            message=f"artifact missing: {artifact_path}",
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    sig_path = output_dir / f"{artifact_path.name}.sig"
    cmd = [
        _TOOL,
        "sign-blob",
        "--yes",
        "--key",
        str(key_path),
        "--output-signature",
        str(sig_path),
        str(artifact_path),
    ]
    try:
        result = subprocess.run(  # noqa: S603 — args жёстко контролируются
            cmd, check=False, capture_output=True, text=True
        )
    except FileNotFoundError as exc:
        return SignResult(
            artifact=str(artifact_path),
            signature_path=None,
            ok=False,
            skipped=True,
            message=f"cosign missing: {exc}",
        )
    if result.returncode != 0:
        return SignResult(
            artifact=str(artifact_path),
            signature_path=None,
            ok=False,
            skipped=False,
            message=f"sign-blob failed exit={result.returncode} stderr={result.stderr.strip()}",
        )
    return SignResult(
        artifact=str(artifact_path),
        signature_path=sig_path,
        ok=True,
        skipped=False,
        message=f"signed -> {sig_path}",
    )


def _sign_image(image: str, key_path: Path) -> SignResult:
    """Подписывает OCI image через ``cosign sign <image>``.

    Args:
        image: Container image identifier (``ghcr.io/org/app:1.0.0``).
        key_path: Путь к приватному ключу.

    Returns:
        [SignResult] со статусом подписи (подпись хранится в registry).
    """
    if shutil.which("docker") is None:
        return SignResult(
            artifact=image,
            signature_path=None,
            ok=False,
            skipped=True,
            message="docker not in PATH (image signing skipped)",
        )
    cmd = [_TOOL, "sign", "--yes", "--key", str(key_path), image]
    try:
        result = subprocess.run(  # noqa: S603
            cmd, check=False, capture_output=True, text=True
        )
    except FileNotFoundError as exc:
        return SignResult(
            artifact=image,
            signature_path=None,
            ok=False,
            skipped=True,
            message=f"cosign missing: {exc}",
        )
    if result.returncode != 0:
        return SignResult(
            artifact=image,
            signature_path=None,
            ok=False,
            skipped=False,
            message=f"image sign failed exit={result.returncode} stderr={result.stderr.strip()}",
        )
    return SignResult(
        artifact=image,
        signature_path=None,
        ok=True,
        skipped=False,
        message="image signed (cosign registry attached signature)",
    )


def sign_sbom(cfg: SignerConfig) -> list[SignResult]:
    """Подписывает SBOM JSON + XML.

    Args:
        cfg: Конфигурация runner.

    Returns:
        Список [SignResult] (один на каждый SBOM-файл).
    """
    results: list[SignResult] = []
    for name in ("sbom.cdx.json", "sbom.cdx.xml"):
        path = cfg.sbom_dir / name
        results.append(_sign_blob(path, cfg.key_path, cfg.output_dir))
    return results


def sign_wheels(cfg: SignerConfig) -> list[SignResult]:
    """Подписывает все ``*.whl`` в wheels_dir.

    Args:
        cfg: Конфигурация runner.

    Returns:
        Список [SignResult] (по одному на wheel) или один SKIP, если нет wheels.
    """
    if not cfg.wheels_dir.exists():
        return [
            SignResult(
                artifact=str(cfg.wheels_dir),
                signature_path=None,
                ok=False,
                skipped=True,
                message="wheels dir missing",
            )
        ]
    wheels = sorted(cfg.wheels_dir.glob("*.whl"))
    if not wheels:
        return [
            SignResult(
                artifact=str(cfg.wheels_dir),
                signature_path=None,
                ok=False,
                skipped=True,
                message="no *.whl found",
            )
        ]
    return [_sign_blob(w, cfg.key_path, cfg.output_dir) for w in wheels]


def sign_plugin_manifests(cfg: SignerConfig) -> list[SignResult]:
    """Подписывает все ``extensions/<name>/plugin.toml`` манифесты.

    Args:
        cfg: Конфигурация runner.

    Returns:
        Список [SignResult] (по одному на манифест) или SKIP, если extensions нет.
    """
    if not cfg.extensions_dir.exists():
        return [
            SignResult(
                artifact=str(cfg.extensions_dir),
                signature_path=None,
                ok=False,
                skipped=True,
                message="extensions dir missing",
            )
        ]
    manifests = sorted(cfg.extensions_dir.glob("*/plugin.toml"))
    if not manifests:
        return [
            SignResult(
                artifact=str(cfg.extensions_dir),
                signature_path=None,
                ok=False,
                skipped=True,
                message="no plugin.toml manifests found",
            )
        ]
    return [_sign_blob(m, cfg.key_path, cfg.output_dir) for m in manifests]


def sign_container_image(cfg: SignerConfig) -> list[SignResult]:
    """Подписывает OCI image, если задан container_image.

    Args:
        cfg: Конфигурация runner.

    Returns:
        Список из одного [SignResult] (SKIP, если image не задан).
    """
    if not cfg.container_image:
        return [
            SignResult(
                artifact="(no container image)",
                signature_path=None,
                ok=False,
                skipped=True,
                message="CONTAINER_IMAGE not set",
            )
        ]
    return [_sign_image(cfg.container_image, cfg.key_path)]


def run(cfg: SignerConfig) -> list[SignResult]:
    """Выполняет полный multi-artifact pipeline согласно конфигу.

    Args:
        cfg: Конфигурация runner.

    Returns:
        Полный список [SignResult] по всем стадиям.
    """
    results: list[SignResult] = []
    if not cfg.skip_sbom:
        results.extend(sign_sbom(cfg))
    if not cfg.skip_wheels:
        results.extend(sign_wheels(cfg))
    if not cfg.skip_plugins:
        results.extend(sign_plugin_manifests(cfg))
    if not cfg.skip_image:
        results.extend(sign_container_image(cfg))
    return results


def print_summary(results: list[SignResult]) -> int:
    """Печатает сводку и возвращает количество blocking failures.

    Args:
        results: Список результатов из :func:`run`.

    Returns:
        Количество стадий с ``ok=False and skipped=False`` (blocking).
    """
    print("\n=== cosign multi-artifact summary ===")
    failures = 0
    for r in results:
        mark = "OK" if r.ok else ("SKIP" if r.skipped else "FAIL")
        print(f"  [{mark}] {r.artifact}: {r.message}")
        if not r.ok and not r.skipped:
            failures += 1
    return failures


def _build_config(args: argparse.Namespace) -> SignerConfig:
    """Преобразует argparse Namespace в [SignerConfig]."""
    container_image = args.container_image or os.environ.get("CONTAINER_IMAGE")
    return SignerConfig(
        key_path=Path(args.key),
        output_dir=Path(args.output_dir),
        sbom_dir=Path(args.sbom_dir),
        wheels_dir=Path(args.wheels_dir),
        extensions_dir=Path(args.extensions_dir),
        container_image=container_image,
        skip_sbom=args.skip_sbom,
        skip_wheels=args.skip_wheels,
        skip_image=args.skip_image,
        skip_plugins=args.skip_plugins,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — multi-artifact cosign signing.

    Args:
        argv: Список аргументов (для тестов; None = sys.argv).

    Returns:
        0 — все blocking стадии прошли; 1 — есть FAIL; 2 — cosign не найден.
    """
    parser = argparse.ArgumentParser(
        description="Multi-artifact cosign signing (S7 K1 supply-chain finale)"
    )
    parser.add_argument("--key", required=True, help="cosign приватный ключ (PEM)")
    parser.add_argument(
        "--output-dir",
        default=str(_DEFAULT_OUTPUT_DIR),
        help="каталог для *.sig файлов",
    )
    parser.add_argument(
        "--sbom-dir",
        default=str(_PROJECT_ROOT / "dist" / "sbom"),
        help="каталог с SBOM (sbom.cdx.json/xml)",
    )
    parser.add_argument(
        "--wheels-dir", default=str(_PROJECT_ROOT / "dist"), help="каталог с *.whl"
    )
    parser.add_argument(
        "--extensions-dir",
        default=str(_PROJECT_ROOT / "extensions"),
        help="каталог расширений с plugin.toml",
    )
    parser.add_argument(
        "--container-image",
        default=None,
        help="OCI image:tag (или ENV CONTAINER_IMAGE)",
    )
    parser.add_argument("--skip-sbom", action="store_true")
    parser.add_argument("--skip-wheels", action="store_true")
    parser.add_argument("--skip-image", action="store_true")
    parser.add_argument("--skip-plugins", action="store_true")
    args = parser.parse_args(argv)

    if not _check_tool_available():
        print(
            "[ERROR] 'cosign' не найден в PATH. "
            "Установите: https://docs.sigstore.dev/cosign/system_config/installation/",
            file=sys.stderr,
        )
        return 2

    cfg = _build_config(args)
    if not cfg.key_path.exists():
        print(f"[ERROR] ключ не найден: {cfg.key_path}", file=sys.stderr)
        return 2

    results = run(cfg)
    failures = print_summary(results)
    if failures > 0:
        print(f"\n[FAIL] cosign-sign-all: {failures} blocking failure(s)")
        return 1
    print("\n[OK] cosign-sign-all: all blocking stages signed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
