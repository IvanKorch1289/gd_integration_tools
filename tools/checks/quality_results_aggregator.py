"""Machine-readable quality-results aggregator (25.09 audit W3).

Per audit W3: «Нужен machine-readable quality-results.json, который
агрегирует command, exit, duration, tool version, HEAD, counts и
artifact hashes. README/roadmap должны генерировать status только из
этого файла».

Этот script запускает все structural gates, собирает результаты в
единый machine-readable формат и пишет ``quality-results.json``.

Output schema (one JSON object per gate):
{
  \"gate\": \"check_layers\",
  \"command\": \"python3.14 tools/check_layers.py\",
  \"exit_code\": 0,
  \"duration_seconds\": 0.123,
  \"head\": \"bb775cd32\",
  \"tool_version\": null,
  \"counts\": {\"new_violations\": 0, \"legacy_baseline\": 22},
  \"status\": \"PASS\",
  \"artifact_hash\": \"sha256:...\",
  \"timestamp\": \"2026-09-25T13:00:00Z\"
}

Per audit W3 spec, gate status ДОЛЖЕН быть один из:
- PASS — проверка выполнена и критерий соблюдён;
- FAIL — проверка выполнена и критерий нарушен;
- TOOL_FAILURE — анализатор упал (subprocess exception);
- ENV_FAILURE — окружение неполно (uv sync, Docker missing);
- NOT_APPLICABLE — gate неприменим в текущем контексте.

Output: ``.audit/quality-results.json`` + human-readable summary в stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = PROJECT_ROOT / ".audit"
OUTPUT_PATH = AUDIT_DIR / "quality-results.json"

# Per audit W3 spec: «неполное окружение означает UNKNOWN, а не PASS или FAIL».
# Aggregator использует venv Python если доступен (полные deps), иначе
# fall-back на python3.14 (может быть без deps → ENV_FAILURE).
_VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
PYTHON_BIN = (
    str(_VENV_PYTHON) if _VENV_PYTHON.is_file() else "python3.14"
)


def _gate_result(
    gate: str,
    command: list[str],
    cwd: Path = PROJECT_ROOT,
    tool_version: str | None = None,
    extra_counts: dict[str, int] | None = None,
) -> dict:
    """Run single gate, capture metrics, return result dict.

    Args:
        gate: human-readable gate name (e.g., ``check_layers``).
        command: command + args list для subprocess.run.
        cwd: working directory (default: PROJECT_ROOT).
        tool_version: optional version string (e.g., ``temporalio 1.32.0``).
        extra_counts: дополнительные метрики для output (e.g., legacy count).

    Returns:
        Dict с keys: gate, command, exit_code, duration_seconds,
        head, tool_version, counts, status, artifact_hash, timestamp.
    """
    head = _get_head()
    start = time.monotonic()
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=180,
        )
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        return _make_result(
            gate=gate,
            command=command,
            head=head,
            exit_code=-1,
            duration=time.monotonic() - start,
            status="ENV_FAILURE",
            tool_version=tool_version,
            message="timeout (180s)",
            extra_counts=extra_counts,
        )
    except Exception as exc:
        return _make_result(
            gate=gate,
            command=command,
            head=head,
            exit_code=-1,
            duration=time.monotonic() - start,
            status="TOOL_FAILURE",
            tool_version=tool_version,
            message=f"{type(exc).__name__}: {exc}",
            extra_counts=extra_counts,
        )

    duration = time.monotonic() - start
    status = _classify_status(exit_code, stderr)
    artifact_hash = hashlib.sha256(
        (stdout + stderr).encode("utf-8", errors="ignore")
    ).hexdigest()[:16]

    counts = _extract_counts(gate, exit_code, stdout, stderr)
    if extra_counts:
        counts.update(extra_counts)

    return _make_result(
        gate=gate,
        command=command,
        head=head,
        exit_code=exit_code,
        duration=duration,
        status=status,
        tool_version=tool_version,
        stdout_tail=stdout[-200:] if stdout else "",
        stderr_tail=stderr[-200:] if stderr else "",
        artifact_hash=artifact_hash,
        counts=counts,
        extra_counts=None,
    )


def _classify_status(exit_code: int, stderr: str) -> str:
    """Classify gate result per audit W3 status taxonomy.

    Per audit W3: каждый gate должен возвращать один из статусов:
    PASS / FAIL / TOOL_FAILURE / ENV_FAILURE / NOT_APPLICABLE.
    """
    if exit_code == 0:
        return "PASS"
    if exit_code == 2:
        # Convention: exit 2 → ENV_FAILURE (mypy wrapper convention).
        return "ENV_FAILURE"
    if exit_code < 0 or exit_code >= 128:
        return "TOOL_FAILURE"
    return "FAIL"


def _extract_counts(
    gate: str, exit_code: int, stdout: str, stderr: str
) -> dict[str, int]:
    """Extract numeric counts из gate stdout/stderr.

    Best-effort parsing — если gate output не распознан, возвращаем
    базовый счёт (exit_code, head length).
    """
    counts: dict[str, int] = {}
    text = (stdout or "") + "\n" + (stderr or "")

    # Generic: match common patterns.
    if "new violations" in text.lower() or "новых нарушений" in text.lower():
        import re

        m = re.search(
            r"(\d+)\s*(?:новых|new)\s*(?:violations|нарушени)", text, re.IGNORECASE
        )
        if m:
            counts["new_violations"] = int(m.group(1))

    if "missing docstrings" in text.lower():
        import re

        m = re.search(r"(\d+)\s*missing", text, re.IGNORECASE)
        if m:
            counts["missing_docstrings"] = int(m.group(1))

    if "unknown" in text.lower() and "user-data" in text.lower():
        import re

        m = re.search(r"unknown[:\s]+(\d+)", text, re.IGNORECASE)
        if m:
            counts["unknown_callsites"] = int(m.group(1))
        m = re.search(r"user-data[:\s]+(\d+)", text, re.IGNORECASE)
        if m:
            counts["user_data_callsites"] = int(m.group(1))

    if "mypy errors" in text.lower():
        import re

        m = re.search(r"mypy errors[:\s]+(\d+)", text, re.IGNORECASE)
        if m:
            counts["mypy_errors"] = int(m.group(1))

    if "missing_filter" in text.lower():
        import re

        m = re.search(r"missing\s+tenant\s+filter\s+candidates[:\s]+(\d+)", text, re.IGNORECASE)
        if m:
            counts["missing_tenant_filter"] = int(m.group(1))

    if "allowlisted" in text.lower():
        import re

        m = re.search(r"allowlisted[:\s]+(\d+)", text, re.IGNORECASE)
        if m:
            counts["allowlisted"] = int(m.group(1))

    if "unclassified" in text.lower():
        import re

        m = re.search(r"unclassified[:\s]+(\d+)", text, re.IGNORECASE)
        if m:
            counts["unclassified"] = int(m.group(1))

    return counts


def _make_result(
    gate: str,
    command: list[str],
    head: str,
    exit_code: int,
    duration: float,
    status: str,
    tool_version: str | None = None,
    message: str | None = None,
    stdout_tail: str = "",
    stderr_tail: str = "",
    artifact_hash: str = "",
    counts: dict[str, int] | None = None,
    extra_counts: dict[str, int] | None = None,
) -> dict:
    """Build final result dict per audit W3 schema."""
    return {
        "gate": gate,
        "command": " ".join(command),
        "exit_code": exit_code,
        "duration_seconds": round(duration, 3),
        "head": head,
        "tool_version": tool_version,
        "status": status,
        "counts": counts or {},
        "artifact_hash": f"sha256:{artifact_hash}" if artifact_hash else None,
        "message": message,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }


def _get_head() -> str:
    """Get current HEAD short SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Machine-readable quality-results aggregator. "
            "Per audit W3: status один из PASS/FAIL/TOOL_FAILURE/ENV_FAILURE/NOT_APPLICABLE."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Output JSON path (default: .audit/quality-results.json)",
    )
    args = parser.parse_args(argv)

    # Run all gates per audit spec.
    gates: list[dict] = []

    # 1. compileall
    gates.append(
        _gate_result(
            gate="compileall",
            command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "-m", "compileall", "-q", "src/backend"],
            tool_version=f"python {_python_version()}",
        )
    )

    # 2. check_layers
    gates.append(_gate_result(gate="check_layers", command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "tools/check_layers.py"]))

    # 3. check_docstrings
    gates.append(
        _gate_result(
            gate="check_docstrings", command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "tools/check_docstrings.py"]
        )
    )

    # 4. classify_object_authorization --strict
    gates.append(
        _gate_result(
            gate="classify_object_authorization",
            command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "tools/classify_object_authorization.py", "--strict"],
        )
    )

    # 5. check_tenant_isolation --strict (W3.5 allowlist)
    gates.append(
        _gate_result(
            gate="check_tenant_isolation",
            command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "tools/checks/check_tenant_isolation.py", "--strict"],
        )
    )

    # 6. check_privacy_lifecycle --strict
    gates.append(
        _gate_result(
            gate="check_privacy_lifecycle",
            command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "tools/checks/check_privacy_lifecycle.py", "--strict"],
        )
    )

    # 7. check_dsl_processors_imports --strict (AST gate)
    gates.append(
        _gate_result(
            gate="check_dsl_processors_imports",
            command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "tools/checks/check_dsl_processors_imports.py", "--strict"],
        )
    )

    # 8. verify_test_profiles --strict
    gates.append(
        _gate_result(
            gate="verify_test_profiles",
            command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "tools/checks/verify_test_profiles.py", "--strict"],
        )
    )

    # 9. mypy budget (max=5 per audit spec)
    gates.append(
        _gate_result(
            gate="mypy_budget",
            command=["/home/user/dev/gd_integration_tools/.venv/bin/python", "tools/checks/mypy_budget.py", "--max", "5"],
            tool_version=f"python {_python_version()}",
        )
    )

    # 10. ruff check
    gates.append(
        _gate_result(
            gate="ruff",
            command=["ruff", "check", "src/backend"],
            tool_version=_tool_version("ruff", ["ruff", "--version"]),
        )
    )

    # Aggregate.
    overall_status_counts: dict[str, int] = {}
    for g in gates:
        s = g["status"]
        overall_status_counts[s] = overall_status_counts.get(s, 0) + 1

    overall_status = (
        "PASS"
        if all(g["status"] in {"PASS", "NOT_APPLICABLE"} for g in gates)
        else "FAIL"
    )

    result = {
        "audit": "GD Integration Tools 25.09.2026",
        "head": _get_head(),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "overall_status": overall_status,
        "status_counts": overall_status_counts,
        "gate_count": len(gates),
        "gates": gates,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    # Human-readable summary.
    print(f"Quality Results Aggregator (audit 25.09.2026)")
    print(f"  HEAD: {result['head']}")
    print(f"  Output: {args.output}")
    print(f"  Overall: {overall_status}")
    print(f"  Gates: {len(gates)}")
    for s, n in sorted(overall_status_counts.items()):
        print(f"    {s}: {n}")
    print()
    for g in gates:
        status_marker = "✅" if g["status"] == "PASS" else "❌"
        print(
            f"  {status_marker} {g['gate']:<35} exit={g['exit_code']:>3} "
            f"duration={g['duration_seconds']:.2f}s status={g['status']}"
        )
        if g.get("counts"):
            counts_str = ", ".join(f"{k}={v}" for k, v in g["counts"].items())
            print(f"      counts: {counts_str}")

    return 0 if overall_status == "PASS" else 1


def _python_version() -> str:
    try:
        result = subprocess.run(
            ["/home/user/dev/gd_integration_tools/.venv/bin/python", "--version"], capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() or result.stderr.strip()
    except Exception:
        return "unknown"


def _tool_version(name: str, version_cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(
            version_cmd, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0]
        return None
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
