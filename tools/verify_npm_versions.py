"""S45 W1 (TD-006 partial): verify npm version pins в package.json реальны.

Mirror of ``tools/verify_pypi_versions.py`` (S44 W3) для npm ecosystem.
Ловит phantom versions в ``frontend/admin-react/package.json`` и других
package.json файлах (recursive scan).

Context: 2026-06-05 security audit рекомендовал phantom npm versions
(``vite@^6.4.6`` — max в npm = 6.0.2, latest = 8.0.16). ``npm install``
FAILED. S44 W3 закрыл PyPI side; S45 W1 закрывает npm side → TD-006 done.

Использование:
    uv run python tools/verify_npm_versions.py
    uv run python tools/verify_npm_versions.py --strict  # exit 1 on warnings
    uv run python tools/verify_npm_versions.py --package vite

Network: npm Registry API (https://registry.npmjs.org/{pkg}). 5s timeout.
При отсутствии сети → graceful SKIP warning, не fatal.

NOT a full security audit — sanity check для предотвращения phantom
version regressions. Per TD-006 closure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

__all__ = ("verify_package_json_pins", "check_phantom_npm_versions")


# Semver pin patterns:
#   ^1.2.3, ~1.2.3, 1.2.3, 1.x, 1.2.x, >=1.2.3, etc.
_PIN_RE = re.compile(
    r"^(?P<op>[\^~>=<]*)?\s*"
    r"(?P<major>\d+)"
    r"(?:\.(?P<minor>\d+))?"
    r"(?:\.(?P<patch>\d+))?"
    r"(?P<rest>.*)$"
)


def _parse_pin(pin: str) -> tuple[str, str, int] | None:
    """Возвращает (op, major_str, major_int) или None если не semver.

    Поддерживает: ^, ~, >=, <=, >, <, =, exact (1.2.3), range.
    Возвращает только major version для сравнения с npm latest.
    """
    pin = pin.strip()
    if pin in ("*", "latest", "x", "X", ""):
        return None
    m = _PIN_RE.match(pin)
    if not m or not m.group("major"):
        return None
    op = m.group("op") or "="
    return (op, m.group("major"), int(m.group("major")))


def _fetch_npm_max(name: str, *, timeout: float = 5.0) -> str | None:
    """Запрос к npm Registry API. Возвращает max version или None."""
    url = f"https://registry.npmjs.org/{name}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        latest = data.get("dist-tags", {}).get("latest", "")
        return str(latest) if latest else None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _iter_package_jsons(root: Path) -> list[Path]:
    """Возвращает все package.json под root (skip node_modules)."""
    return [
        p
        for p in root.rglob("package.json")
        if "node_modules" not in p.parts
    ]


def _extract_pins(data: dict[str, Any]) -> dict[str, str]:
    """Извлекает все version pins из dependencies + devDependencies."""
    pins: dict[str, str] = {}
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        for pkg, ver in (data.get(section) or {}).items():
            pins[pkg] = str(ver)
    return pins


def _version_tuple(v: str) -> tuple[int, ...]:
    """Парсит '1.2.3' → (1, 2, 3)."""
    parts: list[int] = []
    for chunk in v.split("."):
        m = re.match(r"^(\d+)", chunk)
        if m:
            parts.append(int(m.group(1)))
        else:
            break
    return tuple(parts)


def check_phantom_npm_versions(
    root: str = ".",
    *,
    timeout: float = 5.0,
) -> list[dict[str, str]]:
    """Сканирует все package.json под root и проверяет pins против npm.

    Returns:
        List of warnings: {package, pinned, actual_max, source_file, message}.
        Empty list = OK.
    """
    root_path = Path(root)
    warnings: list[dict[str, str]] = []
    for pkg_json in _iter_package_jsons(root_path):
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for pkg_name, pin in _extract_pins(data).items():
            parsed = _parse_pin(pin)
            if not parsed:
                continue
            op, _pinned_major_str, pinned_major = parsed
            actual_max = _fetch_npm_max(pkg_name, timeout=timeout)
            if actual_max is None:
                warnings.append(
                    {
                        "package": pkg_name,
                        "pinned": pin,
                        "actual_max": "?",
                        "source_file": str(pkg_json),
                        "message": f"SKIP: npm lookup failed для {pkg_name!r}",
                    }
                )
                continue
            actual_major = _version_tuple(actual_max)[0]
            # Only flag if pinned major > actual major (real phantom).
            # Allow == (matches) or < (older pin, not phantom).
            if pinned_major > actual_major:
                warnings.append(
                    {
                        "package": pkg_name,
                        "pinned": pin,
                        "actual_max": actual_max,
                        "source_file": str(pkg_json),
                        "message": (
                            f"PHANTOM: {pkg_name} pin {pin} (major {pinned_major}) "
                            f"> npm max {actual_max} (major {actual_major})"
                        ),
                    }
                )
    return warnings


def verify_package_json_pins(
    root: str = ".", *, strict: bool = False
) -> int:
    """CLI entry point. Returns exit code."""
    warnings = check_phantom_npm_versions(root)
    if not warnings:
        print("OK: все pins в package.json валидны (npm registry).")
        return 0
    print(f"Найдено {len(warnings)} warning(s):")
    for w in warnings:
        print(f"  [{w['source_file']}] {w['message']}")
    return 1 if strict else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 при phantom version warnings.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Root dir для рекурсивного scan (default: .).",
    )
    args = parser.parse_args(argv)
    return verify_package_json_pins(args.root, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
