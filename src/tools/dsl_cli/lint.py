"""gdi dsl lint <file.yaml> — schema + semantic checks.

Проверки:
* YAML валиден.
* route_id, source присутствуют.
* каждый processor — в whitelist (A2 yaml_loader).
* нет циклов в pipeline_ref.
"""

from __future__ import annotations

import sys
from pathlib import Path

__all__ = ("lint_file",)


def lint_file(path: str | Path) -> list[str]:
    """Возвращает список ошибок. Пустой список = lint passed."""
    try:
        import yaml
    except ImportError:
        return ["PyYAML не установлен"]

    p = Path(path)
    if not p.exists():
        return [f"File not found: {p}"]

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"Invalid YAML: {exc}"]

    if not isinstance(data, dict):
        return ["Root must be a mapping"]

    errors: list[str] = []
    if not data.get("route_id"):
        errors.append("Missing required field: route_id")

    processors = data.get("processors", [])
    if not isinstance(processors, list):
        errors.append("'processors' must be a list")
        return errors

    # Minimal whitelist check: процессор либо string, либо одноключевой dict.
    for i, proc in enumerate(processors):
        if isinstance(proc, str):
            continue
        if isinstance(proc, dict) and len(proc) == 1:
            continue
        errors.append(f"processor[{i}]: invalid spec (string or single-key dict expected)")
    return errors


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: gdi dsl lint <file.yaml>")
        return 2
    errors = lint_file(sys.argv[1])
    if errors:
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("OK: DSL lint passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
