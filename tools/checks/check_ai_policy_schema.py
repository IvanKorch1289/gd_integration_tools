"""CI-gate: JSON-Schema валидация ``ai_policies/*.policy.yaml`` (ADR-NEW-20).

Sprint 25 W2. Запускается через ``make ai-policy-schema`` (после добавления
target в Makefile) или напрямую::

    python tools/checks/check_ai_policy_schema.py
    python tools/checks/check_ai_policy_schema.py --root ai_policies
    python tools/checks/check_ai_policy_schema.py --emit-schema docs/reference/schemas/ai_policy.schema.json

Логика
------
1. Сканирует ``--root`` (default: ``ai_policies/``) на ``*.policy.yaml``.
2. Для каждого файла:

   * парсит через ``yaml.safe_load``;
   * валидирует через :class:`AIPolicySpec.model_validate` (Pydantic v2).
3. Опционально: с ``--emit-schema`` экспортирует JSON-Schema из Pydantic
   в указанный файл (для документации / external tooling).

Exit codes
----------
* ``0`` — все YAML-файлы валидны.
* ``1`` — найдено ≥1 ошибок валидации.

См. docs/adr/0067-ai-policy-spec-dsl.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.backend.core.ai.policy import AIPolicySpec


def _validate_yaml(path: Path) -> tuple[bool, str]:
    """Валидирует один YAML-файл через :class:`AIPolicySpec`.

    Args:
        path: Путь к ``*.policy.yaml``.

    Returns:
        Tuple ``(ok, message)``: ``ok=True`` → ``message=""``; иначе текст
        ошибки.
    """
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        return False, f"YAML parse error: {exc}"
    try:
        AIPolicySpec.model_validate(raw)
    except (TypeError, ValueError) as exc:
        return False, f"AIPolicySpec validation error: {exc}"
    return True, ""


def main() -> int:
    """Точка входа CLI.

    Returns:
        ``0`` — все policies валидны; ``1`` — есть ошибки.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default="ai_policies",
        help="Корень поиска *.policy.yaml (default: ai_policies/).",
    )
    parser.add_argument(
        "--emit-schema",
        default=None,
        help="Если задан — экспортирует JSON-Schema из AIPolicySpec в указанный файл.",
    )
    args = parser.parse_args()

    if args.emit_schema:
        schema = AIPolicySpec.model_json_schema()
        out_path = Path(args.emit_schema)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"✓ JSON-Schema экспортирован: {out_path}")
        return 0

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"✓ check_ai_policy_schema: {root} не существует — нечего валидировать")
        return 0
    if not root.is_dir():
        print(f"✗ check_ai_policy_schema: {root} не директория")
        return 1

    yaml_files = sorted(root.glob("*.policy.yaml"))
    if not yaml_files:
        print(f"✓ check_ai_policy_schema: {root} не содержит *.policy.yaml")
        return 0

    failed: list[tuple[Path, str]] = []
    for path in yaml_files:
        ok, msg = _validate_yaml(path)
        if ok:
            print(f"  ✓ {path}")
        else:
            print(f"  ✗ {path}: {msg}")
            failed.append((path, msg))

    if failed:
        print(
            f"\n✗ check_ai_policy_schema: {len(failed)} файл(а/ов) не прошли валидацию"
        )
        return 1
    print(f"\n✓ check_ai_policy_schema: {len(yaml_files)} файл(а/ов) валидны")
    return 0


if __name__ == "__main__":
    sys.exit(main())
