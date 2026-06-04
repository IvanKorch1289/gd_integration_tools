"""Supply-chain полный CI gate (orchestrates SBOM + pip-audit + cosign + bandit-TLS).

Назначение:
    Единая точка входа для supply-chain проверок в Sprint 6 К1.
    Оркестрирует существующие проверки:
        1. ``generate_sbom.py`` — CycloneDX JSON+XML
        2. ``run_pip_audit.py`` — pip-audit (ERROR-level)
        3. ``check_bandit_tls.py`` — bandit с TLS-rules
        4. ``cosign_sign.py`` — cosign artifact signing (опционально, требует
           ARTIFACT и KEY env)

    Соответствует Sprint 6 К1 wave [wave:s6/k1-supply-chain-full-gate] и
    BLOCKER #4 closure (KNOWN_ISSUES.md).

Использование:
    python tools/checks/check_supply_chain.py
    python tools/checks/check_supply_chain.py --skip-cosign
    python tools/checks/check_supply_chain.py --output-dir dist/sbom

feature_flag:
    supply_chain_strict_mode (default-OFF до полного аудита transitive deps).

Возвращает exit 0 если все проверки прошли, exit 1 если что-то упало,
exit 2 если инструменты недоступны.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TOOLS = _PROJECT_ROOT / "tools" / "checks"


@dataclass(frozen=True, slots=True)
class StageResult:
    """Результат одной стадии supply-chain pipeline.

    Attributes:
        name: имя стадии.
        exit_code: код возврата (0 = ok).
        skipped: True если стадия пропущена.
        message: сводное сообщение.
    """

    name: str
    exit_code: int
    skipped: bool
    message: str


def _run_stage(
    name: str, cmd: list[str], *, allow_codes: tuple[int, ...] = (0,)
) -> StageResult:
    """Запускает одну стадию pipeline.

    Args:
        name: имя стадии (для отчёта).
        cmd: команда + аргументы.
        allow_codes: допустимые exit-коды (по умолчанию только 0).

    Returns:
        [StageResult] с exit_code и сводкой.
    """
    print(f"\n=== {name} ===")
    try:
        result = subprocess.run(cmd, check=False, cwd=str(_PROJECT_ROOT))  # noqa: S603
    except FileNotFoundError as exc:
        return StageResult(
            name=name, exit_code=2, skipped=False, message=f"tool missing: {exc}"
        )
    ok = result.returncode in allow_codes
    return StageResult(
        name=name,
        exit_code=result.returncode,
        skipped=False,
        message="OK" if ok else f"failed exit={result.returncode}",
    )


def run_sbom(output_dir: Path) -> StageResult:
    """Стадия 1 — CycloneDX SBOM generation."""
    script = _TOOLS / "generate_sbom.py"
    if not script.exists():
        return StageResult("sbom", 2, True, f"missing {script}")
    return _run_stage(
        "sbom",
        [
            sys.executable,
            str(script),
            "--output-dir",
            str(output_dir),
            "--format",
            "all",
        ],
    )


def run_pip_audit() -> StageResult:
    """Стадия 2 — pip-audit с ERROR-level threshold."""
    script = _TOOLS / "run_pip_audit.py"
    if not script.exists():
        return StageResult("pip-audit", 2, True, f"missing {script}")
    return _run_stage("pip-audit", [sys.executable, str(script)])


def run_bandit_tls() -> StageResult:
    """Стадия 3 — bandit TLS-rules."""
    script = _TOOLS / "check_bandit_tls.py"
    if not script.exists():
        return StageResult("bandit-tls", 2, True, f"missing {script}")
    return _run_stage("bandit-tls", [sys.executable, str(script)])


def run_cosign() -> StageResult:
    """Стадия 4 — cosign signing (опционально, требует ARTIFACT+KEY)."""
    script = _TOOLS / "cosign_sign.py"
    if not script.exists():
        return StageResult("cosign", 2, True, f"missing {script}")
    artifact = os.environ.get("ARTIFACT")
    key = os.environ.get("KEY")
    if not artifact or not key:
        return StageResult(
            "cosign", 0, True, "skipped (ARTIFACT/KEY not set — non-release stage)"
        )
    if shutil.which("cosign") is None:
        return StageResult("cosign", 2, True, "cosign not installed in PATH")
    return _run_stage(
        "cosign", [sys.executable, str(script), "--artifact", artifact, "--key", key]
    )


def run_cosign_all_artifacts() -> StageResult:
    """Стадия 5 (S7 finale) — multi-artifact cosign signing.

    Делегирует :mod:`tools.checks.cosign_sign_all` через subprocess; ключ
    передаётся через ENV ``KEY`` (общий контракт с :func:`run_cosign`).
    Stage пропускается, если ``KEY`` не задан или ``cosign`` отсутствует —
    pipeline идёт дальше с SKIP, не валит весь gate.
    """
    script = _TOOLS / "cosign_sign_all.py"
    if not script.exists():
        return StageResult("cosign-all", 2, True, f"missing {script}")
    key = os.environ.get("KEY")
    if not key:
        return StageResult(
            "cosign-all", 0, True, "skipped (KEY not set — non-release stage)"
        )
    if shutil.which("cosign") is None:
        return StageResult("cosign-all", 2, True, "cosign not installed in PATH")
    cmd = [sys.executable, str(script), "--key", key]
    container_image = os.environ.get("CONTAINER_IMAGE")
    if container_image:
        cmd.extend(["--container-image", container_image])
    else:
        cmd.append("--skip-image")
    return _run_stage("cosign-all", cmd)


def main() -> int:
    """CLI entry point — оркестрация 4 стадий supply-chain."""
    parser = argparse.ArgumentParser(description="supply-chain полный CI gate")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("dist/sbom"), help="SBOM output dir"
    )
    parser.add_argument("--skip-cosign", action="store_true", help="Skip cosign stage")
    parser.add_argument(
        "--skip-pip-audit", action="store_true", help="Skip pip-audit (ускорение dev)"
    )
    parser.add_argument("--skip-bandit", action="store_true", help="Skip bandit-TLS")
    parser.add_argument(
        "--all-artifacts",
        action="store_true",
        help=(
            "S7 K1 finale: после base-стадий запустить cosign_sign_all "
            "(SBOM+wheels+plugin manifests+container image)"
        ),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    results: list[StageResult] = [run_sbom(args.output_dir)]
    if not args.skip_pip_audit:
        results.append(run_pip_audit())
    if not args.skip_bandit:
        results.append(run_bandit_tls())
    if not args.skip_cosign:
        results.append(run_cosign())
    if args.all_artifacts:
        results.append(run_cosign_all_artifacts())

    print("\n=== supply-chain summary ===")
    blocking_failures = 0
    for r in results:
        mark = "OK" if r.exit_code == 0 else ("SKIP" if r.skipped else "FAIL")
        print(f"  [{mark}] {r.name}: {r.message}")
        if r.exit_code != 0 and not r.skipped:
            blocking_failures += 1

    if blocking_failures > 0:
        print(
            f"\n[FAIL] supply-chain gate: {blocking_failures} blocking stage(s) failed"
        )
        return 1
    print("\n[OK] supply-chain gate: all blocking stages passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
