#!/usr/bin/env python3
"""Аудит ``src/backend/core/config/features.py`` (K10 Sprint 2 platform gate).

Назначение:
    Проверяет default-OFF политику реестра feature-flag:
    - все поля FeatureFlags имеют default=False;
    - все поля имеют непустой description (audit-комментарий);
    - все поля имеют title.

При нарушениях — exit 1. Используется в pre-commit и CI gate.

Запуск::

    python tools/check_feature_flags.py [--allow-non-off NAME1,NAME2]
"""

from __future__ import annotations

import argparse
import sys

try:
    from src.backend.core.config.features import FeatureFlags
except ImportError as exc:
    print(f"✗ Импорт FeatureFlags провалился: {exc}", file=sys.stderr)
    sys.exit(2)


def audit(allow_non_off: set[str]) -> list[str]:
    """Возвращает список ошибок аудита (пустой → всё ОК)."""
    errors: list[str] = []
    for name, field in FeatureFlags.model_fields.items():
        if field.default is not False and name not in allow_non_off:
            errors.append(
                f"feature_flags.{name}: default={field.default!r}, "
                f"должен быть False (default-OFF policy). "
                f"Если намеренно — добавить в --allow-non-off."
            )
        if not field.description:
            errors.append(
                f"feature_flags.{name}: отсутствует description "
                f"(audit-комментарий с owner/ETA обязателен)."
            )
        if not field.title:
            errors.append(f"feature_flags.{name}: отсутствует title.")
    return errors


def main() -> int:
    """CLI-entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-non-off",
        default="",
        help="Список flag-name через запятую, которые разрешено иметь "
        "default!=False (исключения из default-OFF policy).",
    )
    args = parser.parse_args()
    allow = {n.strip() for n in args.allow_non_off.split(",") if n.strip()}

    errors = audit(allow)
    if errors:
        print("✗ feature-flag audit FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    total = len(FeatureFlags.model_fields)
    print(
        f"✓ feature-flag audit OK: {total} flag, все default-OFF, "
        f"все имеют title + description."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
