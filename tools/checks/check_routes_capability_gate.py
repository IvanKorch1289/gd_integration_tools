#!/usr/bin/env python3
"""CI gate: routes capability-gate (K-ARCH-3, Sprint 17).

Назначение:
    Валидирует структурный invariant V11 RouteLoader (S17 K-ARCH-3):

    1. ``services/routes/loader.py`` содержит вызов
       ``self._gate.declare(...)`` ДО ``self._registrar(...)``;
    2. ``services/routes/loader.py`` эмитит audit-event
       ``route.capabilities.allocated`` сразу после declare.

    При несоответствии — exit-code 1 с подробным reason.

Запуск::

    python tools/checks/check_routes_capability_gate.py [--strict]

При ``--strict`` дополнительно требуется наличие feature-flag
``routes_capability_gate_strict`` в ``src/backend/core/config/features.py``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LOADER_PATH = Path("src/backend/services/routes/loader.py")
FEATURES_PATH = Path("src/backend/core/config/features.py")
STRICT_FLAG = "routes_capability_gate_strict"


def validate() -> list[str]:
    """Возвращает список ошибок (пустой → всё ОК)."""
    errors: list[str] = []

    if not LOADER_PATH.exists():
        return [f"{LOADER_PATH} отсутствует"]

    src = LOADER_PATH.read_text(encoding="utf-8")

    # 1) declare(...) присутствует.
    if not re.search(r"self\._gate\.declare\(", src):
        errors.append(
            f"{LOADER_PATH}: отсутствует вызов self._gate.declare(...)"
        )

    # 2) audit-event 'route.capabilities.allocated' эмитится.
    if "route.capabilities.allocated" not in src:
        errors.append(
            f"{LOADER_PATH}: отсутствует audit-event "
            "'route.capabilities.allocated' после declare()"
        )

    # 3) declare идёт ДО registrar (порядковая проверка).
    declare_pos = src.find("self._gate.declare(")
    registrar_pos = src.find("self._registrar(")
    if declare_pos != -1 and registrar_pos != -1 and declare_pos > registrar_pos:
        errors.append(
            f"{LOADER_PATH}: self._gate.declare(...) идёт ПОСЛЕ "
            "self._registrar(...) — нарушение порядка K-ARCH-3"
        )

    return errors


def validate_strict() -> list[str]:
    """Дополнительная проверка наличия feature-flag (--strict)."""
    errors: list[str] = []
    if not FEATURES_PATH.exists():
        errors.append(f"{FEATURES_PATH} отсутствует")
        return errors
    src = FEATURES_PATH.read_text(encoding="utf-8")
    if f"{STRICT_FLAG}:" not in src:
        errors.append(
            f"{FEATURES_PATH}: feature-flag '{STRICT_FLAG}' не найден"
        )
    return errors


def main() -> int:
    """CLI-entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Дополнительно проверяет наличие feature-flag в features.py",
    )
    args = parser.parse_args()

    errors = validate()
    if args.strict:
        errors.extend(validate_strict())

    if errors:
        print("✗ routes capability-gate validation FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(
        "✓ routes capability-gate OK: declare() ДО registrar() + "
        "audit-event 'route.capabilities.allocated' эмитится"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
