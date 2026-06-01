#!/usr/bin/env python3
"""Guard для W26: проверяет, что 11 fallback chain'ов корректно описаны.

Контракт (см. ADR-036 / docs/reference/dsl/resilience.md):

* в ``config_profiles/base.yml`` секция ``resilience.breakers`` содержит все
  11 канонических компонентов из ``RESILIENCE_COMPONENTS``;
* в секции ``resilience.fallbacks`` для тех же 11 компонентов задана
  непустая ``chain``;
* ``RESILIENCE_COMPONENTS`` (источник правды) совпадает с keys в YAML;
* для каждого компонента задан ненулевой ``chain``.

Запуск:
    uv run python3 tools/check_fallback_matrix.py

Возвращает 0 при success, 1 при ошибках. Используется в ``make
readiness-check`` (см. Makefile target).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.backend.infrastructure.resilience.registration import (  # noqa: E402
    RESILIENCE_COMPONENTS,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def main() -> int:
    base_path = PROJECT_ROOT / "config_profiles" / "base.yml"
    if not base_path.is_file():
        print(f"ERROR: base.yml not found at {base_path}")
        return 1

    cfg = _load_yaml(base_path).get("resilience") or {}
    breakers = cfg.get("breakers") or {}
    fallbacks = cfg.get("fallbacks") or {}

    expected = set(RESILIENCE_COMPONENTS)
    issues: list[str] = []

    missing_breakers = expected - set(breakers)
    if missing_breakers:
        issues.append(
            "  - Missing breakers in resilience.breakers: "
            + ", ".join(sorted(missing_breakers))
        )

    missing_fallbacks = expected - set(fallbacks)
    if missing_fallbacks:
        issues.append(
            "  - Missing entries in resilience.fallbacks: "
            + ", ".join(sorted(missing_fallbacks))
        )

    extra_breakers = set(breakers) - expected
    if extra_breakers:
        issues.append(
            "  - Unknown breakers (not in RESILIENCE_COMPONENTS): "
            + ", ".join(sorted(extra_breakers))
        )

    extra_fallbacks = set(fallbacks) - expected
    if extra_fallbacks:
        issues.append(
            "  - Unknown fallbacks (not in RESILIENCE_COMPONENTS): "
            + ", ".join(sorted(extra_fallbacks))
        )

    for component in expected & set(fallbacks):
        chain = fallbacks[component].get("chain") or []
        if not chain:
            issues.append(f"  - Empty fallback chain for component '{component}'")

    if issues:
        print("ERROR: fallback matrix check не прошёл:")
        for line in issues:
            print(line)
        return 1

    print(
        f"OK: fallback matrix consistent ({len(expected)} components, "
        f"all chains non-empty)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
