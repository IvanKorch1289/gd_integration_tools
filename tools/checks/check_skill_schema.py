"""CI-gate: JSON-Schema валидация ``[[skill]]`` TOML-секций (ADR-069, V11.2).

Sprint 35. Запускается через ``make skill-schema``::

    python tools/checks/check_skill_schema.py
    python tools/checks/check_skill_schema.py --root extensions/
    python tools/checks/check_skill_schema.py --emit-schema docs/reference/schemas/skill.schema.json

Логика
------
1. ``--emit-schema``: экспортирует SkillSpec JSON-Schema и завершается.
2. Иначе: сканирует ``--root`` (default: extensions/) на ``plugin.toml``.
3. Для каждого plugin.toml:
   - парсит через ``tomllib``;
   - извлекает секции ``[[skill]]``;
   - валидирует каждую через :class:`SkillSpec.model_validate`.

Exit codes
----------
* ``0`` — все секции валидны или ``--emit-schema`` выполнен.
* ``1`` — найдено ≥1 ошибок валидации.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _emit_schema(output_path: Path) -> None:
    """Экспортирует SkillSpec JSON-Schema в файл."""
    from src.backend.core.ai.skill_registry import SkillSpec

    schema = SkillSpec.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[skill-schema] JSON-Schema экспортирован: {output_path}")


def _validate_plugin(path: Path) -> list[str]:
    """Валидирует все ``[[skill]]`` секции в одном plugin.toml.

    Returns:
        Список строк с ошибками (пустой если валидно).
    """
    import tomllib

    from src.backend.core.ai.skill_registry import SkillSpec

    errors: list[str] = []

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return [f"TOML parse error: {exc}"]

    skills = raw.get("skill", [])
    if not isinstance(skills, list):
        return [f"top-level 'skill' must be array, got {type(skills).__name__}"]

    for i, skill in enumerate(skills):
        if not isinstance(skill, dict):
            errors.append(f"[skill][{i}]: must be object, got {type(skill).__name__}")
            continue
        try:
            SkillSpec.model_validate(skill)
        except (TypeError, ValueError) as exc:
            errors.append(f"[skill][{i}]: {exc}")

    return errors


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default="extensions",
        help="Корень поиска plugin.toml (default: extensions/).",
    )
    parser.add_argument(
        "--emit-schema",
        default=None,
        help="Если задан — экспортирует SkillSpec JSON-Schema и выходит.",
    )
    args = parser.parse_args()

    if args.emit_schema:
        _emit_schema(Path(args.emit_schema))
        return 0

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"[skill-schema] {root} не существует — нечего валидировать")
        return 0
    if not root.is_dir():
        print(f"[skill-schema] {root} не директория")
        return 1

    toml_files = sorted(root.rglob("plugin.toml"))
    if not toml_files:
        print(f"[skill-schema] plugin.toml не найдены в {root}")
        return 0

    all_errors: list[tuple[Path, str]] = []
    for toml_path in toml_files:
        errors = _validate_plugin(toml_path)
        if errors:
            for err in errors:
                all_errors.append((toml_path, err))
            print(f"  [FAIL] {toml_path.relative_to(root)}")
            for err in errors:
                print(f"        {err}")
        else:
            print(f"  [OK]   {toml_path.relative_to(root)}")

    if all_errors:
        unique_files = len({p for p, _ in all_errors})
        print(
            f"\n[skill-schema] {unique_files} plugin.toml с ошибками, {len(all_errors)} total"
        )
        return 1

    print(f"\n[skill-schema] все {len(toml_files)} plugin.toml валидны")
    return 0


if __name__ == "__main__":
    sys.exit(main())
