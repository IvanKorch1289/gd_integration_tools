"""S44 W3 (TD-006): verify that PyPI version pins в pyproject.toml реальны.

Context: 2026-06-05 security audit рекомендовал **phantom versions**:
- chromadb>=1.5.20,<2.0.0 (max в PyPI = 1.5.9)
- vite@^6.4.6 (max в npm = 6.0.2)

`uv sync` / `npm install` оба FAILED. Lesson: AI security advisories
могут hallucinate version numbers. **Always verify against registry
BEFORE applying patches.**

Этот скрипт:
1. Парсит pyproject.toml → list of (package, version_spec).
2. Для каждого package запрашивает PyPI JSON API → max version.
3. Если заявленный upper bound > max available → **PHANTOM WARNING**.
4. Exit code 0 если OK, 1 если phantom versions found.

Использование:
    uv run python tools/verify_pypi_versions.py
    uv run python tools/verify_pypi_versions.py --strict  # exit 1 on warnings
    uv run python tools/verify_pypi_versions.py --package chromadb

S44 W3 scope: PyPI only (npm deferred до S45+ D). Network access required
(PyPI JSON API). При отсутствии сети → graceful warning, не fatal.

NOT a full security audit — это **sanity check** для предотвращения
phantom version regressions. Per TD-006.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from typing import Any

__all__ = ("verify_pyproject_pins", "check_phantom_versions")


# regex: package[extras] op_version, op_version
_PIN_RE = re.compile(
    r"^([A-Za-z0-9_.\-]+(?:\[[A-Za-z0-9_,\-]+\])?)\s*"
    r"(>=|<=|==|!=|>|<|~=)\s*"
    r"([A-Za-z0-9_.\-\+!]+)"
    r"(?:\s*,\s*(>=|<=|==|!=|>|<|~=)\s*([A-Za-z0-9_.\-\+!]+))?$"
)


def _parse_pin(dep: str) -> tuple[str, str] | None:
    """Возвращает (package_name, max_version_string) или None если pin не строгий."""
    m = _PIN_RE.match(dep.strip())
    if not m:
        return None
    name = m.group(1).split("[")[0]
    # Берём последний upper bound (если есть) для <X.Y.Z
    op1, ver1, op2, _ver2 = m.group(2), m.group(3), m.group(4), m.group(5)
    if op2 and op2 in ("<", "<="):
        return (name.lower(), ver1 if op1 in (">", ">=", "==") else ver1)
    if op1 in ("<", "<="):
        return (name.lower(), ver1)
    if op1 in (">", ">=", "==", "~="):
        # Нет upper bound — skip
        return None
    return None


def _fetch_pypi_max(name: str, *, timeout: float = 5.0) -> str | None:
    """Запрос к PyPI JSON API. Возвращает max version или None при ошибке."""
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return str(data.get("info", {}).get("version", ""))
    except urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError:
        return None


def _version_tuple(v: str) -> tuple[int, ...]:
    """Парсит '1.5.9' → (1, 5, 9). Pre-release suffix игнорируется."""
    parts: list[int] = []
    for chunk in v.split("."):
        m = re.match(r"^(\d+)", chunk)
        if m:
            parts.append(int(m.group(1)))
        else:
            break
    return tuple(parts)


def check_phantom_versions(
    pyproject_path: str = "pyproject.toml", *, timeout: float = 5.0
) -> list[dict[str, str]]:
    """Проверяет все upper-bound pins в pyproject.toml против PyPI.

    Returns:
        List of warnings, каждая = {package, pinned, actual_max, message}.
        Empty list = OK.
    """
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    deps = data.get("project", {}).get("dependencies", [])

    warnings: list[dict[str, str]] = []
    for dep in deps:
        parsed = _parse_pin(dep)
        if not parsed:
            continue
        name, pinned_max = parsed
        actual_max = _fetch_pypi_max(name, timeout=timeout)
        if actual_max is None:
            # Network error или package не найден — skip с quiet warning.
            warnings.append(
                {
                    "package": name,
                    "pinned": pinned_max,
                    "actual_max": "?",
                    "message": f"SKIP: PyPI lookup failed для {name!r}",
                }
            )
            continue
        if _version_tuple(pinned_max) > _version_tuple(actual_max):
            warnings.append(
                {
                    "package": name,
                    "pinned": pinned_max,
                    "actual_max": actual_max,
                    "message": (
                        f"PHANTOM: {name} pin {pinned_max} > PyPI max {actual_max}"
                    ),
                }
            )
    return warnings


def verify_pyproject_pins(
    pyproject_path: str = "pyproject.toml", *, strict: bool = False
) -> int:
    """Точка входа CLI. Returns exit code."""
    warnings = check_phantom_versions(pyproject_path)
    if not warnings:
        print("OK: все pins в pyproject.toml валидны (PyPI).")
        return 0
    print(f"Найдено {len(warnings)} warning(s):")
    for w in warnings:
        print(f"  [{w['package']}] {w['message']}")
    return 1 if strict else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--strict", action="store_true", help="Exit 1 при phantom version warnings."
    )
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path к pyproject.toml (default: ./pyproject.toml).",
    )
    args = parser.parse_args(argv)
    return verify_pyproject_pins(args.pyproject, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
